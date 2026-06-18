from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from datetime import datetime, timezone

import safety
from backtest_feed import BacktestFeed
from backtest_report import compute_summary, write_trade_log_csv
from config import BACKTEST_SYNTHETIC_SPREAD_PCT
from execution import ExecutionEngine
from main import wire_strategy
from risk import PAPER_BALANCE_USDT
from state import MarketState


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
    return parser.parse_args(argv)


def validate_range(start_ms: int, end_ms: int) -> None:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if start_ms >= end_ms:
        raise ValueError("--start must be before --end")
    if end_ms > now_ms:
        raise ValueError("--end cannot be in the future")


async def run_backtest(args: argparse.Namespace, exchange=None) -> dict:
    start_ms = _parse_date_utc(args.start)
    end_ms = _parse_date_utc(args.end)
    validate_range(start_ms, end_ms)

    _, state_file_path = tempfile.mkstemp(prefix="backtest_safety_state_", suffix=".json")
    safety.STATE_FILE_PATH = state_file_path

    state = MarketState()
    trade_records: list = []
    engine = ExecutionEngine(state, on_trade_closed=trade_records.append)
    feed = BacktestFeed(state, exchange=exchange, spread_pct=args.spread_pct, use_cache=not args.no_cache)
    wire_strategy(state, feed, engine)

    await feed.replay(start_ms, end_ms)

    summary = compute_summary(trade_records)
    write_trade_log_csv(trade_records, args.out)
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
