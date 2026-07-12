from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import time
from datetime import datetime, timezone

import config
import safety
import signals
from backtest_feed import BacktestFeed
from backtest_html import write_index
from backtest_report import (
    compute_summary,
    downsample_equity,
    git_commit_info,
    make_run_dir_name,
    write_run,
    write_trade_log_csv,
)
from config import BACKTEST_SYNTHETIC_SPREAD_PCT
from execution import ExecutionEngine
from main import wire_strategy
from risk import PAPER_BALANCE_USDT
from state import MarketState

RUNS_DIR = "backtest_runs"


def _parse_date_utc(value: str) -> int:
    """Parses YYYY-MM-DD as milliseconds since epoch, UTC midnight."""
    dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def parse_args(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest the BTC scalping strategy against historical Binance data.")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (UTC, inclusive)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (UTC, exclusive)")
    parser.add_argument("--balance", type=float, default=PAPER_BALANCE_USDT)
    parser.add_argument("--spread-pct", type=float, default=BACKTEST_SYNTHETIC_SPREAD_PCT)
    parser.add_argument("--out", default="backtest_trades.csv")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--label", default=None, help="Etiqueta corta para identificar la corrida en el comparador")
    parser.add_argument("--variant", choices=("fade", "break"), default="fade",
                        help="Modelo de entrada: fade (anticipado) o break (confirmación de ruptura)")
    parser.add_argument("--disable-gate", action="append", default=None,
                        choices=signals.GATE_NAMES, dest="disable_gate",
                        help="Apaga un gate de entrada (repetible)")
    parser.add_argument("--squeeze-compression", type=float, default=config.SQUEEZE_COMPRESSION_ATR)
    parser.add_argument("--squeeze-min-bars", type=int, default=config.SQUEEZE_MIN_BARS)
    return parser.parse_args(argv)


def validate_range(start_ms: int, end_ms: int) -> None:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if start_ms >= end_ms:
        raise ValueError("--start must be before --end")
    if end_ms > now_ms:
        raise ValueError("--end cannot be in the future")


async def run_backtest(args: argparse.Namespace, exchange=None) -> dict:
    t0 = time.monotonic()
    start_ms = _parse_date_utc(args.start)
    end_ms = _parse_date_utc(args.end)
    validate_range(start_ms, end_ms)

    config.SQUEEZE_COMPRESSION_ATR = args.squeeze_compression
    config.SQUEEZE_MIN_BARS = args.squeeze_min_bars
    signals.ENTRY_VARIANT = args.variant
    signals.DISABLED_GATES = set(args.disable_gate or ())
    signals.reset_signal_stats()

    _, state_file_path = tempfile.mkstemp(prefix="backtest_safety_state_", suffix=".json")
    safety.STATE_FILE_PATH = state_file_path

    state = MarketState()
    trade_records: list = []
    engine = ExecutionEngine(state, on_trade_closed=trade_records.append)
    feed = BacktestFeed(state, exchange=exchange, spread_pct=args.spread_pct, use_cache=not args.no_cache)
    wire_strategy(state, feed, engine)

    await feed.replay(start_ms, end_ms)

    summary = compute_summary(trade_records)
    summary["gate_vetoes"] = dict(signals.GATE_VETO_COUNTS)
    summary["signals_fired"] = signals.SIGNAL_STATS["fired"]
    write_trade_log_csv(trade_records, args.out)

    closes = [r for r in trade_records if not r["is_partial"]]
    equity_curve = downsample_equity([r["total_trade_net"] for r in closes])
    git_info = git_commit_info()
    meta = {
        "start": args.start, "end": args.end, "balance": args.balance,
        "spread_pct": args.spread_pct, "label": args.label, "out": args.out,
        "git_commit": git_info["commit"], "git_dirty": git_info["dirty"],
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "duration_seconds": round(time.monotonic() - t0, 1),
        "format_version": 1,
        "variant": args.variant,
        "disabled_gates": sorted(signals.DISABLED_GATES),
        "squeeze_compression": args.squeeze_compression,
        "squeeze_min_bars": args.squeeze_min_bars,
    }
    dir_name = make_run_dir_name(datetime.now(timezone.utc), args.label)
    run_dir = write_run(RUNS_DIR, dir_name, meta, summary, equity_curve, trade_records)
    index_path = write_index(RUNS_DIR)
    print(f"Run guardada en: {run_dir}")
    print(f"Comparador: {index_path}")
    return summary


def _print_summary(summary: dict) -> None:
    print(f"Trades: {summary['total_trades']}")
    print(f"Win rate: {summary['win_rate']:.1%}")
    print(f"Total net P&L: ${summary['total_net_pnl']:+.2f}")
    print(f"Profit factor: {summary['profit_factor']:.2f}")
    print(f"Max drawdown: ${summary['max_drawdown']:.2f}")
    print(f"Max consecutive losses: {summary['max_consecutive_losses']}")


def main(argv=None, exchange=None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        summary = asyncio.run(run_backtest(args, exchange=exchange))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
