from __future__ import annotations

import logging
from typing import Optional

from config import CVD_DIVERGENCE_LOOKBACK
from state import MarketState

logger = logging.getLogger(__name__)


# --- CVD ---

def snapshot_cvd_on_close(state: MarketState) -> None:
    """Save running CVD at candle close, then reset for the next candle."""
    state.cvd_per_candle.append(state.cvd)
    state.cvd = 0.0


def detect_cvd_divergence(state: MarketState) -> Optional[str]:
    """
    Returns "bearish_divergence", "bullish_divergence", or None.

    Bearish: price printed a higher high but CVD trend is falling → absorption selling.
    Bullish: price printed a lower low but CVD trend is rising → absorption buying.

    Uses the last CVD_DIVERGENCE_LOOKBACK closed candles.
    """
    candles = list(state.candles_15m)
    cvds = list(state.cvd_per_candle)
    n = min(CVD_DIVERGENCE_LOOKBACK, len(candles), len(cvds))
    if n < 3:
        return None

    recent_candles = candles[-n:]
    recent_cvds = cvds[-n:]

    price_highs = [c.high for c in recent_candles]
    price_lows = [c.low for c in recent_candles]

    if price_highs[-1] > price_highs[-2] and recent_cvds[-1] < recent_cvds[-2]:
        return "bearish_divergence"
    if price_lows[-1] < price_lows[-2] and recent_cvds[-1] > recent_cvds[-2]:
        return "bullish_divergence"

    return None
