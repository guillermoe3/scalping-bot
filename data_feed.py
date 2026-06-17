from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable, Awaitable, List

import websockets
from websockets.exceptions import ConnectionClosed

from config import WS_STREAM_URL, STREAMS
from state import MarketState, Candle, BookSnapshot, OrderBookLevel

logger = logging.getLogger(__name__)

_Handler = Callable[..., Awaitable[None]]


class DataFeed:
    """
    Subscribes to Binance combined stream:
      - aggTrade  → tick-level trades (price, qty, aggressor side)
      - kline_1m/5m/15m → candle events (live + closed)
      - depth20@100ms → order book snapshots

    Emits events via registered async callbacks.
    Handles reconnection with exponential backoff.
    """

    def __init__(self, state: MarketState) -> None:
        self.state = state
        self._trade_handlers: List[_Handler] = []
        self._candle_1m_handlers: List[_Handler] = []
        self._candle_5m_handlers: List[_Handler] = []
        self._candle_15m_handlers: List[_Handler] = []
        self._orderbook_handlers: List[_Handler] = []
        self._running = False
        self._reconnect_delay = 1.0

    # --- Registration ---

    def on_trade(self, fn: _Handler) -> None:
        self._trade_handlers.append(fn)

    def on_candle_1m(self, fn: _Handler) -> None:
        self._candle_1m_handlers.append(fn)

    def on_candle_5m(self, fn: _Handler) -> None:
        self._candle_5m_handlers.append(fn)

    def on_candle_15m(self, fn: _Handler) -> None:
        self._candle_15m_handlers.append(fn)

    def on_orderbook(self, fn: _Handler) -> None:
        self._orderbook_handlers.append(fn)

    # --- Lifecycle ---

    async def connect(self) -> None:
        self._running = True
        url = f"{WS_STREAM_URL}?streams={'/'.join(STREAMS)}"
        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("WebSocket connected to Binance")
                    self._reconnect_delay = 1.0
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._dispatch(json.loads(raw))
            except ConnectionClosed as exc:
                logger.warning("WebSocket closed (%s) — reconnecting in %.1fs", exc, self._reconnect_delay)
            except Exception:
                logger.exception("WebSocket error — reconnecting in %.1fs", self._reconnect_delay)

            if self._running:
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60.0)

    async def stop(self) -> None:
        self._running = False

    # --- Dispatch ---

    async def _dispatch(self, msg: dict) -> None:
        stream: str = msg.get("stream", "")
        data: dict = msg.get("data", msg)

        if "aggTrade" in stream:
            await self._handle_trade(data)
        elif "kline" in stream:
            await self._handle_kline(data)
        elif "depth" in stream:
            await self._handle_depth(data)

    # --- Handlers ---

    async def _handle_trade(self, d: dict) -> None:
        price = float(d["p"])
        qty = float(d["q"])
        is_buyer_maker: bool = d["m"]  # True → sell aggressor (hit bid)
        ts = d["T"] / 1000.0

        self.state.last_price = price
        self._update_live_candles(price, qty)

        # Running CVD: buy aggressor adds, sell aggressor subtracts
        if is_buyer_maker:
            self.state.cvd -= qty
        else:
            self.state.cvd += qty

        await self._emit(self._trade_handlers, price, qty, is_buyer_maker, ts)

    def _update_live_candles(self, price: float, qty: float) -> None:
        for live in (self.state.live_1m, self.state.live_5m, self.state.live_15m):
            if live is not None:
                live.high = max(live.high, price)
                live.low = min(live.low, price)
                live.close = price
                live.volume += qty

    async def _handle_kline(self, d: dict) -> None:
        k = d["k"]
        tf: str = k["i"]
        is_closed: bool = k["x"]

        candle = Candle(
            open=float(k["o"]),
            high=float(k["h"]),
            low=float(k["l"]),
            close=float(k["c"]),
            volume=float(k["v"]),
            timestamp=int(k["t"]),
        )

        if tf == "1m":
            self.state.live_1m = candle
            if is_closed:
                self.state.candles_1m.append(candle)
                self.state.live_1m = None
                await self._emit(self._candle_1m_handlers, candle)
        elif tf == "5m":
            self.state.live_5m = candle
            if is_closed:
                self.state.candles_5m.append(candle)
                self.state.live_5m = None
                await self._emit(self._candle_5m_handlers, candle)
        elif tf == "15m":
            self.state.live_15m = candle
            if is_closed:
                self.state.candles_15m.append(candle)
                self.state.live_15m = None
                await self._emit(self._candle_15m_handlers, candle)

    async def _handle_depth(self, d: dict) -> None:
        bids = [OrderBookLevel(float(b[0]), float(b[1])) for b in d["bids"]]
        asks = [OrderBookLevel(float(a[0]), float(a[1])) for a in d["asks"]]
        snapshot = BookSnapshot(bids=bids, asks=asks, timestamp=time.time())

        self.state.ob_snapshots.append(snapshot)

        if bids and asks:
            self.state.last_bid = bids[0].price
            self.state.last_ask = asks[0].price
            self.state.spread = asks[0].price - bids[0].price

        await self._emit(self._orderbook_handlers, snapshot)

    # --- Helpers ---

    async def _emit(self, handlers: List[_Handler], *args) -> None:
        for h in handlers:
            try:
                await h(*args)
            except Exception:
                logger.exception("Error in handler %s", getattr(h, "__name__", repr(h)))
