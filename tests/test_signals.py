import pytest

import signals
from signals import (
    BACKTEST_EVALUABLE_GATES,
    DEFAULT_DISABLED_GATES,
    GATE_NAMES,
    GATE_VETO_COUNTS,
    _nearest_key_level,
    _passes_gates,
    check_entry_signal,
    reset_signal_stats,
    update_squeeze,
)
from state import Candle, MarketState, Side


@pytest.fixture(autouse=True)
def _reset_gates():
    signals.DISABLED_GATES = set(DEFAULT_DISABLED_GATES)
    reset_signal_stats()
    yield
    signals.DISABLED_GATES = set(DEFAULT_DISABLED_GATES)
    reset_signal_stats()


def _candle(o=100.0, h=101.0, low=99.0, c=100.0, ts=0) -> Candle:
    return Candle(open=o, high=h, low=low, close=c, volume=1.0, timestamp=ts)


def _armed_state() -> MarketState:
    """A state that under the old code would have produced a LONG fade signal."""
    state = MarketState()
    state.atr = 2.0
    state.last_price = 100.4
    state.spread = 0.0001
    state.trend_1h = Side.LONG
    state.swing_lows.append(100.0)  # support right under price
    for i in range(5):
        state.candles_15m.append(_candle(c=100.4, h=100.6, low=100.2, ts=i * 900_000))
    for _ in range(4):
        update_squeeze(state)
    assert state.in_squeeze  # sanity: the detector still arms
    return state


# --- no entry trigger ---

def test_check_entry_signal_returns_none_even_with_fully_armed_setup():
    state = _armed_state()
    assert check_entry_signal(state) is None


def test_check_entry_signal_fires_no_stats():
    state = _armed_state()
    check_entry_signal(state)
    assert signals.SIGNAL_STATS["fired"] == 0
    assert all(v == 0 for v in GATE_VETO_COUNTS.values())


# --- squeeze reduced to a compression detector ---

def test_update_squeeze_arms_without_directional_state():
    state = _armed_state()
    assert not hasattr(state, "squeeze_direction")
    assert not hasattr(state, "squeeze_broken")
    assert not hasattr(state, "squeeze_reference_level")


def test_update_squeeze_resets_when_compression_ends():
    state = _armed_state()
    state.candles_15m.append(_candle(c=104.0, h=105.0, low=99.5, ts=99 * 900_000))
    update_squeeze(state)
    assert not state.in_squeeze
    assert state.squeeze_bar_count == 0


# --- gate harness ---

def test_gate_names_are_exactly_the_survivors():
    assert GATE_NAMES == ("spread", "trend_1h", "cvd")


def test_cvd_gate_is_disabled_by_default():
    assert "cvd" in DEFAULT_DISABLED_GATES
    assert signals.DISABLED_GATES == set(DEFAULT_DISABLED_GATES)


def test_backtest_live_invariant_every_gate_is_backtest_evaluable():
    # D4: reintroducing a gate the backtest engine cannot evaluate must break CI.
    assert set(GATE_NAMES) <= set(BACKTEST_EVALUABLE_GATES)


def test_passes_gates_spread_veto():
    state = MarketState()
    state.atr = 2.0
    state.spread = 1.0  # >> SPREAD_FILTER_ATR_PCT * atr = 0.02
    assert _passes_gates(state, Side.LONG) is False
    assert GATE_VETO_COUNTS["spread"] == 1


def test_passes_gates_trend_veto():
    state = MarketState()
    state.atr = 2.0
    state.trend_1h = Side.SHORT
    assert _passes_gates(state, Side.LONG) is False
    assert GATE_VETO_COUNTS["trend_1h"] == 1


def test_passes_gates_ok_when_aligned_and_tight_spread():
    state = MarketState()
    state.atr = 2.0
    state.spread = 0.0001
    state.trend_1h = Side.LONG
    assert _passes_gates(state, Side.LONG) is True


def test_passes_gates_cvd_ignored_while_disabled(monkeypatch):
    state = MarketState()
    state.atr = 2.0
    state.spread = 0.0001
    state.trend_1h = Side.LONG
    monkeypatch.setattr(signals, "detect_cvd_divergence", lambda s: "bearish_divergence")
    assert _passes_gates(state, Side.LONG) is True  # cvd is in DISABLED_GATES
    assert GATE_VETO_COUNTS["cvd"] == 0


def test_passes_gates_cvd_vetoes_when_enabled(monkeypatch):
    state = MarketState()
    state.atr = 2.0
    state.spread = 0.0001
    state.trend_1h = Side.LONG
    signals.DISABLED_GATES = set()
    monkeypatch.setattr(signals, "detect_cvd_divergence", lambda s: "bearish_divergence")
    assert _passes_gates(state, Side.LONG) is False
    assert GATE_VETO_COUNTS["cvd"] == 1


# --- _nearest_key_level (unchanged behaviour, kept because update_squeeze uses it) ---

def test_nearest_key_level_prefers_consistent_side_on_tie():
    state = MarketState()
    state.swing_lows.append(99.0)
    state.swing_highs.append(101.0)
    level, dist, kind = _nearest_key_level(100.0, state)
    assert (level, kind) == (99.0, "support")
    assert dist == pytest.approx(1.0)


def test_nearest_key_level_empty_state():
    state = MarketState()
    level, dist, kind = _nearest_key_level(100.0, state)
    assert level == 0.0 and dist == float("inf")
