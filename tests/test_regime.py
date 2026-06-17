from collections import deque

from config import REGIME_CONFIRM_CANDLES
from regime import (
    _ema_is_sloping,
    _has_liquidity_sweeps_at_both_extremes,
    _infer_candidate,
    _is_breakout_candle,
    _is_tight_candle,
    update_mtf_trend,
    update_regime,
)
from state import Candle, MarketState, Regime, Side


def _candle(o: float, h: float, l: float, cl: float, index: int = 0) -> Candle:
    return Candle(open=o, high=h, low=l, close=cl, volume=0.0, timestamp=index * 60_000)


def _boring(index: int) -> Candle:
    return _candle(105.0, 106.0, 104.0, 105.0, index)


def _boring_state(atr: float = 10.0) -> MarketState:
    """20 identical low-range candles. Their own high/low ARE the 20-bar
    window's extremes, so _infer_candidate always reads this as
    tight + swept + not sloping -> Regime.TRADING_RANGE."""
    state = MarketState()
    state.atr = atr
    for i in range(20):
        state.candles_1m.append(_boring(i))
    return state


def _tight_unswept_candles():
    """One wide outlier candle sets the 20-bar window's high/low, but none
    of the most recent 5 candles touch them -> tight + NOT swept ->
    Regime.TIGHT_CHANNEL."""
    return [_candle(100.0, 130.0, 70.0, 100.0, 0)] + [_boring(i) for i in range(1, 20)]


def _tight_swept_candles():
    """15 boring candles, then two candles that tag the window's high and
    low within the last 5 -> tight + swept -> Regime.TRADING_RANGE
    (when not sloping)."""
    return [_boring(i) for i in range(15)] + [
        _candle(105.0, 110.0, 104.0, 109.0, 15),
        _candle(105.0, 106.0, 100.0, 101.0, 16),
    ] + [_boring(i) for i in range(17, 20)]


def test_is_breakout_candle_true_above_body_atr_threshold():
    candle = _candle(100.0, 116.0, 99.0, 116.0)  # body=16 >= 1.5*10
    assert _is_breakout_candle(candle, atr=10.0) is True


def test_is_breakout_candle_false_below_body_atr_threshold():
    candle = _candle(100.0, 108.0, 99.0, 101.0)  # body=1 < 1.5*10
    assert _is_breakout_candle(candle, atr=10.0) is False


def test_is_tight_candle_true_below_range_atr_threshold():
    candle = _candle(100.0, 104.0, 100.0, 102.0)  # range=4 <= 0.8*10
    assert _is_tight_candle(candle, atr=10.0) is True


def test_is_tight_candle_false_above_range_atr_threshold():
    candle = _candle(100.0, 110.0, 95.0, 102.0)  # range=15 > 0.8*10
    assert _is_tight_candle(candle, atr=10.0) is False


def test_has_liquidity_sweeps_true_when_both_extremes_touched_recently():
    candles = deque(_tight_swept_candles())
    assert _has_liquidity_sweeps_at_both_extremes(candles, lookback=20) is True


def test_has_liquidity_sweeps_false_when_recent_candles_miss_extremes():
    candles = deque(_tight_unswept_candles())
    assert _has_liquidity_sweeps_at_both_extremes(candles, lookback=20) is False


def test_has_liquidity_sweeps_false_below_minimum_lookback():
    candles = deque(_tight_swept_candles()[:10])
    assert _has_liquidity_sweeps_at_both_extremes(candles, lookback=20) is False


def test_ema_is_sloping_true_when_drift_exceeds_threshold():
    state = MarketState()
    state.atr = 10.0
    state.ema = 110.0  # close 10 bars ago is 105.0 -> drift 5.0 > 0.15*10=1.5
    for i in range(10):
        state.candles_1m.append(_boring(i))

    assert _ema_is_sloping(state, state.atr) is True


def test_ema_is_sloping_false_when_drift_within_threshold():
    state = MarketState()
    state.atr = 10.0
    state.ema = 105.5  # drift 0.5 <= 1.5
    for i in range(10):
        state.candles_1m.append(_boring(i))

    assert _ema_is_sloping(state, state.atr) is False


def test_ema_is_sloping_false_below_minimum_candle_count():
    state = MarketState()
    state.atr = 10.0
    state.ema = 110.0
    for i in range(9):
        state.candles_1m.append(_boring(i))

    assert _ema_is_sloping(state, state.atr) is False


def test_infer_candidate_unknown_below_minimum_candle_count():
    state = MarketState()
    state.atr = 10.0
    for i in range(3):
        state.candles_1m.append(_boring(i))

    assert _infer_candidate(state) == Regime.UNKNOWN


def test_infer_candidate_breakout_on_large_body_candle():
    state = MarketState()
    state.atr = 10.0
    for i in range(5):
        state.candles_1m.append(_boring(i))
    state.candles_1m.append(_candle(100.0, 120.0, 99.0, 120.0, 5))

    assert _infer_candidate(state) == Regime.BREAKOUT


def test_infer_candidate_tight_channel_when_tight_but_not_swept():
    state = MarketState()
    state.atr = 10.0
    for c in _tight_unswept_candles():
        state.candles_1m.append(c)

    assert _infer_candidate(state) == Regime.TIGHT_CHANNEL


def test_infer_candidate_trading_range_when_tight_swept_and_not_sloping():
    state = MarketState()
    state.atr = 10.0
    for c in _tight_swept_candles():
        state.candles_1m.append(c)
    state.ema = list(state.candles_1m)[-10].close  # keep EMA flat -> not sloping

    assert _infer_candidate(state) == Regime.TRADING_RANGE


def test_update_regime_single_confirmation_does_not_transition():
    state = _boring_state()  # candidate == TRADING_RANGE every call

    update_regime(state)

    assert state.regime == Regime.UNKNOWN
    assert state.pending_regime == Regime.TRADING_RANGE
    assert state.regime_confirm_count == 1


def test_update_regime_transitions_after_confirm_candles():
    state = _boring_state()

    for _ in range(REGIME_CONFIRM_CANDLES):
        update_regime(state)

    assert state.regime == Regime.TRADING_RANGE
    assert state.pending_regime is None
    assert state.regime_confirm_count == 0


def test_update_regime_interrupted_streak_resets_to_new_candidate():
    state = _boring_state()
    update_regime(state)
    update_regime(state)
    assert state.regime_confirm_count == 2
    assert state.pending_regime == Regime.TRADING_RANGE

    state.candles_1m.clear()
    for c in _tight_unswept_candles():
        state.candles_1m.append(c)
    update_regime(state)  # candidate is now TIGHT_CHANNEL, not TRADING_RANGE

    assert state.regime == Regime.UNKNOWN
    assert state.pending_regime == Regime.TIGHT_CHANNEL
    assert state.regime_confirm_count == 1


def test_update_regime_unknown_candidate_never_mutates_state():
    state = _boring_state()
    state.atr = 0.0  # forces _infer_candidate -> UNKNOWN
    state.regime = Regime.TRADING_RANGE
    state.pending_regime = Regime.BREAKOUT
    state.regime_confirm_count = 2

    update_regime(state)

    assert state.regime == Regime.TRADING_RANGE
    assert state.pending_regime == Regime.BREAKOUT
    assert state.regime_confirm_count == 2


def test_update_mtf_trend_15m_goes_long_above_dead_zone():
    state = MarketState()
    state.ema_15m = 100.0
    state.trend_15m = None
    state.last_price = 100.06

    update_mtf_trend(state)

    assert state.trend_15m == Side.LONG


def test_update_mtf_trend_15m_unchanged_inside_dead_zone():
    state = MarketState()
    state.ema_15m = 100.0
    state.trend_15m = Side.LONG
    state.last_price = 100.0

    update_mtf_trend(state)

    assert state.trend_15m == Side.LONG


def test_update_mtf_trend_15m_goes_short_below_dead_zone():
    state = MarketState()
    state.ema_15m = 100.0
    state.trend_15m = None
    state.last_price = 99.9

    update_mtf_trend(state)

    assert state.trend_15m == Side.SHORT


def test_update_mtf_trend_5m_goes_long_above_dead_zone():
    state = MarketState()
    state.ema_5m = 100.0
    state.trend_5m = None
    state.last_price = 100.04

    update_mtf_trend(state)

    assert state.trend_5m == Side.LONG


def test_update_mtf_trend_5m_unchanged_inside_dead_zone():
    state = MarketState()
    state.ema_5m = 100.0
    state.trend_5m = Side.SHORT
    state.last_price = 100.0

    update_mtf_trend(state)

    assert state.trend_5m == Side.SHORT


def test_update_mtf_trend_5m_goes_short_below_dead_zone():
    state = MarketState()
    state.ema_5m = 100.0
    state.trend_5m = None
    state.last_price = 99.96

    update_mtf_trend(state)

    assert state.trend_5m == Side.SHORT
