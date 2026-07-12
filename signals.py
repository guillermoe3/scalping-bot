from __future__ import annotations

import logging
from typing import Optional, Tuple

from config import SPREAD_FILTER_ATR_PCT, SQUEEZE_COMPRESSION_ATR, SQUEEZE_LEVEL_ATR_PROXIMITY, SQUEEZE_MIN_BARS
from order_flow import detect_cvd_divergence, get_book_imbalance
from state import MarketState, Regime, Side

logger = logging.getLogger(__name__)


# --- Key level proximity ---

def _nearest_key_level(price: float, state: MarketState) -> Tuple[float, float, str]:
    """Return (level, distance, kind) for the closest swing level.

    kind is "support" (swing low) or "resistance" (swing high). On an exact
    distance tie the level consistent with the price side wins (support at or
    below price, resistance at or above); if both qualify, support wins.
    """
    candidates = [(lvl, abs(lvl - price), "support") for lvl in state.swing_lows]
    candidates += [(lvl, abs(lvl - price), "resistance") for lvl in state.swing_highs]
    if not candidates:
        return 0.0, float("inf"), "support"

    def _rank(candidate):
        lvl, dist, kind = candidate
        consistent = (kind == "support" and lvl <= price) or (kind == "resistance" and lvl >= price)
        return (dist, 0 if consistent else 1, 0 if kind == "support" else 1)

    return min(candidates, key=_rank)


# --- Squeeze detection (Volman compression model) ---

# Entry model variant: "fade" (bet on level rejection, pre-break) or "break"
# (enter on confirmed break of the squeeze level). Backtest overrides this;
# live default stays "fade".
ENTRY_VARIANT = "fade"

GATE_NAMES = ("regime_known", "spread", "trend_1h", "macro", "breakout_align", "cvd", "ob_imbalance")

# Backtest ablation hooks: gates listed here are skipped entirely.
DISABLED_GATES: set = set()

# Diagnostic counters, reset per backtest run via reset_signal_stats().
GATE_VETO_COUNTS = {name: 0 for name in GATE_NAMES}
SIGNAL_STATS = {"fired": 0}


def reset_signal_stats() -> None:
    for name in GATE_NAMES:
        GATE_VETO_COUNTS[name] = 0
    SIGNAL_STATS["fired"] = 0


def _vetoed(name: str, opposes: bool) -> bool:
    """A named gate rejects the candidate signal (unless disabled)."""
    if name in DISABLED_GATES or not opposes:
        return False
    GATE_VETO_COUNTS[name] += 1
    return True


def _clear_broken(state: MarketState) -> None:
    state.squeeze_broken = False
    state.squeeze_broken_direction = None
    state.squeeze_broken_level = 0.0
    state.squeeze_broken_ttl = 0


def update_squeeze(state: MarketState) -> None:
    """
    Detect Volman-style "The Squeeze": price compressing in a tight range
    against a key support/resistance level, and track its resolution.

    Two downstream consumers:
      - fade variant: squeeze_direction is the bounce off the level's kind
        (support → LONG, resistance → SHORT); incoherent kind → no thesis.
      - break variant: when an armed squeeze closes across its reference
        level, squeeze_broken opens a 2-bar entry window in the break's
        real direction.
    """
    if state.atr <= 0:
        return

    candles = list(state.candles_15m)
    if not candles:
        return

    latest = candles[-1]

    # Age out a previous break window (decrement happens on every close
    # AFTER the detection candle; the window covers closes N and N+1).
    if state.squeeze_broken:
        state.squeeze_broken_ttl -= 1
        if state.squeeze_broken_ttl <= 0:
            _clear_broken(state)

    # Break detection must run BEFORE the compression reset wipes the
    # armed squeeze — the breakout candle is by definition not compressed.
    if state.in_squeeze and state.squeeze_reference_level > 0:
        level = state.squeeze_reference_level
        broke_down = state.squeeze_price_above_level is True and latest.close < level
        broke_up = state.squeeze_price_above_level is False and latest.close > level
        if broke_down or broke_up:
            state.squeeze_broken = True
            state.squeeze_broken_direction = Side.SHORT if broke_down else Side.LONG
            state.squeeze_broken_level = level
            state.squeeze_broken_ttl = 2

    is_compressed = latest.range <= SQUEEZE_COMPRESSION_ATR * state.atr
    key_level, distance, level_kind = _nearest_key_level(state.last_price, state)
    near_level = key_level > 0 and distance <= SQUEEZE_LEVEL_ATR_PROXIMITY * state.atr

    if is_compressed and near_level:
        state.squeeze_bar_count += 1
        if state.squeeze_bar_count >= SQUEEZE_MIN_BARS:
            state.in_squeeze = True
            state.squeeze_reference_level = key_level
            state.squeeze_price_above_level = state.last_price > key_level
            # Fade thesis only makes sense against the level's real kind:
            # compressed on top of support → bounce up; under resistance → bounce down.
            if level_kind == "support" and state.last_price >= key_level:
                state.squeeze_direction = Side.LONG
            elif level_kind == "resistance" and state.last_price <= key_level:
                state.squeeze_direction = Side.SHORT
            else:
                state.squeeze_direction = None
    else:
        state.squeeze_bar_count = 0
        state.in_squeeze = False
        state.squeeze_reference_level = 0.0
        state.squeeze_direction = None
        state.squeeze_price_above_level = None


# --- Entry signal ---

def check_entry_signal(state: MarketState) -> Optional[Side]:
    """
    Returns LONG, SHORT, or None.

    Required conditions (all must pass):
      1. Variant-specific squeeze candidate: an armed squeeze (fade) or a
         just-broken squeeze (break) supplies a direction
      2. Direction is resolved (squeeze/break direction is not None)
      3. No position already open
      4. Named gates, in order (each individually disableable via
         DISABLED_GATES and counted in GATE_VETO_COUNTS on rejection):
           - regime_known: regime is not UNKNOWN
           - spread: book spread within ATR-relative bound
           - trend_1h: direction aligns with 1h trend bias (or unknown)
           - macro: no macro context block for this direction
           - breakout_align: in BREAKOUT regime, squeeze aligns with the
             breakout candle
           - cvd: CVD shows no divergence against the planned trade
           - ob_imbalance: order book imbalance does not oppose the trade
    """
    if ENTRY_VARIANT == "break":
        if not state.squeeze_broken:
            return None
        direction = state.squeeze_broken_direction
    else:
        if not state.in_squeeze:
            return None
        direction = state.squeeze_direction
    if direction is None:
        return None
    if state.position is not None:
        return None

    if _vetoed("regime_known", state.regime == Regime.UNKNOWN):
        logger.debug("Signal rejected: regime unknown")
        return None

    if _vetoed("spread", state.atr > 0 and state.spread > SPREAD_FILTER_ATR_PCT * state.atr):
        logger.debug(
            "Signal rejected: spread %.4f exceeds %.0f%% of ATR %.4f",
            state.spread, SPREAD_FILTER_ATR_PCT * 100, state.atr,
        )
        return None

    if _vetoed("trend_1h", state.trend_1h is not None and state.trend_1h != direction):
        logger.debug("Signal rejected: 1h trend %s opposes %s", state.trend_1h, direction)
        return None

    macro_opposes = (direction == Side.LONG and state.macro_blocks_longs) or \
                    (direction == Side.SHORT and state.macro_blocks_shorts)
    if _vetoed("macro", macro_opposes):
        logger.debug("Signal rejected: macro blocks %s", direction.value)
        return None

    breakout_opposes = False
    if state.regime == Regime.BREAKOUT:
        candles = list(state.candles_15m)
        if candles:
            last = candles[-1]
            breakout_opposes = not ((direction == Side.LONG and last.bullish) or
                                    (direction == Side.SHORT and last.bearish))
    if _vetoed("breakout_align", breakout_opposes):
        logger.debug("Signal rejected: squeeze direction opposes breakout candle")
        return None

    divergence = detect_cvd_divergence(state)
    cvd_opposes = (direction == Side.LONG and divergence == "bearish_divergence") or \
                  (direction == Side.SHORT and divergence == "bullish_divergence")
    if _vetoed("cvd", cvd_opposes):
        logger.debug("Signal rejected: %s against %s setup", divergence, direction.value)
        return None

    _, ob_dir = get_book_imbalance(state)
    ob_opposes = (direction == Side.LONG and ob_dir == "ask") or \
                 (direction == Side.SHORT and ob_dir == "bid")
    if _vetoed("ob_imbalance", ob_opposes):
        logger.debug("Signal rejected: %s-side book imbalance on %s setup", ob_dir, direction.value)
        return None

    SIGNAL_STATS["fired"] += 1
    if ENTRY_VARIANT == "break":
        _clear_broken(state)

    logger.info(
        "Entry signal: %s | regime=%s | level=%.2f | divergence=%s | ob=%s",
        direction.value.upper(), state.regime.value,
        state.squeeze_reference_level, divergence, ob_dir,
    )
    return direction
