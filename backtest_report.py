from __future__ import annotations

import csv
from typing import List


def compute_summary(trade_records: List[dict]) -> dict:
    """trade_records: dicts shaped like ExecutionEngine.on_trade_closed's
    payload. Only is_partial=False rows count as a complete trade —
    their total_trade_net already aggregates the entry fee, every partial
    leg, and the final close."""
    closes = [r for r in trade_records if not r["is_partial"]]

    total_trades = len(closes)
    if total_trades == 0:
        return {
            "total_trades": 0, "win_rate": 0.0, "total_net_pnl": 0.0,
            "profit_factor": 0.0, "max_drawdown": 0.0, "max_consecutive_losses": 0,
        }

    nets = [r["total_trade_net"] for r in closes]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]

    win_rate = len(wins) / total_trades
    total_net_pnl = sum(nets)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for n in nets:
        equity += n
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    streak = 0
    max_streak = 0
    for n in nets:
        if n <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    return {
        "total_trades": total_trades, "win_rate": win_rate, "total_net_pnl": total_net_pnl,
        "profit_factor": profit_factor, "max_drawdown": max_drawdown,
        "max_consecutive_losses": max_streak,
    }


_CSV_FIELDS = [
    "side", "entry_price", "exit_price", "size", "reason", "leg_net",
    "total_trade_net", "fees_paid", "entry_time", "exit_time", "is_partial",
]


def write_trade_log_csv(trade_records: List[dict], path: str) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for r in trade_records:
            row = dict(r)
            row["side"] = row["side"].value
            writer.writerow(row)
