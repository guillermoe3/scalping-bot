import pytest

import clock
import safety
from config import ACCOUNT_RISK_PCT, INITIAL_SL_ATR, PAPER_BALANCE_USDT, TAKER_FEE_RATE, TP1_CLOSE_PCT
from risk import (
    apply_partial_close,
    check_tp1,
    close_position,
    open_position,
)
from state import MarketState, Side


def _state_with_long_position(entry: float = 100.0, atr: float = 2.0) -> MarketState:
    state = MarketState()
    state.atr = atr
    state.last_price = entry
    open_position(state, Side.LONG, entry)
    return state


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    path = tmp_path / "safety_state.json"
    monkeypatch.setattr(safety, "STATE_FILE_PATH", str(path))
    return path


def test_open_position_deducts_entry_fee_from_pnl_today():
    state = _state_with_long_position(entry=100.0)
    pos = state.position
    expected_fee = pos.size * 100.0 * TAKER_FEE_RATE

    assert pos.fees_paid == pytest.approx(expected_fee)
    assert pos.realized_pnl == pytest.approx(-expected_fee)
    assert state.pnl_today == pytest.approx(-expected_fee)


def test_open_position_persists_state(_isolate_state_file):
    state = _state_with_long_position(entry=100.0)
    pos = state.position

    assert _isolate_state_file.exists()

    loaded = MarketState()
    safety.load_into_state(loaded)

    assert loaded.position is not None
    assert loaded.position.side == Side.LONG
    assert loaded.position.size == pytest.approx(pos.size)
    assert loaded.position.entry_price == pytest.approx(pos.entry_price)


def test_check_tp1_returns_close_size_once_when_price_reaches_target():
    state = _state_with_long_position(entry=100.0)
    pos = state.position
    state.last_price = pos.tp1

    close_size = check_tp1(state)

    assert close_size == pytest.approx(round(pos.size * TP1_CLOSE_PCT, 6))
    assert pos.tp1_hit is True
    assert check_tp1(state) is None  # only fires once


def test_check_tp1_returns_none_when_price_has_not_reached_target():
    state = _state_with_long_position(entry=100.0)
    pos = state.position
    state.last_price = pos.entry_price  # nowhere near tp1

    assert check_tp1(state) is None
    assert pos.tp1_hit is False


def test_apply_partial_close_credits_net_pnl_and_shrinks_size():
    state = _state_with_long_position(entry=100.0)
    pos = state.position
    entry_fee = pos.fees_paid
    original_size = pos.size
    close_size = round(original_size * TP1_CLOSE_PCT, 6)

    net = apply_partial_close(state, close_size, fill_price=110.0)

    expected_gross = (110.0 - 100.0) * close_size
    expected_fee = close_size * 110.0 * TAKER_FEE_RATE
    expected_net = expected_gross - expected_fee

    assert net == pytest.approx(expected_net)
    assert pos.size == pytest.approx(original_size - close_size)
    assert pos.fees_paid == pytest.approx(entry_fee + expected_fee)
    assert pos.realized_pnl == pytest.approx(-entry_fee + expected_net)
    assert state.pnl_today == pytest.approx(-entry_fee + expected_net)


def test_apply_partial_close_persists_state(_isolate_state_file):
    state = _state_with_long_position(entry=100.0)
    pos = state.position
    close_size = round(pos.size * TP1_CLOSE_PCT, 6)

    apply_partial_close(state, close_size, fill_price=110.0)

    assert _isolate_state_file.exists()

    loaded = MarketState()
    safety.load_into_state(loaded)

    assert loaded.position is not None
    assert loaded.position.size == pytest.approx(pos.size)
    assert loaded.position.realized_pnl == pytest.approx(pos.realized_pnl)


def test_close_position_aggregates_realized_pnl_and_calls_kill_switch(monkeypatch):
    state = _state_with_long_position(entry=100.0)
    pos = state.position
    entry_fee = pos.fees_paid
    size = pos.size

    calls = []
    monkeypatch.setattr(
        safety, "after_trade_closed",
        lambda s, total_net: calls.append(total_net),
    )

    net = close_position(state, price=105.0, reason="time_exit")

    expected_gross = (105.0 - 100.0) * size
    expected_fee = size * 105.0 * TAKER_FEE_RATE
    expected_net = expected_gross - expected_fee
    expected_total_trade_net = -entry_fee + expected_net

    assert net == pytest.approx(expected_net)
    assert state.position is None
    assert len(calls) == 1
    assert calls[0] == pytest.approx(expected_total_trade_net)


def test_trade_with_tp1_then_breakeven_exit_uses_total_realized_pnl(monkeypatch):
    state = _state_with_long_position(entry=100.0)
    pos = state.position
    entry_fee = pos.fees_paid
    original_size = pos.size
    close_size = round(original_size * TP1_CLOSE_PCT, 6)

    partial_net = apply_partial_close(state, close_size, fill_price=110.0)

    calls = []
    monkeypatch.setattr(
        safety, "after_trade_closed",
        lambda s, total_net: calls.append(total_net),
    )

    final_net = close_position(state, price=100.0, reason="stop_loss")

    expected_total = (-entry_fee) + partial_net + final_net
    assert calls[0] == pytest.approx(expected_total)


def test_manage_position_returns_tuple_of_tp1_size_and_exit_reason():
    from risk import manage_position

    state = _state_with_long_position(entry=100.0)
    pos = state.position
    state.last_price = pos.stop_loss  # force an immediate stop-loss hit

    tp1_close_size, reason = manage_position(state)

    assert tp1_close_size is None
    assert reason == "stop_loss"


def test_open_position_uses_clock_for_entry_time(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: 1700000000.0)
    state = MarketState()
    state.atr = 2.0
    state.last_price = 100.0

    open_position(state, Side.LONG, 100.0)

    assert state.position.entry_time == 1700000000.0


def test_manage_position_time_exit_uses_clock_for_held_minutes(monkeypatch):
    from config import TIME_EXIT_MINUTES

    monkeypatch.setattr(clock, "now", lambda: 1700000000.0)
    state = _state_with_long_position(entry=100.0)
    state.position.entry_time = 1700000000.0 - TIME_EXIT_MINUTES * 60 - 1
    state.last_price = state.position.entry_price  # nowhere near SL/TP

    from risk import manage_position
    tp1_close_size, reason = manage_position(state)

    assert reason == "time_exit"


def test_open_position_sizes_against_daily_starting_balance():
    state = MarketState()
    state.atr = 2.0
    state.daily_starting_balance = 50_000.0

    open_position(state, Side.LONG, price=100.0)

    sl_dist = INITIAL_SL_ATR * state.atr
    expected_size = round((50_000.0 * ACCOUNT_RISK_PCT) / sl_dist, 6)
    assert state.position.size == pytest.approx(expected_size)


def test_open_position_falls_back_to_paper_balance_when_unset():
    state = MarketState()
    state.atr = 2.0
    assert state.daily_starting_balance is None

    open_position(state, Side.LONG, price=100.0)

    sl_dist = INITIAL_SL_ATR * state.atr
    expected_size = round((PAPER_BALANCE_USDT * ACCOUNT_RISK_PCT) / sl_dist, 6)
    assert state.position.size == pytest.approx(expected_size)
