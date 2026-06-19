from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict
from typing import Optional

import clock
from config import (
    KILL_SWITCH_CONSECUTIVE_LOSSES,
    KILL_SWITCH_DAILY_LOSS_PCT,
    PAPER_BALANCE_USDT,
    STATE_FILE_PATH,
)
from state import MarketState, Position, Side

logger = logging.getLogger(__name__)


def fetch_real_balance(exchange) -> float:
    """Fetches the real USDT wallet balance from the exchange. Exits the
    process rather than guessing when the fetch fails or the response is
    malformed — same fail-closed criterion as reconcile_with_exchange."""
    try:
        balance = exchange.fetch_balance()
        total = balance["total"]["USDT"]
    except Exception:
        logger.error("Could not fetch real account balance", exc_info=True)
        sys.exit(1)
    return float(total)


def _today_utc() -> str:
    return clock.today_utc()


def maybe_reset_daily(state: MarketState, exchange=None) -> None:
    """Reset daily counters and the kill switch when the UTC date has rolled
    over, and (re)resolve the daily starting balance used for position
    sizing and the kill switch threshold."""
    today = _today_utc()
    if state.last_reset_date == today and state.daily_starting_balance is not None:
        return
    state.daily_starting_balance = (
        PAPER_BALANCE_USDT if exchange is None else fetch_real_balance(exchange)
    )
    state.pnl_today = 0.0
    state.trades_today = 0
    state.consecutive_losses = 0
    state.kill_switch_active = False
    state.last_reset_date = today
    save_state(state)


def can_open_new_position(state: MarketState) -> bool:
    maybe_reset_daily(state)
    return not state.kill_switch_active


def after_trade_closed(state: MarketState, total_trade_net: float, balance: float) -> None:
    if total_trade_net < 0:
        state.consecutive_losses += 1
    else:
        state.consecutive_losses = 0

    daily_loss_breached = state.pnl_today <= -KILL_SWITCH_DAILY_LOSS_PCT * balance
    streak_breached = state.consecutive_losses >= KILL_SWITCH_CONSECUTIVE_LOSSES

    if (daily_loss_breached or streak_breached) and not state.kill_switch_active:
        state.kill_switch_active = True
        logger.warning(
            "KILL SWITCH activated | daily_loss_breached=%s streak_breached=%s "
            "pnl_today=$%+.2f consecutive_losses=%d",
            daily_loss_breached, streak_breached, state.pnl_today, state.consecutive_losses,
        )

    save_state(state)


def _position_to_dict(pos: Optional[Position]) -> Optional[dict]:
    if pos is None:
        return None
    data = asdict(pos)
    data["side"] = pos.side.value
    return data


def _position_from_dict(data: Optional[dict]) -> Optional[Position]:
    if data is None:
        return None
    data = dict(data)
    data["side"] = Side(data["side"])
    return Position(**data)


def save_state(state: MarketState) -> None:
    payload = {
        "date_utc": state.last_reset_date,
        "pnl_today": state.pnl_today,
        "trades_today": state.trades_today,
        "consecutive_losses": state.consecutive_losses,
        "kill_switch_active": state.kill_switch_active,
        "position": _position_to_dict(state.position),
    }
    try:
        with open(STATE_FILE_PATH, "w") as f:
            json.dump(payload, f)
    except OSError:
        logger.exception("Failed to write %s", STATE_FILE_PATH)


def load_into_state(state: MarketState) -> None:
    try:
        with open(STATE_FILE_PATH, "r") as f:
            payload = json.load(f)
    except FileNotFoundError:
        return
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not parse %s — starting with fresh state", STATE_FILE_PATH)
        return

    try:
        last_reset_date = payload.get("date_utc")
        pnl_today = payload.get("pnl_today", 0.0)
        trades_today = payload.get("trades_today", 0)
        consecutive_losses = payload.get("consecutive_losses", 0)
        kill_switch_active = payload.get("kill_switch_active", False)
        position = _position_from_dict(payload.get("position"))
    except (TypeError, KeyError, ValueError):
        logger.warning("Could not parse %s — starting with fresh state", STATE_FILE_PATH)
        return

    state.last_reset_date = last_reset_date
    state.pnl_today = pnl_today
    state.trades_today = trades_today
    state.consecutive_losses = consecutive_losses
    state.kill_switch_active = kill_switch_active
    state.position = position


_SIZE_TOLERANCE_PCT = 0.001  # 0.1% size tolerance when matching persisted vs exchange position


def _fetch_exchange_position(exchange) -> Optional[dict]:
    positions = exchange.fetch_positions(["BTC/USDT"])
    for p in positions:
        contracts = float(p.get("contracts") or 0)
        if contracts > 0:
            side = Side.LONG if p.get("side") == "long" else Side.SHORT
            return {"side": side, "size": contracts}
    return None


def reconcile_with_exchange(state: MarketState, exchange) -> None:
    """Compares the persisted position (already loaded into state.position by
    load_into_state) against the exchange's real reported position. Exits the
    process rather than guessing when they disagree."""
    try:
        exchange_pos = _fetch_exchange_position(exchange)
    except Exception:
        logger.error("Could not fetch exchange positions for reconciliation", exc_info=True)
        sys.exit(1)

    persisted = state.position

    if persisted is None and exchange_pos is None:
        logger.info("Reconciliation OK: no open position on either side")
        return

    if persisted is not None and exchange_pos is not None:
        size_diff_pct = abs(persisted.size - exchange_pos["size"]) / exchange_pos["size"]
        if persisted.side == exchange_pos["side"] and size_diff_pct <= _SIZE_TOLERANCE_PCT:
            logger.info(
                "Reconciliation OK: resuming %s position, size=%.6f",
                persisted.side.value, persisted.size,
            )
            return

    logger.error(
        "RECONCILIATION MISMATCH — persisted=%s exchange=%s — refusing to start, "
        "manual review required",
        persisted, exchange_pos,
    )
    sys.exit(1)
