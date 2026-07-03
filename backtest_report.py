from __future__ import annotations

import csv
import json
import math
import os
import re
import subprocess
from datetime import datetime
from typing import List, Optional


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
    losses = [n for n in nets if n <= 0]  # break-even (net == 0) counts as a loss

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


def downsample_equity(nets: List[float], max_points: int = 500) -> List[list]:
    points: List[list] = []
    equity = 0.0
    for i, n in enumerate(nets, start=1):
        equity += n
        points.append([i, equity])
    if len(points) <= max_points:
        return points
    step = (len(points) - 1) / (max_points - 1)
    sampled = [points[round(k * step)] for k in range(max_points - 1)]
    sampled.append(points[-1])
    return sampled


def git_commit_info() -> dict:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout.strip() != ""
        return {"commit": commit, "dirty": dirty}
    except Exception:
        return {"commit": "unknown", "dirty": False}


def make_run_dir_name(now_dt: datetime, label: Optional[str]) -> str:
    name = now_dt.strftime("%Y-%m-%d_%H-%M-%S")
    if label:
        name += "_" + re.sub(r"[^a-z0-9_-]", "-", label.lower())
    return name


def _jsonable(value):
    if isinstance(value, float) and math.isinf(value):
        return "inf"
    return value


def write_run(base_dir: str, dir_name: str, meta: dict, summary: dict,
              equity_curve: List[list], trade_records: List[dict]) -> str:
    run_dir = os.path.join(base_dir, dir_name)
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    payload = {
        "metrics": {k: _jsonable(v) for k, v in summary.items()},
        "equity_curve": equity_curve,
        "final_equity": equity_curve[-1][1] if equity_curve else 0.0,
    }
    with open(os.path.join(run_dir, "summary.json"), "w") as f:
        json.dump(payload, f, indent=2)
    write_trade_log_csv(trade_records, os.path.join(run_dir, "trades.csv"))
    return run_dir
