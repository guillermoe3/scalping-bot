from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from config import (
    KILL_SWITCH_CONSECUTIVE_LOSSES,
    KILL_SWITCH_DAILY_LOSS_PCT,
    STATE_FILE_PATH,
)
from state import MarketState, Position, Side

logger = logging.getLogger(__name__)


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def maybe_reset_daily(state: MarketState) -> None:
    """Reset daily counters and the kill switch when the UTC date has rolled over."""
    today = _today_utc()
    if state.last_reset_date == today:
        return
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

    state.last_reset_date = payload.get("date_utc")
    state.pnl_today = payload.get("pnl_today", 0.0)
    state.trades_today = payload.get("trades_today", 0)
    state.consecutive_losses = payload.get("consecutive_losses", 0)
    state.kill_switch_active = payload.get("kill_switch_active", False)
    state.position = _position_from_dict(payload.get("position"))
