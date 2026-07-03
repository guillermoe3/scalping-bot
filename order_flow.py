from __future__ import annotations

import logging
from typing import Optional, List, Tuple

from config import OB_SNAPSHOTS, OB_IMBALANCE_RATIO, CVD_DIVERGENCE_LOOKBACK
from state import BookSnapshot, MarketState

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


# --- Order book ---

def _averaged_bid_ask_volume(snapshots: List[BookSnapshot], depth: int = 10) -> Tuple[float, float]:
    """
    Return (avg_bid_vol, avg_ask_vol) averaged across all snapshots.
    Averaging across N snapshots filters ephemeral spoofing orders.
    """
    if not snapshots:
        return 0.0, 0.0

    bid_totals: List[float] = []
    ask_totals: List[float] = []

    for snap in snapshots:
        bid_totals.append(sum(lvl.quantity for lvl in snap.bids[:depth]))
        ask_totals.append(sum(lvl.quantity for lvl in snap.asks[:depth]))

    return sum(bid_totals) / len(bid_totals), sum(ask_totals) / len(ask_totals)


def get_book_imbalance(state: MarketState) -> Tuple[float, str]:
    """
    Returns (ratio, direction) where direction is "bid", "ask", or "neutral".
    ratio is always >= 1.0.

    "bid" with ratio >= OB_IMBALANCE_RATIO → strong buy-side pressure.
    "ask" with ratio >= OB_IMBALANCE_RATIO → strong sell-side pressure.
    """
    recent = list(state.ob_snapshots)[-OB_SNAPSHOTS:]
    if len(recent) < 2:
        return 1.0, "neutral"

    avg_bid, avg_ask = _averaged_bid_ask_volume(recent)

    if avg_ask <= 0:
        return 1.0, "neutral"

    ratio = avg_bid / avg_ask

    if ratio >= OB_IMBALANCE_RATIO:
        return ratio, "bid"
    if ratio <= 1.0 / OB_IMBALANCE_RATIO:
        return 1.0 / ratio, "ask"
    return ratio, "neutral"
