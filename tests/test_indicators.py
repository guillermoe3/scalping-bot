from collections import deque

import pytest

from config import EMA_PERIOD_BREAKOUT, EMA_PERIOD_CHANNEL, EMA_PERIOD_RANGE
from indicators import compute_atr, compute_ema, detect_swing_points, ema_period_for_regime, update_indicators
from state import Candle, MarketState, Regime


def _candle(high: float, low: float, close: float = None, index: int = 0) -> Candle:
    close = high if close is None else close
    return Candle(open=low, high=high, low=low, close=close, volume=0.0, timestamp=index * 60_000)


def _candles_with_closes(closes):
    out = []
    for i, close in enumerate(closes):
        out.append(Candle(open=close, high=close + 1, low=close - 1, close=close, volume=0.0, timestamp=i * 60_000))
    return out


def test_compute_atr_returns_zero_with_fewer_than_two_candles():
    assert compute_atr(deque([_candle(10.0, 8.0)])) == 0.0
    assert compute_atr(deque([])) == 0.0


def test_compute_atr_matches_hand_calculated_wilder_value():
    candles = deque([
        Candle(open=9.0, high=10.0, low=8.0, close=9.0, volume=0.0, timestamp=0),
        Candle(open=10.0, high=11.0, low=9.0, close=10.0, volume=0.0, timestamp=1),
        Candle(open=12.0, high=13.0, low=10.0, close=12.0, volume=0.0, timestamp=2),
        Candle(open=11.5, high=12.0, low=11.0, close=11.5, volume=0.0, timestamp=3),
        Candle(open=13.0, high=14.0, low=11.0, close=13.0, volume=0.0, timestamp=4),
    ])

    assert compute_atr(candles, period=3) == pytest.approx(7 / 3)


def test_compute_ema_returns_zero_for_empty_list():
    assert compute_ema([], period=3) == 0.0


def test_compute_ema_matches_hand_calculated_value():
    assert compute_ema([1.0, 2.0, 3.0, 4.0, 5.0], period=3) == pytest.approx(4.0)


def test_ema_period_for_regime_maps_each_regime_to_its_configured_period():
    assert ema_period_for_regime(Regime.BREAKOUT) == EMA_PERIOD_BREAKOUT
    assert ema_period_for_regime(Regime.TIGHT_CHANNEL) == EMA_PERIOD_CHANNEL
    assert ema_period_for_regime(Regime.TRADING_RANGE) == EMA_PERIOD_RANGE
    assert ema_period_for_regime(Regime.UNKNOWN) == EMA_PERIOD_RANGE


def test_detect_swing_points_returns_empty_below_minimum_candle_count():
    candles = deque([_candle(10.0, 5.0) for _ in range(4)])

    assert detect_swing_points(candles, lookback=2) == ([], [])


def test_detect_swing_points_finds_known_peak_and_valley():
    highs_lows = [(10.0, 5.0), (12.0, 6.0), (20.0, 7.0), (15.0, 3.0), (8.0, 2.0), (9.0, 4.0), (11.0, 6.0)]
    candles = deque(_candle(h, l, index=i) for i, (h, l) in enumerate(highs_lows))

    swing_highs, swing_lows = detect_swing_points(candles, lookback=2)

    assert swing_highs == [20.0]
    assert swing_lows == [2.0]


def test_update_indicators_sets_atr_and_all_ema_fields():
    state = MarketState()
    state.regime = Regime.TIGHT_CHANNEL
    for c in _candles_with_closes([100.0 + i for i in range(25)]):
        state.candles_15m.append(c)
    for c in _candles_with_closes([100.0 + i for i in range(3)]):
        state.candles_5m.append(c)

    update_indicators(state)

    assert state.atr > 0.0
    assert state.ema > 0.0
    assert state.ema_5m > 0.0
    assert state.ema_15m > 0.0


def test_update_indicators_uses_regime_adaptive_period_for_signal_ema():
    closes = [100.0 + i for i in range(25)]

    breakout_state = MarketState()
    breakout_state.regime = Regime.BREAKOUT
    for c in _candles_with_closes(closes):
        breakout_state.candles_15m.append(c)
    update_indicators(breakout_state)

    unknown_state = MarketState()
    unknown_state.regime = Regime.UNKNOWN
    for c in _candles_with_closes(closes):
        unknown_state.candles_15m.append(c)
    update_indicators(unknown_state)

    assert breakout_state.ema != pytest.approx(unknown_state.ema)
