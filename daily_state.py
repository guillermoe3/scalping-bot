from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional

from config import DAILY_CLOSES_BUFFER


@dataclass
class DailyClose:
    timestamp: int  # UTC daily candle open time, ms
    close: float


@dataclass
class DailyState:
    closes: deque = field(default_factory=lambda: deque(maxlen=DAILY_CLOSES_BUFFER))
    btc_balance: float = 0.0
    usdt_balance: float = 0.0
    equity_peak_usdt: float = 0.0
    breaker_active: bool = False
    last_rebalance_date: Optional[str] = None


def append_close(state: DailyState, timestamp: int, close: float) -> None:
    state.closes.append(DailyClose(timestamp=timestamp, close=close))


def close_values(state: DailyState) -> List[float]:
    return [c.close for c in state.closes]


def current_equity_usdt(state: DailyState, last_price: float) -> float:
    return state.usdt_balance + state.btc_balance * last_price


def current_exposure_pct(state: DailyState, last_price: float) -> float:
    equity = current_equity_usdt(state, last_price)
    if equity <= 0:
        return 0.0
    return (state.btc_balance * last_price) / equity
