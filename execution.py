from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, Optional

import clock
from risk import apply_partial_close, close_position, manage_position, open_position
from state import MarketState, Side

logger = logging.getLogger(__name__)

PAPER_MODE: bool = os.getenv("PAPER_MODE", "true").lower() == "true"


class ExecutionEngine:
    """
    Handles order routing.

    PAPER_MODE=true  → orders are simulated by crossing the bid/ask spread (entries fill
                        at last_ask/last_bid, exits at last_bid/last_ask), with no fee
                        assumed beyond TAKER_FEE_RATE.
    PAPER_MODE=false → routes market orders via ccxt to Binance Futures.

    Position management (SL, TP, trailing) is always handled in-process regardless
    of mode. In live mode, the in-process exit logic fires a market close order.
    """

    def __init__(self, state: MarketState, on_trade_closed: Optional[Callable[[dict], None]] = None) -> None:
        self.state = state
        self._exchange = None
        self._on_trade_closed = on_trade_closed
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

    @property
    def exchange(self):
        return self._exchange

    async def enter(self, side: Side) -> bool:
        if self.state.last_bid <= 0 or self.state.last_ask <= 0:
            return False

        fill_price = self.state.last_ask if side == Side.LONG else self.state.last_bid
        open_position(self.state, side, fill_price)

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

        pos = self.state.position
        fill_price = self.state.last_bid if pos.side == Side.LONG else self.state.last_ask

        if not (PAPER_MODE or self._exchange is None):
            try:
                order_side = "sell" if pos.side == Side.LONG else "buy"
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._exchange.create_market_order("BTC/USDT", order_side, pos.size),
                )
            except Exception:
                logger.exception("Live exit order failed")

        side, entry_price, size, entry_time = pos.side, pos.entry_price, pos.size, pos.entry_time
        net = close_position(self.state, fill_price, reason)

        if self._on_trade_closed is not None:
            self._on_trade_closed({
                "side": side, "entry_price": entry_price, "exit_price": fill_price,
                "size": size, "reason": reason, "leg_net": net,
                "total_trade_net": pos.realized_pnl, "fees_paid": pos.fees_paid,
                "entry_time": entry_time, "exit_time": clock.now(), "is_partial": False,
            })

        return net

    async def partial_exit(self, close_size: float, reason: str) -> float:
        pos = self.state.position
        if pos is None:
            return 0.0

        fill_price = self.state.last_bid if pos.side == Side.LONG else self.state.last_ask

        if not (PAPER_MODE or self._exchange is None):
            try:
                order_side = "sell" if pos.side == Side.LONG else "buy"
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._exchange.create_market_order(
                        "BTC/USDT", order_side, close_size, params={"reduceOnly": True},
                    ),
                )
            except Exception:
                logger.exception("Live partial-exit order failed")

        side, entry_price, entry_time = pos.side, pos.entry_price, pos.entry_time
        net = apply_partial_close(self.state, close_size, fill_price)

        if self._on_trade_closed is not None:
            self._on_trade_closed({
                "side": side, "entry_price": entry_price, "exit_price": fill_price,
                "size": close_size, "reason": reason, "leg_net": net,
                "total_trade_net": None, "fees_paid": pos.fees_paid,
                "entry_time": entry_time, "exit_time": clock.now(), "is_partial": True,
            })

        return net

    async def monitor_and_exit(self) -> None:
        """Called on every trade tick. Evaluates TP1 and all exit conditions."""
        if self.state.position is None:
            return
        tp1_close_size, reason = manage_position(self.state)
        if tp1_close_size:
            await self.partial_exit(tp1_close_size, "tp1")
        if reason:
            await self.exit(reason)
