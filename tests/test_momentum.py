import time

import pytest

import clock
from config import MOMENTUM_ABORT_MINUTES
from momentum import should_abort_for_momentum, update_volume_velocity
from state import Candle, MarketState, Position, Side


def _position(entry_time: float) -> Position:
    return Position(
        side=Side.LONG, entry_price=100.0, size=1.0, entry_time=entry_time,
        stop_loss=95.0, tp1=110.0, initial_atr=2.0, initial_sl_distance=5.0,
    )


def test_update_volume_velocity_noop_when_no_live_candle():
    state = MarketState()
    state.volume_velocity = 99.0

    update_volume_velocity(state)

    assert state.volume_velocity == 99.0


def test_update_volume_velocity_matches_volume_over_elapsed_seconds():
    state = MarketState()
    state.live_1m = Candle(
        open=1.0, high=1.0, low=1.0, close=1.0, volume=10.0,
        timestamp=(time.time() - 5.0) * 1000.0,
    )

    update_volume_velocity(state)

    assert state.volume_velocity == pytest.approx(2.0, abs=0.01)


def test_should_abort_for_momentum_false_without_position():
    state = MarketState()

    assert should_abort_for_momentum(state) is False


def test_should_abort_for_momentum_false_before_abort_window():
    state = MarketState()
    state.position = _position(entry_time=time.time())

    assert should_abort_for_momentum(state) is False


def test_should_abort_for_momentum_false_when_no_prior_velocity():
    state = MarketState()
    state.position = _position(entry_time=time.time() - MOMENTUM_ABORT_MINUTES * 60 - 10)
    state.prior_volume_velocity = 0.0

    assert should_abort_for_momentum(state) is False


def test_should_abort_for_momentum_true_when_velocity_collapses():
    state = MarketState()
    state.position = _position(entry_time=time.time() - MOMENTUM_ABORT_MINUTES * 60 - 10)
    state.prior_volume_velocity = 10.0
    state.volume_velocity = 2.0  # ratio 0.2 < 0.30 collapse threshold

    assert should_abort_for_momentum(state) is True


def test_should_abort_for_momentum_false_when_velocity_holds():
    state = MarketState()
    state.position = _position(entry_time=time.time() - MOMENTUM_ABORT_MINUTES * 60 - 10)
    state.prior_volume_velocity = 10.0
    state.volume_velocity = 5.0  # ratio 0.5 >= 0.30 collapse threshold

    assert should_abort_for_momentum(state) is False


def test_update_volume_velocity_uses_clock_not_real_time(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: 1000.0)
    state = MarketState()
    state.live_1m = Candle(open=1.0, high=1.0, low=1.0, close=1.0, volume=10.0, timestamp=995_000.0)

    update_volume_velocity(state)

    assert state.volume_velocity == pytest.approx(2.0)


def test_should_abort_for_momentum_uses_clock_for_held_seconds(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: 1000.0)
    state = MarketState()
    state.position = _position(entry_time=1000.0 - MOMENTUM_ABORT_MINUTES * 60 - 10)
    state.prior_volume_velocity = 10.0
    state.volume_velocity = 2.0  # ratio 0.2 < 0.30 collapse threshold

    assert should_abort_for_momentum(state) is True
