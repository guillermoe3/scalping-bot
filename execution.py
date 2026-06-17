from __future__ import annotations

import asyncio
import logging
import os

from risk import close_position, manage_position, open_position
from state import MarketState, Side

logger = logging.getLogger(__name__)

PAPER_MODE: bool = os.getenv("PAPER_MODE", "true").lower() == "true"


class ExecutionEngine:
    """
    Handles order routing.

    PAPER_MODE=true  → all orders are simulated at last_price with zero slippage.
    PAPER_MODE=false → routes market orders via ccxt to Binance Futures.

    Position management (SL, TP, trailing) is always handled in-process regardless
    of mode. In live mode, the in-process exit logic fires a market close order.
    """

    def __init__(self, state: MarketState) -> None:
        self.state = state
        self._exchange = None
        if not PAPER_MODE:
            self._init_exchange()

    def _init_exchange(self) -> None:
        try:
            import ccxt
            self._exchange = ccxt.binance({
                "apiKey": os.environ["BINANCE_API_KEY"],
                "secret": os.environ["BINANCE_SECRET"],
                "options": {"defaultType": "future"},
                "enableRateLimit": True,
            })
            logger.info("Live exchange (Binance Futures) initialized")
        except Exception:
            logger.exception("Exchange init failed — running in paper mode")
            self._exchange = None

    async def enter(self, side: Side) -> bool:
        price = self.state.last_price
        if price <= 0:
            return False

        # Always set up position in state first (determines size, SL, TP)
        open_position(self.state, side, price)

        if PAPER_MODE or self._exchange is None:
            return True

        pos = self.state.position
        if pos is None:
            return False

        try:
            order_side = "buy" if side == Side.LONG else "sell"
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._exchange.create_market_order("BTC/USDT", order_side, pos.size),
            )
            return True
        except Exception:
            logger.exception("Live entry order failed — position kept in paper")
            return False

    async def exit(self, reason: str) -> float:
        if self.state.position is None:
            return 0.0

        price = self.state.last_price
        pos = self.state.position

        if not (PAPER_MODE or self._exchange is None):
            try:
                order_side = "sell" if pos.side == Side.LONG else "buy"
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._exchange.create_market_order("BTC/USDT", order_side, pos.size),
                )
            except Exception:
                logger.exception("Live exit order failed")

        return close_position(self.state, price, reason)

    async def monitor_and_exit(self) -> None:
        """Called on every trade tick. Evaluates all exit conditions."""
        if self.state.position is None:
            return
        reason = manage_position(self.state)
        if reason:
            await self.exit(reason)
