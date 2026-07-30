from __future__ import annotations

import json
import logging
import sys
from typing import Callable, Optional, Tuple

from config import DAILY_STATE_FILE_PATH, DRAWDOWN_CIRCUIT_BREAKER_PCT, PAPER_BALANCE_USDT
from daily_state import DailyState, append_close, current_equity_usdt

logger = logging.getLogger(__name__)

_BALANCE_TOLERANCE_PCT = 0.001


def update_circuit_breaker(
    state: DailyState,
    last_price: float,
    on_breaker_tripped: Optional[Callable[[dict], None]] = None,
) -> None:
    equity = current_equity_usdt(state, last_price)
    state.equity_peak_usdt = max(state.equity_peak_usdt, equity)
    if state.equity_peak_usdt <= 0:
        return

    drawdown = 1.0 - equity / state.equity_peak_usdt
    if drawdown >= DRAWDOWN_CIRCUIT_BREAKER_PCT and not state.breaker_active:
        state.breaker_active = True
        logger.warning(
            "DAILY CIRCUIT BREAKER ACTIVATED | drawdown=%.1f%% equity=$%.2f peak=$%.2f",
            drawdown * 100, equity, state.equity_peak_usdt,
        )
        if on_breaker_tripped is not None:
            on_breaker_tripped({"drawdown_pct": drawdown, "equity_usdt": equity})


def save_state(state: DailyState) -> None:
    payload = {
        "closes": [{"timestamp": c.timestamp, "close": c.close} for c in state.closes],
        "btc_balance": state.btc_balance,
        "usdt_balance": state.usdt_balance,
        "equity_peak_usdt": state.equity_peak_usdt,
        "breaker_active": state.breaker_active,
        "last_rebalance_date": state.last_rebalance_date,
    }
    try:
        with open(DAILY_STATE_FILE_PATH, "w") as f:
            json.dump(payload, f)
    except OSError:
        logger.exception("Failed to write %s", DAILY_STATE_FILE_PATH)


def load_into_state(state: DailyState) -> bool:
    """Returns True if a persisted state file was found and loaded."""
    try:
        with open(DAILY_STATE_FILE_PATH, "r") as f:
            payload = json.load(f)
    except FileNotFoundError:
        return False
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not parse %s — starting with fresh state", DAILY_STATE_FILE_PATH)
        return False

    try:
        for row in payload.get("closes", []):
            append_close(state, row["timestamp"], row["close"])
        state.btc_balance = payload.get("btc_balance", 0.0)
        state.usdt_balance = payload.get("usdt_balance", 0.0)
        state.equity_peak_usdt = payload.get("equity_peak_usdt", 0.0)
        state.breaker_active = payload.get("breaker_active", False)
        state.last_rebalance_date = payload.get("last_rebalance_date")
    except (TypeError, KeyError, ValueError):
        logger.warning("Could not parse %s — starting with fresh state", DAILY_STATE_FILE_PATH)
        return False
    return True


def fetch_spot_balances(exchange) -> Tuple[float, float]:
    """Returns (btc_total, usdt_total). Exits the process rather than
    guessing when the fetch fails — same fail-closed criterion as
    safety.fetch_real_balance."""
    try:
        balance = exchange.fetch_balance()
        btc = float(balance["total"].get("BTC", 0.0))
        usdt = float(balance["total"].get("USDT", 0.0))
    except Exception:
        logger.error("Could not fetch real spot balances", exc_info=True)
        sys.exit(1)
    return btc, usdt


def reconcile_with_exchange(state: DailyState, exchange) -> None:
    """Compares the persisted balances against the exchange's real reported
    balances. Exits the process rather than guessing when they disagree."""
    btc, usdt = fetch_spot_balances(exchange)

    btc_diff = abs(state.btc_balance - btc)
    usdt_diff = abs(state.usdt_balance - usdt)
    btc_ok = btc_diff <= max(btc, state.btc_balance, 1e-8) * _BALANCE_TOLERANCE_PCT
    usdt_ok = usdt_diff <= max(usdt, state.usdt_balance, 1.0) * _BALANCE_TOLERANCE_PCT

    if btc_ok and usdt_ok:
        logger.info("Reconciliation OK: btc=%.6f usdt=%.2f", btc, usdt)
        return

    logger.error(
        "RECONCILIATION MISMATCH — persisted btc=%.6f usdt=%.2f vs exchange btc=%.6f usdt=%.2f "
        "— refusing to start, manual review required",
        state.btc_balance, state.usdt_balance, btc, usdt,
    )
    sys.exit(1)


def ensure_initialized(state: DailyState, exchange, found_persisted: bool, last_price: float) -> None:
    """Called once at startup, after backfill. On a fresh install (no prior
    save_state ever ran), seeds balances from the paper default or the real
    exchange — there's nothing to reconcile against yet. On a resumed run
    with an exchange configured, reconciles instead."""
    if found_persisted:
        if exchange is not None:
            reconcile_with_exchange(state, exchange)
        return

    if exchange is None:
        state.usdt_balance = PAPER_BALANCE_USDT
        state.btc_balance = 0.0
    else:
        btc, usdt = fetch_spot_balances(exchange)
        state.btc_balance = btc
        state.usdt_balance = usdt

    state.equity_peak_usdt = current_equity_usdt(state, last_price)
