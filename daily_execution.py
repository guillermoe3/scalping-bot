from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, Optional

from config import REBALANCE_BAND_PCT, SPOT_TAKER_FEE_RATE
from daily_state import DailyState, current_equity_usdt, current_exposure_pct

logger = logging.getLogger(__name__)

PAPER_MODE: bool = os.getenv("PAPER_MODE", "true").lower() == "true"


class DailyExecutionEngine:
    """Compares the target exposure against the current one and, if the gap
    clears REBALANCE_BAND_PCT, trades the difference in spot BTC/USDT. Below
    the band, does nothing — this is a deliberate operational approximation
    of the daily-rebalanced study (see spec section 2, no-goals)."""

    def __init__(self, state: DailyState, on_rebalanced: Optional[Callable[[dict], None]] = None) -> None:
        self.state = state
        self._exchange = None
        self._on_rebalanced = on_rebalanced
        if not PAPER_MODE:
            self._init_exchange()

    def _init_exchange(self) -> None:
        try:
            import ccxt
            self._exchange = ccxt.binance({
                "apiKey": os.environ["BINANCE_API_KEY"],
                "secret": os.environ["BINANCE_SECRET"],
                "options": {"defaultType": "spot"},
                "enableRateLimit": True,
            })
            logger.info("Live exchange (Binance Spot) initialized")
        except Exception:
            logger.exception("Exchange init failed — running in paper mode")
            self._exchange = None

    @property
    def exchange(self):
        return self._exchange

    async def rebalance(self, target_exposure: float, last_price: float) -> bool:
        current = current_exposure_pct(self.state, last_price)
        gap = target_exposure - current
        if abs(gap) < REBALANCE_BAND_PCT:
            return False

        equity = current_equity_usdt(self.state, last_price)
        delta_usdt = gap * equity
        side = "buy" if delta_usdt > 0 else "sell"
        btc_amount = round(abs(delta_usdt) / last_price, 6)
        if btc_amount <= 0:
            return False

        if not PAPER_MODE and self._exchange is not None:
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: self._exchange.create_market_order("BTC/USDT", side, btc_amount),
                )
            except Exception:
                logger.exception("Live spot rebalance order failed — will retry next daily close")
                return False

        self._apply_fill(side, btc_amount, last_price)
        return True

    def _apply_fill(self, side: str, btc_amount: float, price: float) -> None:
        fee = btc_amount * price * SPOT_TAKER_FEE_RATE
        if side == "buy":
            self.state.btc_balance += btc_amount
            self.state.usdt_balance -= btc_amount * price + fee
        else:
            self.state.btc_balance -= btc_amount
            self.state.usdt_balance += btc_amount * price - fee

        new_exposure = current_exposure_pct(self.state, price)
        logger.info(
            "REBALANCE %s %.6f BTC @ %.2f | fee=$%.2f | exposure -> %.1f%%",
            side.upper(), btc_amount, price, fee, new_exposure * 100,
        )
        if self._on_rebalanced is not None:
            self._on_rebalanced({
                "side": side, "btc_amount": btc_amount, "price": price,
                "fee": fee, "new_exposure": new_exposure,
            })
