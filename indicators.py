from __future__ import annotations

from collections import deque
from typing import List, Tuple

from config import ATR_PERIOD, EMA_PERIOD_BREAKOUT, EMA_PERIOD_CHANNEL, EMA_PERIOD_RANGE, TREND_EMA_5M, TREND_EMA_15M
from state import Candle, Regime, MarketState


# --- Core math ---

def compute_atr(candles: deque, period: int = ATR_PERIOD) -> float:
    c_list = list(candles)
    if len(c_list) < 2:
        return 0.0

    true_ranges: List[float] = []
    for i in range(1, len(c_list)):
        c = c_list[i]
        prev = c_list[i - 1]
        tr = max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close))
        true_ranges.append(tr)

    if not true_ranges:
        return 0.0

    n = min(period, len(true_ranges))
    # Wilder's smoothing (alpha = 1/period)
    atr = sum(true_ranges[:n]) / n
    for tr in true_ranges[n:]:
        atr = (atr * (n - 1) + tr) / n
    return atr


def compute_ema(values: List[float], period: int) -> float:
    if not values:
        return 0.0
    n = min(period, len(values))
    k = 2.0 / (n + 1)
    ema = sum(values[:n]) / n
    for v in values[n:]:
        ema = v * k + ema * (1.0 - k)
    return ema


# --- Regime-adaptive EMA period ---

def ema_period_for_regime(regime: Regime) -> int:
    if regime == Regime.BREAKOUT:
        return EMA_PERIOD_BREAKOUT
    if regime == Regime.TIGHT_CHANNEL:
        return EMA_PERIOD_CHANNEL
    return EMA_PERIOD_RANGE


# --- Swing point detection ---

def detect_swing_points(candles: deque, lookback: int = 5) -> Tuple[List[float], List[float]]:
    """
    Returns (swing_highs, swing_lows).
    A pivot high: the candle's high is the highest in a [lookback] window on each side.
    """
    c_list = list(candles)
    min_len = lookback * 2 + 1
    if len(c_list) < min_len:
        return [], []

    highs: List[float] = []
    lows: List[float] = []

    for i in range(lookback, len(c_list) - lookback):
        window = c_list[i - lookback: i + lookback + 1]
        pivot = c_list[i]
        if pivot.high == max(w.high for w in window):
            highs.append(pivot.high)
        if pivot.low == min(w.low for w in window):
            lows.append(pivot.low)

    return highs, lows


# --- State update entry point ---

def update_indicators(state: MarketState) -> None:
    """Recompute ATR, EMA (regime-adaptive), and MTF EMAs from current candle buffers."""
    if len(state.candles_1m) >= 2:
        state.atr = compute_atr(state.candles_1m)
        closes_1m = [c.close for c in state.candles_1m]
        period = ema_period_for_regime(state.regime)
        state.ema = compute_ema(closes_1m, period)

    if len(state.candles_5m) >= 2:
        closes_5m = [c.close for c in state.candles_5m]
        state.ema_5m = compute_ema(closes_5m, TREND_EMA_5M)

    if len(state.candles_15m) >= 2:
        closes_15m = [c.close for c in state.candles_15m]
        state.ema_15m = compute_ema(closes_15m, TREND_EMA_15M)
