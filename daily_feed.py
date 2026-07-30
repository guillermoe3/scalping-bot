from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed

import clock
from config import DAILY_WS_STREAM, WS_STREAM_URL
from daily_state import DailyClose, DailyState, append_close

logger = logging.getLogger(__name__)

_Handler = Callable[[DailyClose], Awaitable[None]]
_ONE_DAY_MS = 86_400_000


class DailyDataFeed:
    """Subscribes to Binance spot's daily-kline stream and emits one event
    per closed UTC day. Handles reconnection with exponential backoff —
    same pattern as data_feed.DataFeed."""

    def __init__(self, state: DailyState) -> None:
        self.state = state
        self._candle_handlers: List[_Handler] = []
        self._running = False
        self._reconnect_delay = 1.0

    def on_candle_1d(self, fn: _Handler) -> None:
        self._candle_handlers.append(fn)

    async def connect(self) -> None:
        self._running = True
        url = f"{WS_STREAM_URL}?streams={DAILY_WS_STREAM}"
        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("Daily WebSocket connected to Binance")
                    self._reconnect_delay = 1.0
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._dispatch(json.loads(raw))
            except ConnectionClosed as exc:
                logger.warning("Daily WebSocket closed (%s) — reconnecting in %.1fs", exc, self._reconnect_delay)
            except Exception:
                logger.exception("Daily WebSocket error — reconnecting in %.1fs", self._reconnect_delay)

            if self._running:
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60.0)

    async def stop(self) -> None:
        self._running = False

    async def _dispatch(self, msg: dict) -> None:
        data = msg.get("data", msg)
        k = data.get("k")
        if k is None or not k.get("x"):
            return  # only closed daily candles matter — the signal is decided once a day
        candle = DailyClose(timestamp=int(k["t"]), close=float(k["c"]))
        append_close(self.state, candle.timestamp, candle.close)
        await self._emit(candle)

    async def _emit(self, candle: DailyClose) -> None:
        for h in self._candle_handlers:
            try:
                await h(candle)
            except Exception:
                logger.exception("Error in daily candle handler %s", getattr(h, "__name__", repr(h)))


def _public_spot_exchange():
    import ccxt
    return ccxt.binance({"options": {"defaultType": "spot"}, "enableRateLimit": True})


def backfill(state: DailyState, exchange: Optional[object] = None, limit: int = 100) -> None:
    """Startup only: fetches the last `limit` daily candles via REST (public
    endpoint — no API keys needed) and seeds state.closes, so the k=14
    lookback and 30-day vol window are populated immediately instead of
    waiting weeks. Drops Binance's still-forming current-day candle."""
    state.closes.clear()
    ex = exchange if exchange is not None else _public_spot_exchange()
    rows = ex.fetch_ohlcv("BTC/USDT", timeframe="1d", limit=limit)
    rows = sorted(rows, key=lambda r: r[0])
    now_ms = clock.now() * 1000.0
    for ts, _o, _h, _l, close, _v in rows:
        if ts + _ONE_DAY_MS > now_ms:
            continue  # still forming — wait for the close event instead
        append_close(state, int(ts), float(close))
