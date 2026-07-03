import csv
import json
import os
from datetime import datetime, timezone

import pytest

from backtest_report import (
    compute_summary,
    downsample_equity,
    git_commit_info,
    make_run_dir_name,
    write_run,
    write_trade_log_csv,
)
from state import Side


def _full_close(net: float) -> dict:
    return {
        "side": Side.LONG, "entry_price": 100.0, "exit_price": 105.0, "size": 1.0,
        "reason": "time_exit", "leg_net": net, "total_trade_net": net,
        "fees_paid": 0.1, "entry_time": 0.0, "exit_time": 60.0, "is_partial": False,
    }


def _partial_leg() -> dict:
    return {
        "side": Side.LONG, "entry_price": 100.0, "exit_price": 110.0, "size": 0.5,
        "reason": "tp1", "leg_net": 5.0, "total_trade_net": None,
        "fees_paid": 0.05, "entry_time": 0.0, "exit_time": 30.0, "is_partial": True,
    }


def test_compute_summary_empty_list_returns_zeroed_summary():
    summary = compute_summary([])

    assert summary["total_trades"] == 0
    assert summary["win_rate"] == 0.0
    assert summary["total_net_pnl"] == 0.0
    assert summary["profit_factor"] == 0.0
    assert summary["max_drawdown"] == 0.0
    assert summary["max_consecutive_losses"] == 0


def test_compute_summary_ignores_partial_legs():
    records = [_partial_leg(), _full_close(10.0)]

    summary = compute_summary(records)

    assert summary["total_trades"] == 1


def test_compute_summary_win_rate_and_total_pnl():
    records = [_full_close(10.0), _full_close(-5.0), _full_close(20.0)]

    summary = compute_summary(records)

    assert summary["total_trades"] == 3
    assert summary["win_rate"] == pytest.approx(2 / 3)
    assert summary["total_net_pnl"] == pytest.approx(25.0)


def test_compute_summary_profit_factor():
    records = [_full_close(10.0), _full_close(-5.0)]

    summary = compute_summary(records)

    assert summary["profit_factor"] == pytest.approx(2.0)


def test_compute_summary_max_drawdown_tracks_peak_to_trough():
    records = [_full_close(10.0), _full_close(-15.0), _full_close(-5.0), _full_close(20.0)]
    # equity: 10, -5, -10, 10 ; peak: 10, 10, 10, 10 ; drawdown: 0, 15, 20, 0

    summary = compute_summary(records)

    assert summary["max_drawdown"] == pytest.approx(20.0)


def test_compute_summary_max_consecutive_losses():
    records = [_full_close(-1.0), _full_close(-1.0), _full_close(5.0), _full_close(-1.0)]

    summary = compute_summary(records)

    assert summary["max_consecutive_losses"] == 2


def test_write_trade_log_csv_writes_one_row_per_record(tmp_path):
    path = tmp_path / "trades.csv"
    records = [_full_close(10.0), _partial_leg()]

    write_trade_log_csv(records, str(path))

    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert rows[0]["side"] == "long"
    assert rows[0]["reason"] == "time_exit"
    assert rows[1]["is_partial"] == "True"


def test_write_trade_log_csv_writes_header_only_for_empty_list(tmp_path):
    path = tmp_path / "trades.csv"

    write_trade_log_csv([], str(path))

    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    assert rows == []


def test_downsample_equity_empty_and_single():
    assert downsample_equity([]) == []
    assert downsample_equity([5.0]) == [[1, 5.0]]


def test_downsample_equity_accumulates():
    assert downsample_equity([1.0, -2.0, 3.0]) == [[1, 1.0], [2, -1.0], [3, 2.0]]


def test_downsample_equity_caps_points_and_keeps_endpoints():
    nets = [1.0] * 2000
    points = downsample_equity(nets, max_points=500)
    assert len(points) <= 500
    assert points[0] == [1, 1.0]
    assert points[-1] == [2000, 2000.0]


def test_git_commit_info_shape():
    info = git_commit_info()
    assert set(info) == {"commit", "dirty"}
    assert isinstance(info["commit"], str) and isinstance(info["dirty"], bool)


def test_make_run_dir_name_sanitizes_label():
    dt = datetime(2026, 7, 3, 15, 30, 45, tzinfo=timezone.utc)
    assert make_run_dir_name(dt, None) == "2026-07-03_15-30-45"
    assert make_run_dir_name(dt, "Sin CVD/v2!") == "2026-07-03_15-30-45_sin-cvd-v2-"


def test_write_run_creates_the_three_files(tmp_path):
    meta = {"start": "2026-04-01", "label": None}
    summary = {"total_trades": 1, "win_rate": 1.0, "total_net_pnl": 5.0,
               "profit_factor": float("inf"), "max_drawdown": 0.0,
               "max_consecutive_losses": 0}
    run_dir = write_run(str(tmp_path), "2026-07-03_15-30-45", meta, summary, [[1, 5.0]], [])
    assert json.load(open(os.path.join(run_dir, "meta.json")))["start"] == "2026-04-01"
    data = json.load(open(os.path.join(run_dir, "summary.json")))
    assert data["equity_curve"] == [[1, 5.0]]
    assert data["final_equity"] == 5.0
    assert data["metrics"]["total_trades"] == 1
    assert os.path.exists(os.path.join(run_dir, "trades.csv"))
