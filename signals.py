from __future__ import annotations

import logging
from typing import Optional, Tuple

from config import SPREAD_FILTER_ATR_PCT, SQUEEZE_COMPRESSION_ATR, SQUEEZE_LEVEL_ATR_PROXIMITY, SQUEEZE_MIN_BARS
from order_flow import detect_cvd_divergence, get_book_imbalance
from state import MarketState, Regime, Side

logger = logging.getLogger(__name__)


# --- Key level proximity ---

def _nearest_key_level(price: float, state: MarketState) -> Tuple[float, float]:
    """Return (level, distance) for the closest swing high or low."""
    levels = list(state.swing_highs) + list(state.swing_lows)
    if not levels:
        return 0.0, float("inf")
    closest = min(levels, key=lambda lvl: abs(lvl - price))
    return closest, abs(closest - price)


# --- Squeeze detection (Volman compression model) ---

def update_squeeze(state: MarketState) -> None:
    """
    Detect Volman-style "The Squeeze": price compressing in a tight range
    AGAINST a key support/resistance level, indicating absorption.

    squeeze_direction tells us which way the decompression breakout is expected:
      - Price below the level → squeeze against resistance → SHORT on break
      - Price above the level → squeeze against support → LONG on break
    """
    if state.atr <= 0:
        return

    candles = list(state.candles_15m)
    if not candles:
        return

    latest = candles[-1]
    is_compressed = latest.range <= SQUEEZE_COMPRESSION_ATR * state.atr

    key_level, distance = _nearest_key_level(state.last_price, state)
    near_level = key_level > 0 and distance <= SQUEEZE_LEVEL_ATR_PROXIMITY * state.atr

    if is_compressed and near_level:
        state.squeeze_bar_count += 1
        if state.squeeze_bar_count >= SQUEEZE_MIN_BARS:
            state.in_squeeze = True
            state.squeeze_reference_level = key_level
            # Expected breakout direction is INTO the level (price pressed against it)
            state.squeeze_direction = (
                Side.LONG if state.last_price > key_level else Side.SHORT
            )
    else:
        state.squeeze_bar_count = 0
        state.in_squeeze = False
        state.squeeze_reference_level = 0.0
        state.squeeze_direction = None


# --- Entry signal ---

def check_entry_signal(state: MarketState) -> Optional[Side]:
    """
    Returns LONG, SHORT, or None.

    Required conditions (all must pass):
      1. Regime is known (not UNKNOWN)
      2. Active Volman squeeze detected
      3. Squeeze direction aligns with 1h trend bias (or 1h trend is unknown)
      4. No macro context block
      5. In BREAKOUT regime: squeeze must align with the breakout direction
      6. CVD does not show divergence against the planned trade
      7. Order book imbalance does not oppose the planned trade
    """
    if state.regime == Regime.UNKNOWN:
        return None
    if not state.in_squeeze:
        return None
    if state.position is not None:
        return None

    direction = state.squeeze_direction
    if direction is None:
        return None

    # Spread filter — refuse to trade when the book is abnormally wide
    if state.atr > 0 and state.spread > SPREAD_FILTER_ATR_PCT * state.atr:
        logger.debug(
            "Signal rejected: spread %.4f exceeds %.0f%% of ATR %.4f",
            state.spread, SPREAD_FILTER_ATR_PCT * 100, state.atr,
        )
        return None

    # Hard block: never trade against the confirmed higher-timeframe trend
    if state.trend_1h is not None and state.trend_1h != direction:
        logger.debug("Signal rejected: 1h trend %s opposes %s", state.trend_1h, direction)
        return None

    # Macro gates
    if direction == Side.LONG and state.macro_blocks_longs:
        logger.debug("Signal rejected: macro blocks longs")
        return None
    if direction == Side.SHORT and state.macro_blocks_shorts:
        logger.debug("Signal rejected: macro blocks shorts")
        return None

    # In a breakout, only trade in the breakout's direction
    if state.regime == Regime.BREAKOUT:
        candles = list(state.candles_15m)
        if candles:
            last = candles[-1]
            aligned = (direction == Side.LONG and last.bullish) or \
                      (direction == Side.SHORT and last.bearish)
            if not aligned:
                logger.debug("Signal rejected: squeeze direction opposes breakout candle")
                return None

    # CVD filter — divergence warns that the move lacks genuine participation
    divergence = detect_cvd_divergence(state)
    if direction == Side.LONG and divergence == "bearish_divergence":
        logger.debug("Signal rejected: bearish CVD divergence on long setup")
        return None
    if direction == Side.SHORT and divergence == "bullish_divergence":
        logger.debug("Signal rejected: bullish CVD divergence on short setup")
        return None

    # Order book imbalance filter — heavy opposing wall kills the setup
    _, ob_dir = get_book_imbalance(state)
    if direction == Side.LONG and ob_dir == "ask":
        logger.debug("Signal rejected: ask-side book imbalance on long setup")
        return None
    if direction == Side.SHORT and ob_dir == "bid":
        logger.debug("Signal rejected: bid-side book imbalance on short setup")
        return None

    logger.info(
        "Entry signal: %s | regime=%s | level=%.2f | divergence=%s | ob=%s",
        direction.value.upper(), state.regime.value,
        state.squeeze_reference_level, divergence, ob_dir,
    )
    return direction
