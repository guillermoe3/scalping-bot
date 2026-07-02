import asyncio

from execution import ExecutionEngine
from main import wire_strategy
from state import Candle, MarketState


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
