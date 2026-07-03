from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, replace
from typing import Callable, Optional

import clock
from config import ENTRY_ORDER_TIMEOUT_SECONDS, MAKER_FEE_RATE
from risk import EntryPlan, apply_partial_close, close_position, manage_position, open_planned, plan_entry
from state import MarketState, Side

logger = logging.getLogger(__name__)

PAPER_MODE: bool = os.getenv("PAPER_MODE", "true").lower() == "true"
_LIVE_FILL_POLL_SECONDS = 5.0


@dataclass
class PendingEntry:
    """A resting post-only limit entry, placed but not yet filled."""
    plan: EntryPlan
    placed_at: float                # clock seconds
    order_id: Optional[str] = None  # live only


class ExecutionEngine:
    """
    Handles order routing.

    PAPER_MODE=true  → entries rest as post-only limits filled when price trades through;
                        exits cross the spread as before.
    PAPER_MODE=false → live post-only routing lands in Task 5; until then live mode
                        behaves like paper for entries (position is simulated).

    Position management (SL, TP, trailing) is always handled in-process regardless
    of mode. In live mode, the in-process exit logic fires a market close order.
    """

    def __init__(
        self,
        state: MarketState,
        on_trade_closed: Optional[Callable[[dict], None]] = None,
        on_trade_opened: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.state = state
        self._exchange = None
        self._on_trade_closed = on_trade_closed
        self._on_trade_opened = on_trade_opened
        self._pending_entry: Optional[PendingEntry] = None
        self._last_fill_poll: float = 0.0
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

    @property
    def has_pending_entry(self) -> bool:
        return self._pending_entry is not None

    async def enter(self, side: Side) -> bool:
        """Place a post-only limit entry at the best bid/ask. Returns True if the
        order was placed (NOT filled) — the position opens in check_pending_entry."""
        if self.state.position is not None or self._pending_entry is not None:
            return False
        if self.state.last_bid <= 0 or self.state.last_ask <= 0:
            return False

        limit_price = self.state.last_bid if side == Side.LONG else self.state.last_ask
        plan = plan_entry(self.state, side, limit_price)
        if plan is None:
            return False

        if PAPER_MODE or self._exchange is None:
            self._pending_entry = PendingEntry(plan=plan, placed_at=clock.now())
            logger.info(
                "ENTRY PENDING %s limit @ %.2f | size=%.6f BTC | timeout=%ds",
                side.value.upper(), limit_price, plan.size, ENTRY_ORDER_TIMEOUT_SECONDS,
            )
            return True

        try:
            order_side = "buy" if side == Side.LONG else "sell"
            order = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._exchange.create_limit_order(
                    "BTC/USDT", order_side, plan.size, plan.price,
                    params={"timeInForce": "GTX"},  # Binance Futures post-only
                ),
            )
        except Exception:
            logger.exception("Live post-only entry rejected or failed — no trade")
            return False

        self._pending_entry = PendingEntry(plan=plan, placed_at=clock.now(), order_id=order["id"])
        logger.info(
            "ENTRY PENDING (live GTX) %s limit @ %.2f | size=%.6f BTC | id=%s",
            side.value.upper(), plan.price, plan.size, order["id"],
        )
        return True

    def _fill_pending(self, plan: EntryPlan) -> None:
        self._pending_entry = None
        open_planned(self.state, plan, fee_rate=MAKER_FEE_RATE)
        opened = self.state.position
        if self._on_trade_opened is not None and opened is not None:
            self._on_trade_opened({
                "side": opened.side, "entry_price": opened.entry_price,
                "size": opened.size, "stop_loss": opened.stop_loss, "tp1": opened.tp1,
            })

    async def check_pending_entry(self) -> None:
        """Called on every trade tick. Fills or expires the resting entry order."""
        pending = self._pending_entry
        if pending is None:
            return

        live = not (PAPER_MODE or self._exchange is None) and pending.order_id is not None

        if clock.now() - pending.placed_at >= ENTRY_ORDER_TIMEOUT_SECONDS:
            self._pending_entry = None
            if live:
                await self._cancel_live_entry_keeping_partial(pending)
            else:
                logger.info("Entry order timed out unfilled — cancelled")
            return

        if live:
            if clock.now() - self._last_fill_poll < _LIVE_FILL_POLL_SECONDS:
                return
            self._last_fill_poll = clock.now()
            try:
                order = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._exchange.fetch_order(pending.order_id, "BTC/USDT"),
                )
            except Exception:
                logger.exception("fetch_order failed for pending entry %s", pending.order_id)
                return
            if order.get("status") == "closed":
                filled_raw = order.get("filled")
                filled = float(filled_raw) if filled_raw is not None else pending.plan.size
                if filled <= 0:
                    self._pending_entry = None
                    logger.warning(
                        "Entry order %s closed with zero fill — no position opened",
                        pending.order_id,
                    )
                    return
                avg = float(order.get("average") or pending.plan.price)
                self._fill_pending(replace(pending.plan, size=filled, price=avg))
            return

        # Paper/backtest fill model: fill only when a trade prints strictly THROUGH
        # the limit (conservative queue assumption).
        p = self.state.last_price
        plan = pending.plan
        traded_through = (
            (plan.side == Side.LONG and p < plan.price)
            or (plan.side == Side.SHORT and p > plan.price)
        )
        if traded_through:
            self._fill_pending(plan)

    async def _cancel_live_entry_keeping_partial(self, pending: PendingEntry) -> None:
        """Cancel a timed-out live entry; if it was partially filled, keep the
        filled fraction as a (smaller, lower-risk) position."""
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._exchange.cancel_order(pending.order_id, "BTC/USDT"),
            )
            order = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._exchange.fetch_order(pending.order_id, "BTC/USDT"),
            )
        except Exception:
            logger.exception("Cancel/fetch of timed-out entry %s failed — MANUAL CHECK REQUIRED", pending.order_id)
            return
        filled = float(order.get("filled") or 0.0)
        if filled > 0:
            logger.info("Timed-out entry partially filled (%.6f BTC) — keeping the partial", filled)
            self._fill_pending(replace(pending.plan, size=filled))
        else:
            logger.info("Entry order timed out unfilled — cancelled on exchange")

    async def cancel_open_orders(self) -> None:
        """Startup hygiene: a crash can leave an orphan resting entry on the exchange."""
        if self._exchange is None:
            return
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._exchange.cancel_all_orders("BTC/USDT"),
            )
            logger.info("Startup: cancelled all open BTC/USDT orders")
        except Exception:
            logger.exception("Startup cancel_all_orders failed")

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
