import json

import pytest

import safety
from state import MarketState, Position, Side


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    path = tmp_path / "safety_state.json"
    monkeypatch.setattr(safety, "STATE_FILE_PATH", str(path))
    return path


def test_maybe_reset_daily_resets_counters_on_date_rollover():
    state = MarketState()
    state.last_reset_date = "2020-01-01"
    state.pnl_today = -50.0
    state.trades_today = 4
    state.consecutive_losses = 2
    state.kill_switch_active = True

    safety.maybe_reset_daily(state)

    assert state.pnl_today == 0.0
    assert state.trades_today == 0
    assert state.consecutive_losses == 0
    assert state.kill_switch_active is False
    assert state.last_reset_date == safety._today_utc()


def test_maybe_reset_daily_is_a_noop_when_already_reset_today():
    state = MarketState()
    state.last_reset_date = safety._today_utc()
    state.pnl_today = -50.0

    safety.maybe_reset_daily(state)

    assert state.pnl_today == -50.0


def test_can_open_new_position_false_when_kill_switch_active():
    state = MarketState()
    state.last_reset_date = safety._today_utc()
    state.kill_switch_active = True

    assert safety.can_open_new_position(state) is False


def test_can_open_new_position_true_by_default():
    state = MarketState()

    assert safety.can_open_new_position(state) is True


def test_after_trade_closed_triggers_kill_switch_on_daily_loss_pct():
    state = MarketState()
    state.last_reset_date = safety._today_utc()
    state.pnl_today = -250.0  # -2.5% of a 10,000 balance

    safety.after_trade_closed(state, total_trade_net=-250.0, balance=10_000.0)

    assert state.kill_switch_active is True


def test_after_trade_closed_triggers_kill_switch_on_consecutive_losses():
    state = MarketState()
    state.last_reset_date = safety._today_utc()

    safety.after_trade_closed(state, total_trade_net=-10.0, balance=10_000.0)
    safety.after_trade_closed(state, total_trade_net=-10.0, balance=10_000.0)
    safety.after_trade_closed(state, total_trade_net=-10.0, balance=10_000.0)

    assert state.consecutive_losses == 3
    assert state.kill_switch_active is True


def test_after_trade_closed_resets_streak_on_winning_trade():
    state = MarketState()
    state.last_reset_date = safety._today_utc()

    safety.after_trade_closed(state, total_trade_net=-10.0, balance=10_000.0)
    safety.after_trade_closed(state, total_trade_net=-10.0, balance=10_000.0)
    safety.after_trade_closed(state, total_trade_net=25.0, balance=10_000.0)

    assert state.consecutive_losses == 0
    assert state.kill_switch_active is False


def test_save_then_load_round_trips_flat_state(_isolate_state_file):
    state = MarketState()
    state.last_reset_date = "2026-06-17"
    state.pnl_today = -42.5
    state.trades_today = 3
    state.consecutive_losses = 1
    state.kill_switch_active = False

    safety.save_state(state)

    loaded = MarketState()
    safety.load_into_state(loaded)

    assert loaded.last_reset_date == "2026-06-17"
    assert loaded.pnl_today == pytest.approx(-42.5)
    assert loaded.trades_today == 3
    assert loaded.consecutive_losses == 1
    assert loaded.position is None


def test_save_then_load_round_trips_open_position(_isolate_state_file):
    state = MarketState()
    state.position = Position(
        side=Side.SHORT,
        entry_price=200.0,
        size=0.5,
        entry_time=123.0,
        stop_loss=210.0,
        tp1=180.0,
        initial_atr=3.0,
        initial_sl_distance=10.0,
        fees_paid=0.05,
        realized_pnl=-0.05,
    )

    safety.save_state(state)

    loaded = MarketState()
    safety.load_into_state(loaded)

    assert loaded.position is not None
    assert loaded.position.side == Side.SHORT
    assert loaded.position.size == pytest.approx(0.5)
    assert loaded.position.realized_pnl == pytest.approx(-0.05)


def test_load_into_state_starts_fresh_when_file_missing(_isolate_state_file):
    state = MarketState()

    safety.load_into_state(state)  # file was never written

    assert state.position is None
    assert state.pnl_today == 0.0


def test_load_into_state_starts_fresh_on_corrupt_json(_isolate_state_file):
    with open(safety.STATE_FILE_PATH, "w") as f:
        f.write("{not valid json")

    state = MarketState()
    safety.load_into_state(state)

    assert state.position is None
    assert state.pnl_today == 0.0


def test_save_state_does_not_raise_when_write_fails(monkeypatch, tmp_path):
    bad_path = tmp_path / "missing_dir" / "safety_state.json"  # parent dir doesn't exist
    monkeypatch.setattr(safety, "STATE_FILE_PATH", str(bad_path))
    state = MarketState()

    safety.save_state(state)  # must not raise
