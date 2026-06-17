import asyncio

import pytest

import execution as execution_module
from execution import ExecutionEngine
from state import MarketState, Side


def _state_with_book(bid: float = 99.0, ask: float = 101.0, last_price: float = 100.0) -> MarketState:
    state = MarketState()
    state.last_bid = bid
    state.last_ask = ask
    state.last_price = last_price
    state.atr = 2.0
    return state


def test_enter_long_fills_at_ask_in_paper_mode():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)

    result = asyncio.run(engine.enter(Side.LONG))

    assert result is True
    assert state.position is not None
    assert state.position.entry_price == pytest.approx(101.0)


def test_enter_short_fills_at_bid_in_paper_mode():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)

    result = asyncio.run(engine.enter(Side.SHORT))

    assert result is True
    assert state.position.entry_price == pytest.approx(99.0)


def test_enter_rejects_when_book_not_yet_received():
    state = MarketState()  # last_bid/last_ask default to 0.0
    state.last_price = 100.0
    engine = ExecutionEngine(state)

    result = asyncio.run(engine.enter(Side.LONG))

    assert result is False
    assert state.position is None


def test_exit_long_fills_at_bid_in_paper_mode():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    asyncio.run(engine.enter(Side.LONG))

    net = asyncio.run(engine.exit("time_exit"))

    assert state.position is None
    assert isinstance(net, float)


def test_partial_exit_sends_reduce_only_order_in_live_mode(monkeypatch):
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    asyncio.run(engine.enter(Side.LONG))

    sent_orders = []

    class _FakeExchange:
        def create_market_order(self, symbol, side, amount, params=None):
            sent_orders.append((symbol, side, amount, params))

    engine._exchange = _FakeExchange()
    monkeypatch.setattr(execution_module, "PAPER_MODE", False)

    close_size = round(state.position.size * 0.5, 6)
    asyncio.run(engine.partial_exit(close_size, "tp1"))

    assert len(sent_orders) == 1
    symbol, side, amount, params = sent_orders[0]
    assert symbol == "BTC/USDT"
    assert side == "sell"
    assert amount == pytest.approx(close_size)
    assert params == {"reduceOnly": True}


def test_exchange_property_exposes_underlying_client():
    state = MarketState()
    engine = ExecutionEngine(state)
    engine._exchange = "fake-client"

    assert engine.exchange == "fake-client"
