import asyncio

from execution import ExecutionEngine
from main import wire_strategy
from state import MarketState


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


def test_wire_strategy_registers_one_handler_per_event_type():
    state = MarketState()
    feed = _FakeFeed()
    engine = ExecutionEngine(state)

    wire_strategy(state, feed, engine)

    assert len(feed.trade_handlers) == 1
    assert len(feed.candle_1m_handlers) == 1
    assert len(feed.candle_5m_handlers) == 1
    assert len(feed.candle_15m_handlers) == 1


def test_wire_strategy_on_trade_handler_runs_without_raising():
    state = MarketState()
    feed = _FakeFeed()
    engine = ExecutionEngine(state)
    wire_strategy(state, feed, engine)

    asyncio.run(feed.trade_handlers[0](100.0, 1.0, False, 0.0))  # must not raise


def test_wire_strategy_on_candle_1m_handler_updates_indicators():
    from state import Candle

    state = MarketState()
    for i in range(25):
        state.candles_1m.append(Candle(open=100.0 + i, high=101.0 + i, low=99.0 + i, close=100.0 + i, volume=1.0, timestamp=i * 60_000))
    feed = _FakeFeed()
    engine = ExecutionEngine(state)
    wire_strategy(state, feed, engine)

    closing_candle = Candle(open=125.0, high=126.0, low=124.0, close=125.0, volume=1.0, timestamp=25 * 60_000)
    asyncio.run(feed.candle_1m_handlers[0](closing_candle))

    assert state.atr > 0.0
