from __future__ import annotations

import logging
from collections import deque
from typing import Optional

from config import (
    BREAKOUT_BODY_ATR_MULT,
    CHANNEL_RANGE_ATR_MULT,
    RANGE_SWEEP_LOOKBACK,
    REGIME_CONFIRM_CANDLES,
)
from state import Candle, MarketState, Regime, Side

logger = logging.getLogger(__name__)


# --- Candle classifiers ---

def _is_breakout_candle(c: Candle, atr: float) -> bool:
    return atr > 0 and c.body >= BREAKOUT_BODY_ATR_MULT * atr


def _is_tight_candle(c: Candle, atr: float) -> bool:
    return atr > 0 and c.range <= CHANNEL_RANGE_ATR_MULT * atr


def _has_liquidity_sweeps_at_both_extremes(candles: deque, lookback: int = RANGE_SWEEP_LOOKBACK) -> bool:
    """
    Confirms a Trading Range by requiring that price has tagged both the top and
    bottom of the lookback window within the most recent 5 candles.
    Prevents TRADING_RANGE from being used as a default fallback.
    """
    c_list = list(candles)[-lookback:]
    if len(c_list) < lookback:
        return False

    range_high = max(c.high for c in c_list)
    range_low = min(c.low for c in c_list)
    span = range_high - range_low
    if span <= 0:
        return False

    threshold = span * 0.04  # within 4% of the extreme counts as a sweep
    recent = c_list[-5:]
    swept_high = any(c.high >= range_high - threshold for c in recent)
    swept_low = any(c.low <= range_low + threshold for c in recent)
    return swept_high and swept_low


def _ema_is_sloping(state: MarketState, atr: float) -> bool:
    """True if the 15m EMA has drifted more than 0.15 ATR vs 10 candles ago."""
    c_list = list(state.candles_15m)
    if len(c_list) < 10 or state.ema <= 0:
        return False
    older_close = c_list[-10].close
    return abs(state.ema - older_close) > 0.15 * atr


# --- Candidate regime inference ---

def _infer_candidate(state: MarketState) -> Regime:
    c_list = list(state.candles_15m)
    if len(c_list) < 5 or state.atr <= 0:
        return Regime.UNKNOWN

    latest = c_list[-1]

    if _is_breakout_candle(latest, state.atr):
        return Regime.BREAKOUT

    recent_5 = c_list[-5:]
    tight_count = sum(1 for c in recent_5 if _is_tight_candle(c, state.atr))

    if tight_count >= 3:
        sloping = _ema_is_sloping(state, state.atr)
        swept = _has_liquidity_sweeps_at_both_extremes(state.candles_15m)

        if swept and not sloping:
            return Regime.TRADING_RANGE
        else:
            return Regime.TIGHT_CHANNEL

    return Regime.UNKNOWN


# --- State machine update ---

def update_regime(state: MarketState) -> None:
    """
    Applies hysteresis: a regime candidate must be confirmed by REGIME_CONFIRM_CANDLES
    consecutive candles before a transition is committed.
    UNKNOWN candidates are ignored — regime is never downgraded by noise.
    """
    if len(state.candles_15m) < 10:
        return

    candidate = _infer_candidate(state)

    if candidate == Regime.UNKNOWN:
        return  # preserve current regime through ambiguous bars

    if candidate == state.regime:
        # Already in this regime — reset pending state
        state.pending_regime = None
        state.regime_confirm_count = 0
    elif candidate == state.pending_regime:
        state.regime_confirm_count += 1
        if state.regime_confirm_count >= REGIME_CONFIRM_CANDLES:
            logger.info("Regime: %s → %s", state.regime.value, candidate.value)
            state.regime = candidate
            state.pending_regime = None
            state.regime_confirm_count = 0
    else:
        # New candidate — start fresh confirmation window
        state.pending_regime = candidate
        state.regime_confirm_count = 1


# --- MTF trend bias ---

def update_mtf_trend(state: MarketState) -> None:
    """Set 15m and 5m trend bias from EMA relationship to current price."""
    p = state.last_price
    if p <= 0:
        return

    if state.ema_15m > 0:
        if p > state.ema_15m * 1.0005:
            state.trend_15m = Side.LONG
        elif p < state.ema_15m * 0.9995:
            state.trend_15m = Side.SHORT
        # else: leave unchanged to avoid flip-flopping at the EMA

    if state.ema_5m > 0:
        if p > state.ema_5m * 1.0003:
            state.trend_5m = Side.LONG
        elif p < state.ema_5m * 0.9997:
            state.trend_5m = Side.SHORT
