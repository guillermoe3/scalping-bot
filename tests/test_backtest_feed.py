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
    monkeypatch.setattr("trade_cache.CACHE_DIR", str(tmp_path / "cache"))


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
        [0, 104.0, 106.0, 103.0, 105.0, 1.0],
        [300_000, 105.0, 107.0, 104.0, 106.0, 2.0],
    ]


def test_resample_returns_empty_list_for_empty_input():
    assert resample([], minutes=15) == []


import asyncio

import clock
from backtest_feed import BacktestFeed
from state import MarketState


@pytest.fixture(autouse=True)
def _reset_clock():
    yield
    clock.reset()


async def _noop(*args):
    return None


def test_replay_fires_handlers_in_chronological_order():
    klines_1m = [
        [0,      100.0, 102.0, 99.0,  101.0, 2.0],
        [60_000, 101.0, 103.0, 100.0, 102.0, 3.0],
    ]
    trades = [
        {"timestamp": 10_000, "price": 100.5, "amount": 1.0, "side": "buy"},
        {"timestamp": 30_000, "price": 101.0, "amount": 1.0, "side": "sell"},
        {"timestamp": 70_000, "price": 101.5, "amount": 1.0, "side": "buy"},
        {"timestamp": 90_000, "price": 102.0, "amount": 1.0, "side": "buy"},
    ]
    exchange = _FakeExchange(klines=klines_1m, trades=trades)
    state = MarketState()
    feed = BacktestFeed(state, exchange=exchange, use_cache=False)

    fired = []

    async def on_trade(price, qty, is_sell, ts):
        fired.append(("trade", price))

    async def on_candle_1m(candle):
        fired.append(("candle_1m", candle.close))

    feed.on_trade(on_trade)
    feed.on_candle_1m(on_candle_1m)
    feed.on_candle_5m(_noop)
    feed.on_candle_15m(_noop)

    asyncio.run(feed.replay(start_ms=0, end_ms=120_000))

    assert fired == [
        ("trade", 100.5),
        ("trade", 101.0),
        ("candle_1m", 101.0),
        ("trade", 101.5),
        ("trade", 102.0),
        ("candle_1m", 102.0),
    ]


def test_replay_synthesizes_bid_ask_spread_from_price():
    klines_1m = [[0, 100.0, 100.0, 100.0, 100.0, 1.0]]
    trades = [{"timestamp": 10_000, "price": 100.0, "amount": 1.0, "side": "buy"}]
    exchange = _FakeExchange(klines=klines_1m, trades=trades)
    state = MarketState()
    feed = BacktestFeed(state, exchange=exchange, use_cache=False, spread_pct=0.001)

    seen = []

    async def on_trade(price, qty, is_sell, ts):
        seen.append((state.last_bid, state.last_ask, state.spread))

    feed.on_trade(on_trade)
    feed.on_candle_1m(_noop)
    feed.on_candle_5m(_noop)
    feed.on_candle_15m(_noop)

    asyncio.run(feed.replay(start_ms=0, end_ms=60_000))

    bid, ask, spread = seen[0]
    assert spread == pytest.approx(0.1)
    assert bid == pytest.approx(99.95)
    assert ask == pytest.approx(100.05)


def test_replay_updates_cvd_from_the_real_trade_side():
    klines_1m = [[0, 100.0, 100.0, 100.0, 100.0, 1.0]]
    trades = [
        {"timestamp": 10_000, "price": 100.0, "amount": 3.0, "side": "buy"},
        {"timestamp": 20_000, "price": 100.0, "amount": 1.0, "side": "sell"},
    ]
    exchange = _FakeExchange(klines=klines_1m, trades=trades)
    state = MarketState()
    feed = BacktestFeed(state, exchange=exchange, use_cache=False)
    feed.on_trade(_noop)
    feed.on_candle_1m(_noop)
    feed.on_candle_5m(_noop)
    feed.on_candle_15m(_noop)

    asyncio.run(feed.replay(start_ms=0, end_ms=60_000))

    assert state.cvd == pytest.approx(2.0)  # +3.0 (buy) - 1.0 (sell)


def test_replay_sets_the_simulated_clock_before_dispatching_each_event():
    klines_1m = [[0, 100.0, 100.0, 100.0, 100.0, 1.0]]
    trades = [{"timestamp": 10_000, "price": 100.0, "amount": 1.0, "side": "buy"}]
    exchange = _FakeExchange(klines=klines_1m, trades=trades)
    state = MarketState()
    feed = BacktestFeed(state, exchange=exchange, use_cache=False)

    seen = []

    async def on_trade(*args):
        seen.append(clock.now())

    feed.on_trade(on_trade)
    feed.on_candle_1m(_noop)
    feed.on_candle_5m(_noop)
    feed.on_candle_15m(_noop)

    asyncio.run(feed.replay(start_ms=0, end_ms=60_000))

    assert seen == [10.0]


def test_replay_resets_live_1m_after_each_candle_close():
    klines_1m = [
        [0,      100.0, 102.0, 99.0,  101.0, 2.0],
        [60_000, 101.0, 103.0, 100.0, 102.0, 3.0],
    ]
    trades = [
        {"timestamp": 10_000, "price": 100.5, "amount": 1.0, "side": "buy"},
        {"timestamp": 70_000, "price": 101.5, "amount": 1.0, "side": "buy"},
    ]
    exchange = _FakeExchange(klines=klines_1m, trades=trades)
    state = MarketState()
    feed = BacktestFeed(state, exchange=exchange, use_cache=False)

    closes_seen = []

    async def on_trade(*args):
        closes_seen.append(state.live_1m.close if state.live_1m else None)

    feed.on_trade(on_trade)
    feed.on_candle_1m(_noop)
    feed.on_candle_5m(_noop)
    feed.on_candle_15m(_noop)

    asyncio.run(feed.replay(start_ms=0, end_ms=120_000))

    assert closes_seen == [100.5, 101.5]
    assert state.live_1m is None
    assert len(state.candles_1m) == 2


def test_day_chunks_splits_a_multi_day_range_at_utc_midnight():
    day_ms = 24 * 60 * 60 * 1000

    result = backtest_feed._day_chunks(0, 2 * day_ms)

    assert result == [(0, day_ms), (day_ms, 2 * day_ms)]


def test_day_chunks_returns_a_single_chunk_when_range_is_within_one_day():
    result = backtest_feed._day_chunks(0, 60_000)

    assert result == [(0, 60_000)]


def test_day_chunks_aligns_boundaries_to_utc_midnight_even_with_an_off_grid_start():
    day_ms = 24 * 60 * 60 * 1000
    half_day = day_ms // 2

    result = backtest_feed._day_chunks(half_day, day_ms + half_day)

    assert result == [(half_day, day_ms), (day_ms, day_ms + half_day)]


def test_replay_caches_each_day_separately_for_multi_day_ranges():
    day_ms = backtest_feed.DAY_MS
    klines_1m = [
        [0, 100.0, 100.0, 100.0, 100.0, 1.0],
        [day_ms, 200.0, 200.0, 200.0, 200.0, 1.0],
    ]
    trades = [
        {"timestamp": 10_000, "price": 100.0, "amount": 1.0, "side": "buy"},
        {"timestamp": day_ms + 10_000, "price": 200.0, "amount": 1.0, "side": "sell"},
    ]
    exchange = _FakeExchange(klines=klines_1m, trades=trades)
    state = MarketState()
    feed = BacktestFeed(state, exchange=exchange, use_cache=True)

    asyncio.run(feed.replay(start_ms=0, end_ms=2 * day_ms))

    day0_trades_path = backtest_feed._cache_path("BTC/USDT", "trades", 0, day_ms)
    day1_trades_path = backtest_feed._cache_path("BTC/USDT", "trades", day_ms, 2 * day_ms)
    whole_range_path = backtest_feed._cache_path("BTC/USDT", "trades", 0, 2 * day_ms)

    assert os.path.exists(day0_trades_path)
    assert os.path.exists(day1_trades_path)
    assert not os.path.exists(whole_range_path)
    assert backtest_feed._read_cache(day0_trades_path) == [trades[0]]
    assert backtest_feed._read_cache(day1_trades_path) == [trades[1]]


def test_replay_preserves_chronological_order_and_candle_closes_across_a_day_boundary():
    day_ms = backtest_feed.DAY_MS
    klines_1m = [
        [day_ms - 60_000, 100.0, 102.0, 99.0, 101.0, 2.0],  # last 1m candle of day 0
        [day_ms, 101.0, 103.0, 100.0, 102.0, 3.0],  # first 1m candle of day 1
    ]
    trades = [
        {"timestamp": day_ms - 50_000, "price": 100.5, "amount": 1.0, "side": "buy"},
        {"timestamp": day_ms + 10_000, "price": 101.5, "amount": 1.0, "side": "buy"},
    ]
    exchange = _FakeExchange(klines=klines_1m, trades=trades)
    state = MarketState()
    feed = BacktestFeed(state, exchange=exchange, use_cache=False)

    fired = []

    async def on_trade(price, qty, is_sell, ts):
        fired.append(("trade", price))

    async def on_candle_1m(candle):
        fired.append(("candle_1m", candle.close))

    feed.on_trade(on_trade)
    feed.on_candle_1m(on_candle_1m)
    feed.on_candle_5m(_noop)
    feed.on_candle_15m(_noop)

    asyncio.run(feed.replay(start_ms=0, end_ms=2 * day_ms))

    assert fired == [
        ("trade", 100.5),
        ("candle_1m", 101.0),
        ("trade", 101.5),
        ("candle_1m", 102.0),
    ]
    assert len(state.candles_1m) == 2


def test_replay_raises_a_clear_error_when_no_klines_are_available():
    exchange = _FakeExchange(klines=[], trades=[])
    state = MarketState()
    feed = BacktestFeed(state, exchange=exchange, use_cache=False)
    feed.on_trade(_noop)
    feed.on_candle_1m(_noop)
    feed.on_candle_5m(_noop)
    feed.on_candle_15m(_noop)

    with pytest.raises(ValueError, match="No historical data available"):
        asyncio.run(feed.replay(start_ms=0, end_ms=60_000))


import trade_cache
from backtest_feed import find_missing_days

DAY_MS = backtest_feed.DAY_MS
DAY0 = 1775001600000  # 2026-04-01 00:00 UTC


def test_fetch_trades_prefers_compact_cache_over_exchange():
    trade_cache.write_day("2026-04-01", [[DAY0 + 1000, 50000.0, 0.5, True]])
    exchange = _FakeExchange(trades=[])
    result = fetch_trades(exchange, "BTC/USDT", DAY0, DAY0 + DAY_MS)
    assert exchange.fetch_trades_calls == 0
    assert result == [{"timestamp": DAY0 + 1000, "price": 50000.0, "amount": 0.5, "side": "sell"}]


def test_fetch_trades_compact_filters_to_requested_range():
    trade_cache.write_day("2026-04-01", [
        [DAY0 + 1000, 50000.0, 0.5, True],
        [DAY0 + 7_200_000, 50001.0, 0.1, False],
    ])
    result = fetch_trades(None, "BTC/USDT", DAY0, DAY0 + 3_600_000)
    assert len(result) == 1


def test_fetch_trades_falls_back_to_rest_with_warning(capsys):
    trades = [{"timestamp": DAY0 + 1, "price": 1.0, "amount": 1.0, "side": "buy"}]
    exchange = _FakeExchange(trades=trades)
    result = fetch_trades(exchange, "BTC/USDT", DAY0, DAY0 + 5000)
    assert exchange.fetch_trades_calls >= 1
    assert "download_history.py" in capsys.readouterr().err


def test_find_missing_days_reports_uncached_days():
    trade_cache.write_day("2026-04-02", [[DAY0 + DAY_MS + 1, 1.0, 1.0, False]])
    missing = find_missing_days(DAY0, DAY0 + 3 * DAY_MS)
    assert missing == ["2026-04-01", "2026-04-03"]


def test_replay_strict_raises_when_many_days_missing():
    feed = BacktestFeed.__new__(BacktestFeed)  # sin __init__: no crear exchange real
    feed._strict_cache = True
    with pytest.raises(ValueError) as exc:
        asyncio.run(feed.replay(DAY0, DAY0 + 4 * DAY_MS))
    assert "2026-04-01" in str(exc.value)
    assert "download_history.py" in str(exc.value)


def test_injected_exchange_disables_strict_cache():
    feed = BacktestFeed(MarketState(), exchange=_FakeExchange())
    assert feed._strict_cache is False
