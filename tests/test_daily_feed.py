import asyncio

import clock
from daily_feed import DailyDataFeed, backfill
from daily_state import DailyState, append_close, close_values


def test_dispatch_ignores_unclosed_candle():
    state = DailyState()
    feed = DailyDataFeed(state)
    msg = {"data": {"k": {"t": 1000, "c": "50000.0", "x": False}}}

    asyncio.run(feed._dispatch(msg))

    assert close_values(state) == []


def test_dispatch_appends_closed_candle_and_emits():
    state = DailyState()
    feed = DailyDataFeed(state)
    received = []

    async def handler(candle):
        received.append(candle)

    feed.on_candle_1d(handler)
    msg = {"data": {"k": {"t": 1000, "c": "50000.0", "x": True}}}

    asyncio.run(feed._dispatch(msg))

    assert close_values(state) == [50000.0]
    assert len(received) == 1
    assert received[0].close == 50000.0
    assert received[0].timestamp == 1000


def test_dispatch_error_in_handler_does_not_raise():
    state = DailyState()
    feed = DailyDataFeed(state)

    async def bad_handler(candle):
        raise RuntimeError("boom")

    feed.on_candle_1d(bad_handler)
    msg = {"data": {"k": {"t": 1000, "c": "50000.0", "x": True}}}

    asyncio.run(feed._dispatch(msg))  # must not raise


class _FakeExchange:
    def __init__(self, rows):
        self._rows = rows

    def fetch_ohlcv(self, symbol, timeframe="1d", limit=100):
        assert symbol == "BTC/USDT"
        assert timeframe == "1d"
        return self._rows


def test_backfill_drops_the_still_forming_candle(monkeypatch):
    fixed_now = 2_000_000_000.0  # arbitrary fixed "now", seconds
    monkeypatch.setattr(clock, "now", lambda: fixed_now)
    now_ms = fixed_now * 1000.0
    rows = [
        [now_ms - 3 * 86_400_000, 1, 2, 3, 40000.0, 1],  # closed
        [now_ms - 2 * 86_400_000, 1, 2, 3, 41000.0, 1],  # closed
        [now_ms - 1 * 86_400_000, 1, 2, 3, 42000.0, 1],  # closed (exactly at the boundary)
        [now_ms, 1, 2, 3, 43000.0, 1],                   # still forming — must be dropped
    ]
    state = DailyState()
    exchange = _FakeExchange(rows)

    backfill(state, exchange, limit=4)

    assert close_values(state) == [40000.0, 41000.0, 42000.0]


def test_backfill_appends_in_chronological_order(monkeypatch):
    fixed_now = 2_000_000_000.0
    monkeypatch.setattr(clock, "now", lambda: fixed_now)
    now_ms = fixed_now * 1000.0
    rows = [
        [now_ms - 2 * 86_400_000, 0, 0, 0, 10.0, 0],
        [now_ms - 1 * 86_400_000, 0, 0, 0, 20.0, 0],
    ]
    state = DailyState()

    backfill(state, _FakeExchange(rows))

    assert close_values(state) == [10.0, 20.0]


def test_backfill_clears_stale_closes_before_repopulating(monkeypatch):
    fixed_now = 2_000_000_000.0
    monkeypatch.setattr(clock, "now", lambda: fixed_now)
    now_ms = fixed_now * 1000.0
    rows = [
        [now_ms - 2 * 86_400_000, 0, 0, 0, 10.0, 0],
        [now_ms - 1 * 86_400_000, 0, 0, 0, 20.0, 0],
    ]
    state = DailyState()
    append_close(state, timestamp=1, close=999999.0)  # stale entry from a prior run

    backfill(state, _FakeExchange(rows))

    assert close_values(state) == [10.0, 20.0]  # stale entry is gone, not prepended
