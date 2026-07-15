import csv
import json
import os

import pytest

import backtest
import clock


class _FakeExchange:
    def __init__(self, klines, trades):
        self._klines = klines
        self._trades = trades

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        return [k for k in self._klines if k[0] >= since][:limit]

    def fetch_trades(self, symbol, since=None, limit=None):
        return [t for t in self._trades if t["timestamp"] >= since][:limit]


@pytest.fixture(autouse=True)
def _reset_clock():
    yield
    clock.reset()


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("backtest_feed.CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr("trade_cache.CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture(autouse=True)
def _isolate_runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("backtest.RUNS_DIR", str(tmp_path / "runs"))


_BASE_MS = 1_704_067_200_000  # 2024-01-01T00:00:00Z
START = "2024-01-01"
END = "2024-01-02"


def _sample_day():
    klines_1m = [
        [_BASE_MS,          100.0, 102.0, 99.0,  101.0, 2.0],
        [_BASE_MS + 60_000, 101.0, 103.0, 100.0, 110.0, 3.0],
    ]
    trades = [
        {"timestamp": _BASE_MS + 10_000, "price": 100.5, "amount": 1.0, "side": "buy"},
        {"timestamp": _BASE_MS + 70_000, "price": 109.0, "amount": 1.0, "side": "buy"},
    ]
    return klines_1m, trades


def test_main_runs_end_to_end_and_writes_a_csv(tmp_path):
    klines_1m, trades = _sample_day()
    exchange = _FakeExchange(klines_1m, trades)
    out_path = tmp_path / "trades.csv"

    exit_code = backtest.main(
        ["--start", START, "--end", END, "--out", str(out_path)],
        exchange=exchange,
    )

    assert exit_code == 0
    assert out_path.exists()
    with open(out_path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows == []  # too little warm-up history for any entry signal to fire


def test_run_creates_run_dir_with_meta_summary_and_index(tmp_path):
    klines_1m, trades = _sample_day()
    exchange = _FakeExchange(klines_1m, trades)
    rc = backtest.main(
        ["--start", START, "--end", END, "--out", str(tmp_path / "t.csv"), "--label", "Mi Prueba"],
        exchange=exchange,
    )
    assert rc == 0
    import backtest as bt
    run_dirs = [d for d in os.listdir(bt.RUNS_DIR) if os.path.isdir(os.path.join(bt.RUNS_DIR, d))]
    assert len(run_dirs) == 1
    assert run_dirs[0].endswith("_mi-prueba")
    run = os.path.join(bt.RUNS_DIR, run_dirs[0])
    meta = json.load(open(os.path.join(run, "meta.json")))
    assert meta["label"] == "Mi Prueba"
    assert "git_commit" in meta and "start" in meta
    assert os.path.exists(os.path.join(run, "summary.json"))
    assert os.path.exists(os.path.join(run, "trades.csv"))
    assert os.path.exists(os.path.join(bt.RUNS_DIR, "index.html"))


def test_backtest_report_rebuild_index_cli(tmp_path, monkeypatch, capsys):
    import backtest_report
    rc = backtest_report.main_cli(["--rebuild-index", "--runs-dir", str(tmp_path)])
    assert rc == 0
    assert os.path.exists(os.path.join(str(tmp_path), "index.html"))


def test_main_rejects_start_after_end():
    exit_code = backtest.main(
        ["--start", "2024-01-02", "--end", "2024-01-01"],
        exchange=_FakeExchange([], []),
    )

    assert exit_code == 1


def test_main_rejects_a_future_end_date():
    exit_code = backtest.main(
        ["--start", "2024-01-01", "--end", "2099-01-01"],
        exchange=_FakeExchange([], []),
    )

    assert exit_code == 1


def test_run_backtest_never_touches_the_real_safety_state_file(tmp_path):
    import asyncio

    import safety

    klines_1m = [[_BASE_MS, 100.0, 100.0, 100.0, 100.0, 1.0]]
    trades = [{"timestamp": _BASE_MS + 1_000, "price": 100.0, "amount": 1.0, "side": "buy"}]
    exchange = _FakeExchange(klines_1m, trades)

    args = backtest.parse_args(["--start", "2024-01-01", "--end", "2024-01-02", "--out", str(tmp_path / "t.csv")])
    asyncio.run(backtest.run_backtest(args, exchange=exchange))

    assert safety.STATE_FILE_PATH != "safety_state.json"


def test_parse_args_accepts_ablation_flags():
    args = backtest.parse_args([
        "--start", "2026-04-01", "--end", "2026-04-02",
        "--disable-gate", "cvd", "--disable-gate", "trend_1h",
        "--enable-gate", "cvd",
        "--squeeze-compression", "0.6", "--squeeze-min-bars", "2",
    ])
    assert args.disable_gate == ["cvd", "trend_1h"]
    assert args.enable_gate == ["cvd"]
    assert args.squeeze_compression == 0.6
    assert args.squeeze_min_bars == 2


def test_parse_args_rejects_unknown_gate():
    with pytest.raises(SystemExit):
        backtest.parse_args([
            "--start", "2026-04-01", "--end", "2026-04-02",
            "--disable-gate", "no-existe",
        ])


def test_run_records_ablation_params_in_meta_and_gate_stats_in_summary(tmp_path):
    # _FakeExchange, _sample_day, START/END y el fixture autouse _isolate_runs_dir
    # (que redirige backtest.RUNS_DIR a tmp) ya existen en este archivo.
    import signals

    klines_1m, trades = _sample_day()
    exchange = _FakeExchange(klines_1m, trades)

    rc = backtest.main(
        ["--start", START, "--end", END, "--out", str(tmp_path / "t.csv"),
         "--label", "abl-test", "--disable-gate", "cvd",
         "--squeeze-compression", "0.6", "--squeeze-min-bars", "2"],
        exchange=exchange,
    )
    assert rc == 0

    run_dirs = [d for d in os.listdir(backtest.RUNS_DIR)
                if os.path.isdir(os.path.join(backtest.RUNS_DIR, d))]
    assert len(run_dirs) == 1
    run = os.path.join(backtest.RUNS_DIR, run_dirs[0])

    meta = json.load(open(os.path.join(run, "meta.json")))
    assert meta["disabled_gates"] == ["cvd"]
    assert meta["squeeze_compression"] == 0.6
    assert meta["squeeze_min_bars"] == 2

    metrics = json.load(open(os.path.join(run, "summary.json")))["metrics"]
    assert isinstance(metrics["gate_vetoes"], dict)
    assert set(metrics["gate_vetoes"]) == set(signals.GATE_NAMES)
    assert isinstance(metrics["signals_fired"], int)
