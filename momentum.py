from __future__ import annotations

import logging
import time

from config import MOMENTUM_ABORT_MINUTES
from state import MarketState

logger = logging.getLogger(__name__)

# Volume velocity must fall below this fraction of entry velocity to trigger abort
_VELOCITY_COLLAPSE_RATIO = 0.30


def update_volume_velocity(state: MarketState) -> None:
    """Compute current volume velocity (BTC/second) from the live 1m candle."""
    live = state.live_1m
    if live is None:
        return
    elapsed = (time.time() * 1000.0 - live.timestamp) / 1000.0
    if elapsed > 0:
        state.volume_velocity = live.volume / elapsed


def should_abort_for_momentum(state: MarketState) -> bool:
    """
    Returns True when:
      - A position has been held longer than MOMENTUM_ABORT_MINUTES
      - Current volume velocity collapsed to < 30% of the velocity at entry
      - This signals that the breakout's energy has died; stay in = chop risk
    """
    pos = state.position
    if pos is None:
        return False

    held_seconds = time.time() - pos.entry_time
    if held_seconds < MOMENTUM_ABORT_MINUTES * 60:
        return False

    if state.prior_volume_velocity <= 0:
        return False

    ratio = state.volume_velocity / state.prior_volume_velocity
    if ratio < _VELOCITY_COLLAPSE_RATIO:
        logger.info(
            "Momentum abort: velocity %.4f BTC/s (%.0f%% of entry %.4f BTC/s)",
            state.volume_velocity, ratio * 100, state.prior_volume_velocity,
        )
        return True

    return False
