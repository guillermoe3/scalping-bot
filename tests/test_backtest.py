import csv

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


_BASE_MS = 1_704_067_200_000  # 2024-01-01T00:00:00Z


def test_main_runs_end_to_end_and_writes_a_csv(tmp_path):
    klines_1m = [
        [_BASE_MS,          100.0, 102.0, 99.0,  101.0, 2.0],
        [_BASE_MS + 60_000, 101.0, 103.0, 100.0, 110.0, 3.0],
    ]
    trades = [
        {"timestamp": _BASE_MS + 10_000, "price": 100.5, "amount": 1.0, "side": "buy"},
        {"timestamp": _BASE_MS + 70_000, "price": 109.0, "amount": 1.0, "side": "buy"},
    ]
    exchange = _FakeExchange(klines_1m, trades)
    out_path = tmp_path / "trades.csv"

    exit_code = backtest.main(
        ["--start", "2024-01-01", "--end", "2024-01-02", "--out", str(out_path)],
        exchange=exchange,
    )

    assert exit_code == 0
    assert out_path.exists()
    with open(out_path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows == []  # too little warm-up history for any entry signal to fire


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
