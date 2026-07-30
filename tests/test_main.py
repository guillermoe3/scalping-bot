import asyncio

import pytest

import clock
import daily_safety
import safety
from execution import ExecutionEngine
from main import wire_strategy
from state import Candle, MarketState, Side


@pytest.fixture(autouse=True)
def _isolate_state_files(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "STATE_FILE_PATH", str(tmp_path / "safety_state.json"))
    monkeypatch.setattr(daily_safety, "DAILY_STATE_FILE_PATH", str(tmp_path / "daily_safety_state.json"))


class _FakeFeed:
    def __init__(self):
        self.trade_handlers = []
        self.candle_1m_handlers = []
        self.candle_5m_handlers = []
        self.candle_15m_handlers = []

    def on_trade(self, fn):
        self.trade_handlers.append(fn)

    def on_candle_1m(self, fn):
        self.candle_1m_handlers.append(fn)

    def on_candle_5m(self, fn):
        self.candle_5m_handlers.append(fn)

    def on_candle_15m(self, fn):
        self.candle_15m_handlers.append(fn)


def _candle(i: int) -> Candle:
    return Candle(open=100.0 + i, high=101.0 + i, low=99.0 + i,
                  close=100.0 + i, volume=1.0, timestamp=i * 900_000)


def test_wire_strategy_registers_trade_1m_and_15m_handlers_only():
    state = MarketState()
    feed = _FakeFeed()
    engine = ExecutionEngine(state)

    wire_strategy(state, feed, engine)

    assert len(feed.trade_handlers) == 1
    assert len(feed.candle_1m_handlers) == 1   # debug logging only
    assert len(feed.candle_5m_handlers) == 0   # nothing left to do on 5m closes
    assert len(feed.candle_15m_handlers) == 1  # full signal pipeline


def test_wire_strategy_on_trade_handler_runs_without_raising():
    state = MarketState()
    feed = _FakeFeed()
    engine = ExecutionEngine(state)
    wire_strategy(state, feed, engine)

    asyncio.run(feed.trade_handlers[0](100.0, 1.0, False, 0.0))  # must not raise


def test_on_candle_15m_handler_updates_atr_from_15m_buffer():
    state = MarketState()
    for i in range(25):
        state.candles_15m.append(_candle(i))
    feed = _FakeFeed()
    engine = ExecutionEngine(state)
    wire_strategy(state, feed, engine)

    asyncio.run(feed.candle_15m_handlers[0](_candle(25)))

    assert state.atr > 0.0


def test_on_candle_1m_handler_does_not_run_the_signal_pipeline():
    state = MarketState()
    for i in range(25):
        state.candles_1m.append(_candle(i))
    feed = _FakeFeed()
    engine = ExecutionEngine(state)
    wire_strategy(state, feed, engine)

    asyncio.run(feed.candle_1m_handlers[0](_candle(25)))

    assert state.atr == 0.0  # ATR now comes only from the 15m pipeline


def test_on_trade_handler_checks_pending_entries():
    state = MarketState()
    state.last_bid = 99.0
    state.last_ask = 101.0
    state.last_price = 100.0
    state.atr = 2.0
    feed = _FakeFeed()
    engine = ExecutionEngine(state)
    wire_strategy(state, feed, engine)
    asyncio.run(engine.enter(Side.LONG))

    # the trade handler does not mutate last_price (the feed does); simulate the feed:
    state.last_price = 98.9
    asyncio.run(feed.trade_handlers[0](98.9, 1.0, False, 0.0))

    assert state.position is not None


from daily_execution import DailyExecutionEngine
from daily_state import DailyClose, DailyState, append_close, current_exposure_pct
from main import wire_daily_strategy


class _FakeDailyFeed:
    def __init__(self):
        self.candle_1d_handlers = []

    def on_candle_1d(self, fn):
        self.candle_1d_handlers.append(fn)


def _rising_history(n: int = 40, usdt_balance: float = 1000.0) -> DailyState:
    state = DailyState(usdt_balance=usdt_balance)
    for i in range(n):
        append_close(state, timestamp=i * 86_400_000, close=100.0 + i)
    return state


def test_wire_daily_strategy_registers_one_candle_handler():
    state = DailyState()
    feed = _FakeDailyFeed()
    engine = DailyExecutionEngine(state)

    wire_daily_strategy(state, feed, engine)

    assert len(feed.candle_1d_handlers) == 1


def test_on_candle_1d_updates_equity_peak_and_persists():
    state = _rising_history(40)
    feed = _FakeDailyFeed()
    engine = DailyExecutionEngine(state)
    wire_daily_strategy(state, feed, engine)

    asyncio.run(feed.candle_1d_handlers[0](DailyClose(timestamp=40 * 86_400_000, close=140.0)))

    assert state.equity_peak_usdt > 0.0
    assert state.last_rebalance_date == clock.today_utc()


def test_on_candle_1d_forces_flat_when_breaker_already_active():
    state = _rising_history(40, usdt_balance=50.0)
    state.btc_balance = 1.0  # ~74% exposure at price 140 — well above the 10pp band
    state.breaker_active = True
    feed = _FakeDailyFeed()
    engine = DailyExecutionEngine(state)
    wire_daily_strategy(state, feed, engine)

    asyncio.run(feed.candle_1d_handlers[0](DailyClose(timestamp=40 * 86_400_000, close=140.0)))

    assert state.btc_balance == pytest.approx(0.0, abs=1e-6)


def test_on_candle_1d_calls_on_breaker_tripped_hook():
    state = _rising_history(40, usdt_balance=400.0)
    state.equity_peak_usdt = 1000.0  # current equity (400) is a 60% drawdown from this peak
    captured = []
    feed = _FakeDailyFeed()
    engine = DailyExecutionEngine(state)
    wire_daily_strategy(state, feed, engine, on_breaker_tripped=captured.append)

    asyncio.run(feed.candle_1d_handlers[0](DailyClose(timestamp=40 * 86_400_000, close=140.0)))

    assert len(captured) == 1
    assert state.breaker_active is True


def test_on_candle_1d_calls_on_daily_close_hook_every_time():
    state = _rising_history(40)
    captured = []
    feed = _FakeDailyFeed()
    engine = DailyExecutionEngine(state)
    wire_daily_strategy(state, feed, engine, on_daily_close=captured.append)

    asyncio.run(feed.candle_1d_handlers[0](DailyClose(timestamp=40 * 86_400_000, close=140.0)))

    assert len(captured) == 1
    event = captured[0]
    assert event["close"] == pytest.approx(140.0)
    assert event["breaker_active"] is False
    assert event["current_exposure"] == pytest.approx(current_exposure_pct(state, 140.0))


def test_on_candle_1d_daily_close_hook_fires_even_when_breaker_active():
    state = _rising_history(40, usdt_balance=50.0)
    state.btc_balance = 1.0
    state.breaker_active = True
    captured = []
    feed = _FakeDailyFeed()
    engine = DailyExecutionEngine(state)
    wire_daily_strategy(state, feed, engine, on_daily_close=captured.append)

    asyncio.run(feed.candle_1d_handlers[0](DailyClose(timestamp=40 * 86_400_000, close=140.0)))

    assert len(captured) == 1
    assert captured[0]["breaker_active"] is True
    assert captured[0]["target_exposure"] == 0.0
