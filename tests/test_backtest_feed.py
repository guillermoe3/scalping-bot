import os

import pytest

import backtest_feed
from backtest_feed import fetch_klines_1m, fetch_trades


class _FakeExchange:
    def __init__(self, klines=None, trades=None, page_size=1000):
        self._klines = klines or []
        self._trades = trades or []
        self._page_size = page_size
        self.fetch_ohlcv_calls = 0
        self.fetch_trades_calls = 0

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.fetch_ohlcv_calls += 1
        batch = [k for k in self._klines if k[0] >= since]
        return batch[: self._page_size]

    def fetch_trades(self, symbol, since=None, limit=None):
        self.fetch_trades_calls += 1
        batch = [t for t in self._trades if t["timestamp"] >= since]
        return batch[: self._page_size]


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(backtest_feed, "CACHE_DIR", str(tmp_path / "cache"))


def test_fetch_klines_1m_returns_klines_within_range():
    klines = [[i * 60_000, 100.0, 101.0, 99.0, 100.5, 1.0] for i in range(5)]
    exchange = _FakeExchange(klines=klines)

    result = fetch_klines_1m(exchange, "BTC/USDT", start_ms=0, end_ms=5 * 60_000)

    assert result == klines


def test_fetch_klines_1m_paginates_across_multiple_calls():
    klines = [[i * 60_000, 100.0, 101.0, 99.0, 100.5, 1.0] for i in range(5)]
    exchange = _FakeExchange(klines=klines, page_size=2)

    result = fetch_klines_1m(exchange, "BTC/USDT", start_ms=0, end_ms=5 * 60_000)

    assert result == klines
    assert exchange.fetch_ohlcv_calls == 3


def test_fetch_klines_1m_caches_to_disk_and_skips_second_fetch():
    klines = [[i * 60_000, 100.0, 101.0, 99.0, 100.5, 1.0] for i in range(5)]
    exchange = _FakeExchange(klines=klines)

    fetch_klines_1m(exchange, "BTC/USDT", start_ms=0, end_ms=5 * 60_000)
    fetch_klines_1m(exchange, "BTC/USDT", start_ms=0, end_ms=5 * 60_000)

    assert exchange.fetch_ohlcv_calls == 1


def test_fetch_klines_1m_no_cache_forces_refetch():
    klines = [[i * 60_000, 100.0, 101.0, 99.0, 100.5, 1.0] for i in range(5)]
    exchange = _FakeExchange(klines=klines)

    fetch_klines_1m(exchange, "BTC/USDT", start_ms=0, end_ms=5 * 60_000)
    fetch_klines_1m(exchange, "BTC/USDT", start_ms=0, end_ms=5 * 60_000, use_cache=False)

    assert exchange.fetch_ohlcv_calls == 2


def test_fetch_trades_returns_trades_within_range():
    trades = [{"timestamp": i * 1000, "price": 100.0 + i, "amount": 1.0, "side": "buy"} for i in range(5)]
    exchange = _FakeExchange(trades=trades)

    result = fetch_trades(exchange, "BTC/USDT", start_ms=0, end_ms=5000)

    assert result == trades


def test_fetch_trades_paginates_across_multiple_calls():
    trades = [{"timestamp": i * 1000, "price": 100.0 + i, "amount": 1.0, "side": "buy"} for i in range(5)]
    exchange = _FakeExchange(trades=trades, page_size=2)

    result = fetch_trades(exchange, "BTC/USDT", start_ms=0, end_ms=5000)

    assert result == trades
    assert exchange.fetch_trades_calls == 4


def test_fetch_trades_caches_to_disk_and_skips_second_fetch():
    trades = [{"timestamp": i * 1000, "price": 100.0 + i, "amount": 1.0, "side": "buy"} for i in range(5)]
    exchange = _FakeExchange(trades=trades)

    fetch_trades(exchange, "BTC/USDT", start_ms=0, end_ms=5000)
    fetch_trades(exchange, "BTC/USDT", start_ms=0, end_ms=5000)

    assert exchange.fetch_trades_calls == 2


def test_fetch_trades_returns_all_trades_when_page_size_exceeds_end_ms():
    """Regression test for the dimensionally-invalid `last_ts + limit >= end_ms` bug.

    With high trade density and a small end_ms, the spurious break condition would
    fire early, truncating results. This test uses a scenario where:
    - end_ms - start_ms is small (1500 ms)
    - page_size (limit) is large (1000)
    - trades are densely packed (1 per millisecond)
    - many trades are available beyond end_ms

    The buggy code would return only 1000 trades (1 page) instead of all 1500
    in-range trades, because last_ts + 1000 >= 1500 would fire after the first page.
    """
    # Create 2000 trades, 1 per millisecond from ts=0 to ts=1999
    trades = [
        {"timestamp": i, "price": 100.0 + i * 0.001, "amount": 1.0, "side": "buy"}
        for i in range(2000)
    ]
    exchange = _FakeExchange(trades=trades, page_size=1000)

    # Request trades in range [0, 1500), with limit=1000
    # Should return exactly 1500 trades (timestamps 0-1499)
    # Buggy code would return only 1000 (first page) because last_ts (999) + limit (1000) >= end_ms (1500)
    result = fetch_trades(exchange, "BTC/USDT", start_ms=0, end_ms=1500)

    assert len(result) == 1500, f"Expected 1500 trades, got {len(result)}"
    assert result[0]["timestamp"] == 0
    assert result[-1]["timestamp"] == 1499


def test_write_cache_does_not_leave_a_partial_file_on_interrupted_write(monkeypatch):
    path = backtest_feed._cache_path("BTC/USDT", "klines1m", 0, 1000)

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(backtest_feed.json, "dump", _boom)

    with pytest.raises(OSError):
        backtest_feed._write_cache(path, [1, 2, 3])

    assert not os.path.exists(path)


from backtest_feed import resample


def test_resample_aggregates_five_one_minute_candles_into_one_5m_candle():
    klines_1m = [
        [0,       100.0, 102.0, 99.0,  101.0, 1.0],
        [60_000,  101.0, 103.0, 100.0, 102.0, 2.0],
        [120_000, 102.0, 104.0, 101.0, 103.0, 1.5],
        [180_000, 103.0, 105.0, 102.0, 104.0, 0.5],
        [240_000, 104.0, 106.0, 103.0, 105.0, 1.0],
    ]

    result = resample(klines_1m, minutes=5)

    assert result == [[0, 100.0, 106.0, 99.0, 105.0, 6.0]]


def test_resample_splits_into_separate_buckets_when_crossing_a_boundary():
    klines_1m = [
        [240_000, 104.0, 106.0, 103.0, 105.0, 1.0],  # last candle of bucket [0, 300000)
        [300_000, 105.0, 107.0, 104.0, 106.0, 2.0],  # first candle of the next bucket
    ]

    result = resample(klines_1m, minutes=5)

    assert result == [
        [240_000, 104.0, 106.0, 103.0, 105.0, 1.0],
        [300_000, 105.0, 107.0, 104.0, 106.0, 2.0],
    ]


def test_resample_returns_empty_list_for_empty_input():
    assert resample([], minutes=15) == []
