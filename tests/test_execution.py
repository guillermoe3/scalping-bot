import asyncio

import pytest

import clock
import execution as execution_module
import safety
from config import ENTRY_ORDER_TIMEOUT_SECONDS, MAKER_FEE_RATE
from execution import ExecutionEngine
from state import MarketState, Side


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    path = tmp_path / "safety_state.json"
    monkeypatch.setattr(safety, "STATE_FILE_PATH", str(path))
    return path


def _state_with_book(bid: float = 99.0, ask: float = 101.0, last_price: float = 100.0) -> MarketState:
    state = MarketState()
    state.last_bid = bid
    state.last_ask = ask
    state.last_price = last_price
    state.atr = 2.0
    return state


def _fill_pending(engine: ExecutionEngine, state: MarketState, through_price: float) -> None:
    """Simulate a trade tick printing through the pending limit price."""
    state.last_price = through_price
    asyncio.run(engine.check_pending_entry())


def _open_long(engine: ExecutionEngine, state: MarketState) -> None:
    asyncio.run(engine.enter(Side.LONG))
    _fill_pending(engine, state, state.last_bid - 0.01)


# --- placement ---

def test_enter_long_places_pending_limit_at_bid_not_a_position():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)

    result = asyncio.run(engine.enter(Side.LONG))

    assert result is True
    assert state.position is None
    assert engine.has_pending_entry
    assert engine._pending_entry.plan.price == pytest.approx(99.0)


def test_enter_short_places_pending_limit_at_ask():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)

    asyncio.run(engine.enter(Side.SHORT))

    assert engine._pending_entry.plan.price == pytest.approx(101.0)


def test_enter_rejects_when_book_not_yet_received():
    state = MarketState()  # last_bid/last_ask default to 0.0
    state.last_price = 100.0
    engine = ExecutionEngine(state)

    result = asyncio.run(engine.enter(Side.LONG))

    assert result is False
    assert not engine.has_pending_entry


def test_enter_rejects_while_another_entry_is_pending():
    state = _state_with_book()
    engine = ExecutionEngine(state)
    asyncio.run(engine.enter(Side.LONG))

    result = asyncio.run(engine.enter(Side.LONG))

    assert result is False


# --- paper fills ---

def test_pending_long_fills_at_limit_when_price_trades_through():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    asyncio.run(engine.enter(Side.LONG))

    _fill_pending(engine, state, 98.9)

    pos = state.position
    assert pos is not None
    assert not engine.has_pending_entry
    assert pos.entry_price == pytest.approx(99.0)
    assert pos.fees_paid == pytest.approx(pos.size * 99.0 * MAKER_FEE_RATE)


def test_pending_long_does_not_fill_at_exactly_the_limit_price():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    asyncio.run(engine.enter(Side.LONG))

    _fill_pending(engine, state, 99.0)  # touched, not traded through

    assert state.position is None
    assert engine.has_pending_entry


def test_pending_short_fills_when_price_trades_above_limit():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    asyncio.run(engine.enter(Side.SHORT))

    _fill_pending(engine, state, 101.1)

    assert state.position is not None
    assert state.position.entry_price == pytest.approx(101.0)


def test_pending_entry_times_out_and_is_cancelled(monkeypatch):
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    t0 = clock.now()
    asyncio.run(engine.enter(Side.LONG))

    monkeypatch.setattr(clock, "now", lambda: t0 + ENTRY_ORDER_TIMEOUT_SECONDS + 1)
    _fill_pending(engine, state, 98.9)  # would fill, but the order expired first

    assert state.position is None
    assert not engine.has_pending_entry


def test_check_pending_entry_is_a_noop_with_nothing_pending():
    state = _state_with_book()
    engine = ExecutionEngine(state)
    asyncio.run(engine.check_pending_entry())  # must not raise
    assert state.position is None


# --- exits (unchanged mechanics, now driven through the fill helper) ---

def test_exit_long_fills_at_bid_in_paper_mode():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    _open_long(engine, state)

    net = asyncio.run(engine.exit("time_exit"))

    assert state.position is None
    assert isinstance(net, float)


def test_partial_exit_sends_reduce_only_order_in_live_mode(monkeypatch):
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    _open_long(engine, state)

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


# --- hooks ---

def test_on_trade_opened_fires_at_fill_not_at_placement():
    state = _state_with_book(bid=99.0, ask=101.0)
    captured = []
    engine = ExecutionEngine(state, on_trade_opened=captured.append)

    asyncio.run(engine.enter(Side.LONG))
    assert captured == []  # placed, not filled

    _fill_pending(engine, state, 98.9)

    assert len(captured) == 1
    record = captured[0]
    assert record["side"] == Side.LONG
    assert record["entry_price"] == pytest.approx(99.0)
    assert record["size"] == pytest.approx(state.position.size)
    assert record["stop_loss"] == pytest.approx(state.position.stop_loss)
    assert record["tp1"] == pytest.approx(state.position.tp1)


def test_exit_calls_on_trade_closed_hook_with_full_trade_details():
    state = _state_with_book(bid=99.0, ask=101.0)
    captured = []
    engine = ExecutionEngine(state, on_trade_closed=captured.append)
    _open_long(engine, state)
    entry_price = state.position.entry_price
    size = state.position.size
    state.last_bid = 99.0  # exit fill reference

    net = asyncio.run(engine.exit("time_exit"))

    assert len(captured) == 1
    record = captured[0]
    assert record["side"] == Side.LONG
    assert record["entry_price"] == pytest.approx(entry_price)
    assert record["exit_price"] == pytest.approx(99.0)
    assert record["size"] == pytest.approx(size)
    assert record["reason"] == "time_exit"
    assert record["leg_net"] == pytest.approx(net)
    assert record["total_trade_net"] is not None
    assert record["is_partial"] is False


def test_partial_exit_calls_on_trade_closed_hook_with_leg_size_not_remaining_size():
    state = _state_with_book(bid=99.0, ask=101.0)
    captured = []
    engine = ExecutionEngine(state, on_trade_closed=captured.append)
    _open_long(engine, state)
    close_size = round(state.position.size * 0.5, 6)

    asyncio.run(engine.partial_exit(close_size, "tp1"))

    assert len(captured) == 1
    record = captured[0]
    assert record["size"] == pytest.approx(close_size)
    assert record["is_partial"] is True
    assert record["total_trade_net"] is None


def test_hooks_default_to_none_and_do_not_raise():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)  # no hooks passed
    _open_long(engine, state)
    asyncio.run(engine.exit("time_exit"))  # must not raise


# --- live GTX entry path ---

class _FakeLiveExchange:
    def __init__(self):
        self.limit_orders = []
        self.cancelled = []
        self.cancel_all_calls = []
        self.order_status = {"status": "open", "filled": 0.0}

    def create_limit_order(self, symbol, side, amount, price, params=None):
        self.limit_orders.append((symbol, side, amount, price, params))
        return {"id": "oid-1"}

    def fetch_order(self, order_id, symbol):
        return dict(self.order_status, id=order_id)

    def cancel_order(self, order_id, symbol):
        self.cancelled.append(order_id)

    def cancel_all_orders(self, symbol):
        self.cancel_all_calls.append(symbol)


def _live_engine(state, monkeypatch):
    engine = ExecutionEngine(state)
    fake = _FakeLiveExchange()
    engine._exchange = fake
    monkeypatch.setattr(execution_module, "PAPER_MODE", False)
    return engine, fake


def test_live_enter_sends_post_only_gtx_limit(monkeypatch):
    state = _state_with_book(bid=99.0, ask=101.0)
    engine, fake = _live_engine(state, monkeypatch)

    result = asyncio.run(engine.enter(Side.LONG))

    assert result is True
    assert state.position is None
    symbol, side, amount, price, params = fake.limit_orders[0]
    assert (symbol, side) == ("BTC/USDT", "buy")
    assert price == pytest.approx(99.0)
    assert params == {"timeInForce": "GTX"}
    assert engine._pending_entry.order_id == "oid-1"


def test_live_post_only_rejection_means_no_trade(monkeypatch):
    state = _state_with_book(bid=99.0, ask=101.0)
    engine, fake = _live_engine(state, monkeypatch)

    def _reject(*a, **k):
        raise RuntimeError("Order would immediately match and take")

    fake.create_limit_order = _reject
    result = asyncio.run(engine.enter(Side.LONG))

    assert result is False
    assert not engine.has_pending_entry


def test_live_fill_detected_by_polling_opens_position_with_maker_fee(monkeypatch):
    state = _state_with_book(bid=99.0, ask=101.0)
    engine, fake = _live_engine(state, monkeypatch)
    asyncio.run(engine.enter(Side.LONG))
    fake.order_status = {"status": "closed", "filled": 0.5}
    engine._last_fill_poll = 0.0  # force the next poll

    asyncio.run(engine.check_pending_entry())

    pos = state.position
    assert pos is not None
    assert pos.entry_price == pytest.approx(99.0)
    assert pos.fees_paid == pytest.approx(pos.size * 99.0 * MAKER_FEE_RATE)


def test_live_timeout_cancels_and_keeps_partial_fill(monkeypatch):
    state = _state_with_book(bid=99.0, ask=101.0)
    engine, fake = _live_engine(state, monkeypatch)
    t0 = clock.now()
    asyncio.run(engine.enter(Side.LONG))
    planned_size = engine._pending_entry.plan.size
    fake.order_status = {"status": "open", "filled": round(planned_size / 2, 6)}

    monkeypatch.setattr(clock, "now", lambda: t0 + ENTRY_ORDER_TIMEOUT_SECONDS + 1)
    asyncio.run(engine.check_pending_entry())

    assert fake.cancelled == ["oid-1"]
    assert state.position is not None
    assert state.position.size == pytest.approx(planned_size / 2, rel=1e-4)


def test_live_fill_uses_exchange_filled_size_and_average_price(monkeypatch):
    """Exchange-reported filled/average must override the plan's size/price."""
    state = _state_with_book(bid=99.0, ask=101.0)
    engine, fake = _live_engine(state, monkeypatch)
    asyncio.run(engine.enter(Side.LONG))
    planned_size = engine._pending_entry.plan.size
    # Exchange reports a partial fill at a slightly different average price
    filled = round(planned_size * 0.7, 6)
    avg_price = 98.5  # differs from plan price of 99.0
    fake.order_status = {"status": "closed", "filled": filled, "average": avg_price}
    engine._last_fill_poll = 0.0  # force the next poll

    asyncio.run(engine.check_pending_entry())

    pos = state.position
    assert pos is not None
    assert pos.size == pytest.approx(filled)
    assert pos.entry_price == pytest.approx(avg_price)
    assert pos.fees_paid == pytest.approx(filled * avg_price * MAKER_FEE_RATE)


def test_live_zero_fill_closed_order_does_not_open_position(monkeypatch):
    """An exchange-reported {'status': 'closed', 'filled': 0.0} (e.g. STP kill)
    must not open a synthetic full position — pending entry should be cleared."""
    state = _state_with_book(bid=99.0, ask=101.0)
    engine, fake = _live_engine(state, monkeypatch)
    asyncio.run(engine.enter(Side.LONG))
    fake.order_status = {"status": "closed", "filled": 0.0, "average": 98.5}
    engine._last_fill_poll = 0.0  # force the next poll

    asyncio.run(engine.check_pending_entry())

    assert state.position is None
    assert not engine.has_pending_entry


def test_cancel_open_orders_calls_cancel_all(monkeypatch):
    state = _state_with_book()
    engine, fake = _live_engine(state, monkeypatch)

    asyncio.run(engine.cancel_open_orders())

    assert fake.cancel_all_calls == ["BTC/USDT"]
