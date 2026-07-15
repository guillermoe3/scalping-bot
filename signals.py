from __future__ import annotations

import logging
from typing import Optional, Tuple

import config
from config import SPREAD_FILTER_ATR_PCT, SQUEEZE_LEVEL_ATR_PROXIMITY
from order_flow import detect_cvd_divergence
from state import MarketState, Side

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


# --- Squeeze detection (compression detector only — no directional thesis) ---

def update_squeeze(state: MarketState) -> None:
    """Detect range compression near a swing level.

    The squeeze-based ENTRY hypothesis was rejected twice with clean
    measurement (backtest_runs/ablation-2026-07-14.md: no direction edge, and
    volatility CONTRACTS after a squeeze). What survives is the detector
    itself: compression predicts calm, so `in_squeeze` is a candidate
    "do not trade" filter for future signals. It carries no direction.
    """
    if state.atr <= 0:
        return

    candles = list(state.candles_15m)
    if not candles:
        return

    latest = candles[-1]
    is_compressed = latest.range <= config.SQUEEZE_COMPRESSION_ATR * state.atr
    key_level, distance, _kind = _nearest_key_level(state.last_price, state)
    near_level = key_level > 0 and distance <= SQUEEZE_LEVEL_ATR_PROXIMITY * state.atr

    if is_compressed and near_level:
        state.squeeze_bar_count += 1
        if state.squeeze_bar_count >= config.SQUEEZE_MIN_BARS:
            state.in_squeeze = True
    else:
        state.squeeze_bar_count = 0
        state.in_squeeze = False


# --- Entry gate harness ---
#
# Gates named here MUST be evaluable by the backtest engine (their inputs are
# updated during replay). That is the backtest=live invariant: a gate the
# simulator cannot exercise gives the live bot a behaviour no measurement can
# audit. macro and ob_imbalance were removed for exactly that reason
# (spec 2026-07-14). Enforced by test_backtest_live_invariant_*.
GATE_NAMES = ("spread", "trend_1h", "cvd")
BACKTEST_EVALUABLE_GATES = ("spread", "trend_1h", "cvd")

# cvd is off by default: the 2026-07-14 ablation showed it vetoing good trades
# (PF 0.30 -> 0.51 without it). It stays implemented so a future ablation can
# re-measure it (backtest --enable-gate cvd).
DEFAULT_DISABLED_GATES = frozenset({"cvd"})
DISABLED_GATES: set = set(DEFAULT_DISABLED_GATES)

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


def _passes_gates(state: MarketState, direction: Side) -> bool:
    """Run every named gate against a candidate direction.

    Kept fully wired (and unit-tested) even though no trigger currently
    calls it: this is the reusable half of the ablation harness that the
    next adopted signal must pass through.
    """
    if _vetoed("spread", state.atr > 0 and state.spread > SPREAD_FILTER_ATR_PCT * state.atr):
        logger.debug(
            "Signal rejected: spread %.4f exceeds %.0f%% of ATR %.4f",
            state.spread, SPREAD_FILTER_ATR_PCT * 100, state.atr,
        )
        return False

    if _vetoed("trend_1h", state.trend_1h is not None and state.trend_1h != direction):
        logger.debug("Signal rejected: 1h trend %s opposes %s", state.trend_1h, direction)
        return False

    divergence = detect_cvd_divergence(state)
    cvd_opposes = (direction == Side.LONG and divergence == "bearish_divergence") or \
                  (direction == Side.SHORT and divergence == "bullish_divergence")
    if _vetoed("cvd", cvd_opposes):
        logger.debug("Signal rejected: %s against %s setup", divergence, direction.value)
        return False

    return True


# --- Entry signal ---

def check_entry_signal(state: MarketState) -> Optional[Side]:
    """No entry trigger is currently adopted — always returns None.

    The squeeze trigger was retired after its pre-registered rejection
    (backtest_runs/ablation-2026-07-14.md). A bot with no signal that does
    not trade is the CORRECT state. The next trigger must come from an
    approved base-rate study (see docs/superpowers/specs/
    2026-07-14-ciclo-limpieza-y-estudios-tasa-base-design.md), be expressed
    as trigger + _passes_gates, and survive the ablation harness.
    """
    return None
