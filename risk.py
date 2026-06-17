from __future__ import annotations

import logging
import time
from typing import Optional

from config import (
    ACCOUNT_RISK_PCT,
    ATR_BREATHING_THRESHOLD,
    BREAKEVEN_ATR_TRIGGER,
    INITIAL_SL_ATR,
    TIME_EXIT_MINUTES,
    TP1_CLOSE_PCT,
    TP1_RR,
)
from indicators import detect_swing_points
from state import MarketState, Position, Side

logger = logging.getLogger(__name__)

# Used in paper mode; replace with live account balance query for live trading
PAPER_BALANCE_USDT = 10_000.0


# --- Position sizing ---

def _compute_size(entry: float, stop: float, balance: float) -> float:
    """Risk ACCOUNT_RISK_PCT of balance on this trade."""
    sl_dist = abs(entry - stop)
    if sl_dist <= 0:
        return 0.0
    risk_usd = balance * ACCOUNT_RISK_PCT
    return round(risk_usd / sl_dist, 6)


# --- Entry level calculation ---

def _compute_levels(side: Side, entry: float, atr: float) -> tuple[float, float]:
    """Return (stop_loss, tp1)."""
    sl_dist = INITIAL_SL_ATR * atr
    tp_dist = sl_dist * TP1_RR
    if side == Side.LONG:
        return entry - sl_dist, entry + tp_dist
    return entry + sl_dist, entry - tp_dist


# --- Open / close ---

def open_position(
    state: MarketState,
    side: Side,
    price: float,
    balance: float = PAPER_BALANCE_USDT,
) -> None:
    stop_loss, tp1 = _compute_levels(side, price, state.atr)
    size = _compute_size(price, stop_loss, balance)
    sl_dist = abs(price - stop_loss)

    state.position = Position(
        side=side,
        entry_price=price,
        size=size,
        entry_time=time.time(),
        stop_loss=stop_loss,
        tp1=tp1,
        initial_atr=state.atr,
        initial_sl_distance=sl_dist,
    )
    state.prior_volume_velocity = state.volume_velocity

    logger.info(
        "OPEN %s @ %.2f | SL=%.2f | TP1=%.2f | size=%.6f BTC | risk=$%.2f",
        side.value.upper(), price, stop_loss, tp1, size, size * sl_dist,
    )


def close_position(state: MarketState, price: float, reason: str) -> float:
    pos = state.position
    if pos is None:
        return 0.0

    pnl = (
        (price - pos.entry_price) * pos.size
        if pos.side == Side.LONG
        else (pos.entry_price - price) * pos.size
    )

    state.pnl_today += pnl
    state.trades_today += 1
    state.position = None

    logger.info(
        "CLOSE %s @ %.2f | reason=%-16s | P&L=$%+.2f | daily=$%+.2f",
        pos.side.value.upper(), price, reason, pnl, state.pnl_today,
    )
    return pnl


# --- Dynamic stop management ---

def _apply_breakeven(state: MarketState) -> None:
    pos = state.position
    if pos is None or pos.breakeven_moved:
        return

    price = state.last_price
    profit = abs(price - pos.entry_price)

    if profit < BREAKEVEN_ATR_TRIGGER * pos.initial_atr:
        return

    if pos.side == Side.LONG and price > pos.entry_price:
        new_sl = max(pos.stop_loss, pos.entry_price)
        if new_sl != pos.stop_loss:
            pos.stop_loss = new_sl
            pos.breakeven_moved = True
            logger.info("Breakeven: SL moved to %.2f", new_sl)
    elif pos.side == Side.SHORT and price < pos.entry_price:
        new_sl = min(pos.stop_loss, pos.entry_price)
        if new_sl != pos.stop_loss:
            pos.stop_loss = new_sl
            pos.breakeven_moved = True
            logger.info("Breakeven: SL moved to %.2f", new_sl)


def _apply_breathing_stop(state: MarketState) -> None:
    """Expand SL if live ATR has grown significantly since entry — avoids premature stops."""
    pos = state.position
    if pos is None or pos.initial_atr <= 0 or state.atr <= 0:
        return

    growth = state.atr / pos.initial_atr
    if growth < ATR_BREATHING_THRESHOLD:
        return

    new_dist = INITIAL_SL_ATR * state.atr
    if pos.side == Side.LONG:
        new_sl = pos.entry_price - new_dist
        if new_sl < pos.stop_loss:  # only expand, never tighten via this path
            pos.stop_loss = new_sl
            logger.info("Breathing SL: expanded to %.2f (ATR +%.0f%%)", new_sl, (growth - 1) * 100)
    else:
        new_sl = pos.entry_price + new_dist
        if new_sl > pos.stop_loss:
            pos.stop_loss = new_sl
            logger.info("Breathing SL: expanded to %.2f (ATR +%.0f%%)", new_sl, (growth - 1) * 100)


def _apply_structural_trail(state: MarketState) -> None:
    """Trail SL behind the most recent structural swing point in favour of the trade."""
    pos = state.position
    if pos is None:
        return

    highs, lows = detect_swing_points(state.candles_1m, lookback=3)

    if pos.side == Side.LONG and lows:
        # Trail behind the highest recent swing low that is above our original SL
        candidates = [l for l in lows if l > pos.entry_price - pos.initial_sl_distance]
        if candidates:
            trail = max(candidates)
            if trail > pos.stop_loss:
                pos.stop_loss = trail
                logger.debug("Structural trail: SL → %.2f", trail)

    elif pos.side == Side.SHORT and highs:
        candidates = [h for h in highs if h < pos.entry_price + pos.initial_sl_distance]
        if candidates:
            trail = min(candidates)
            if trail < pos.stop_loss:
                pos.stop_loss = trail
                logger.debug("Structural trail: SL → %.2f", trail)


def _handle_tp1(state: MarketState) -> None:
    pos = state.position
    if pos is None or pos.tp1_hit:
        return

    price = state.last_price
    hit = (pos.side == Side.LONG and price >= pos.tp1) or \
          (pos.side == Side.SHORT and price <= pos.tp1)

    if hit:
        pos.tp1_hit = True
        pos.size = round(pos.size * (1.0 - TP1_CLOSE_PCT), 6)
        logger.info("TP1 hit @ %.2f — position reduced to %.6f BTC", price, pos.size)


# --- Main position monitor ---

def manage_position(state: MarketState) -> Optional[str]:
    """
    Called on every tick. Returns an exit reason string or None.
    Also handles TP1 partial close and all dynamic SL updates.
    """
    from momentum import should_abort_for_momentum

    if state.position is None:
        return None

    pos = state.position
    price = state.last_price
    held_min = (time.time() - pos.entry_time) / 60.0

    # Update stops (order matters: breakeven before trail)
    _apply_breakeven(state)
    _apply_breathing_stop(state)
    _apply_structural_trail(state)
    _handle_tp1(state)

    # Exit checks
    sl_hit = (pos.side == Side.LONG and price <= pos.stop_loss) or \
             (pos.side == Side.SHORT and price >= pos.stop_loss)
    if sl_hit:
        return "stop_loss"

    if held_min >= TIME_EXIT_MINUTES:
        return "time_exit"

    if should_abort_for_momentum(state):
        return "momentum_abort"

    return None
