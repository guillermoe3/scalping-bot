from __future__ import annotations

import json
import os
from typing import Awaitable, Callable, List, Optional

import clock
from config import BACKTEST_SYNTHETIC_SPREAD_PCT
from data_feed import update_live_candles
from state import Candle, MarketState

CACHE_DIR = "backtest_cache"

_Handler = Callable[..., Awaitable[None]]


def _cache_path(symbol: str, kind: str, start_ms: int, end_ms: int) -> str:
    safe_symbol = symbol.replace("/", "")
    return os.path.join(CACHE_DIR, f"{safe_symbol}_{kind}_{start_ms}_{end_ms}.json")


def _read_cache(path: str) -> Optional[list]:
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def _write_cache(path: str, data: list) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f)
    os.replace(tmp_path, path)


def fetch_klines_1m(exchange, symbol: str, start_ms: int, end_ms: int, use_cache: bool = True) -> List[list]:
    """Returns [timestamp_ms, open, high, low, close, volume] rows covering [start_ms, end_ms)."""
    path = _cache_path(symbol, "klines1m", start_ms, end_ms)
    if use_cache:
        cached = _read_cache(path)
        if cached is not None:
            return cached

    candles: List[list] = []
    since = start_ms
    while since < end_ms:
        batch = exchange.fetch_ohlcv(symbol, "1m", since=since, limit=1000)
        if not batch:
            break
        candles.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= since:
            break
        since = last_ts + 60_000

    candles = [c for c in candles if start_ms <= c[0] < end_ms]

    if use_cache:
        _write_cache(path, candles)
    return candles


def fetch_trades(exchange, symbol: str, start_ms: int, end_ms: int, use_cache: bool = True) -> List[dict]:
    """Returns ccxt-normalized trade dicts covering [start_ms, end_ms)."""
    path = _cache_path(symbol, "trades", start_ms, end_ms)
    if use_cache:
        cached = _read_cache(path)
        if cached is not None:
            return cached

    trades: List[dict] = []
    since = start_ms
    while since < end_ms:
        batch = exchange.fetch_trades(symbol, since=since, limit=1000)
        if not batch:
            break
        trades.extend(batch)
        last_ts = batch[-1]["timestamp"]
        if last_ts <= since:
            break
        since = last_ts + 1

    trades = [t for t in trades if start_ms <= t["timestamp"] < end_ms]

    if use_cache:
        _write_cache(path, trades)
    return trades


def resample(klines_1m: List[list], minutes: int) -> List[list]:
    """Aggregates 1m klines ([ts, o, h, l, c, v]) into `minutes`-minute
    buckets aligned to UTC minute-of-day boundaries — mathematically
    identical to what Binance's own 5m/15m klines would report, since 1m
    boundaries are a superset of every coarser grid."""
    if not klines_1m:
        return []

    bucket_ms = minutes * 60_000
    out: List[list] = []
    current_bucket_start: Optional[int] = None
    current: Optional[list] = None

    for ts, o, h, l, c, v in klines_1m:
        bucket_start = (ts // bucket_ms) * bucket_ms
        if bucket_start != current_bucket_start:
            if current is not None:
                out.append(current)
            current = [bucket_start, o, h, l, c, v]
            current_bucket_start = bucket_start
        else:
            current[2] = max(current[2], h)
            current[3] = min(current[3], l)
            current[4] = c
            current[5] += v

    if current is not None:
        out.append(current)

    return out


def _build_event_timeline(trades: List[dict], klines_1m: List[list], klines_5m: List[list], klines_15m: List[list]) -> List[dict]:
    events: List[dict] = []

    for t in trades:
        events.append({"type": "trade", "ts": t["timestamp"], "price": t["price"], "amount": t["amount"], "side": t["side"]})

    for klines, timeframe, period_ms in ((klines_1m, "1m", 60_000), (klines_5m, "5m", 5 * 60_000), (klines_15m, "15m", 15 * 60_000)):
        for ts, o, h, l, c, v in klines:
            events.append({
                "type": "candle_close", "ts": ts + period_ms, "timeframe": timeframe,
                "candle": Candle(open=o, high=h, low=l, close=c, volume=v, timestamp=ts),
            })

    events.sort(key=lambda e: (e["ts"], e["type"] == "candle_close"))
    return events


class BacktestFeed:
    """Replays historical Binance data (klines + real trades, via ccxt)
    through the same on_trade/on_candle_1m/5m/15m registration interface
    DataFeed exposes live, so main.wire_strategy works unchanged against
    either one."""

    def __init__(
        self,
        state: MarketState,
        exchange=None,
        spread_pct: float = BACKTEST_SYNTHETIC_SPREAD_PCT,
        use_cache: bool = True,
    ) -> None:
        self.state = state
        self._exchange = exchange if exchange is not None else _build_exchange()
        self._spread_pct = spread_pct
        self._use_cache = use_cache
        self._trade_handlers: List[_Handler] = []
        self._candle_1m_handlers: List[_Handler] = []
        self._candle_5m_handlers: List[_Handler] = []
        self._candle_15m_handlers: List[_Handler] = []
        self._bucket_1m: Optional[int] = None
        self._bucket_5m: Optional[int] = None
        self._bucket_15m: Optional[int] = None

    def on_trade(self, fn: _Handler) -> None:
        self._trade_handlers.append(fn)

    def on_candle_1m(self, fn: _Handler) -> None:
        self._candle_1m_handlers.append(fn)

    def on_candle_5m(self, fn: _Handler) -> None:
        self._candle_5m_handlers.append(fn)

    def on_candle_15m(self, fn: _Handler) -> None:
        self._candle_15m_handlers.append(fn)

    async def replay(self, start_ms: int, end_ms: int) -> None:
        klines_1m = fetch_klines_1m(self._exchange, "BTC/USDT", start_ms, end_ms, self._use_cache)
        if not klines_1m:
            raise ValueError(f"No historical data available for BTC/USDT between {start_ms} and {end_ms}")
        klines_5m = resample(klines_1m, 5)
        klines_15m = resample(klines_1m, 15)
        trades = fetch_trades(self._exchange, "BTC/USDT", start_ms, end_ms, self._use_cache)

        for event in _build_event_timeline(trades, klines_1m, klines_5m, klines_15m):
            clock.set_now(event["ts"] / 1000.0)
            if event["type"] == "trade":
                await self._handle_trade(event)
            else:
                await self._handle_candle_close(event)

    def _ensure_live_candle(self, live_attr: str, bucket_attr: str, ts_ms: int, bucket_size_ms: int, price: float) -> None:
        bucket_start = (ts_ms // bucket_size_ms) * bucket_size_ms
        if getattr(self, bucket_attr) != bucket_start:
            setattr(self.state, live_attr, Candle(open=price, high=price, low=price, close=price, volume=0.0, timestamp=bucket_start))
            setattr(self, bucket_attr, bucket_start)

    async def _handle_trade(self, event: dict) -> None:
        price = event["price"]
        qty = event["amount"]
        ts_ms = event["ts"]

        self._ensure_live_candle("live_1m", "_bucket_1m", ts_ms, 60_000, price)
        self._ensure_live_candle("live_5m", "_bucket_5m", ts_ms, 5 * 60_000, price)
        self._ensure_live_candle("live_15m", "_bucket_15m", ts_ms, 15 * 60_000, price)

        self.state.last_price = price
        spread = price * self._spread_pct
        self.state.last_bid = price - spread / 2
        self.state.last_ask = price + spread / 2
        self.state.spread = spread

        is_sell_aggressor = event["side"] == "sell"
        if is_sell_aggressor:
            self.state.cvd -= qty
        else:
            self.state.cvd += qty

        update_live_candles(self.state, price, qty)

        await self._emit(self._trade_handlers, price, qty, is_sell_aggressor, ts_ms / 1000.0)

    async def _handle_candle_close(self, event: dict) -> None:
        candle = event["candle"]
        tf = event["timeframe"]
        if tf == "1m":
            self.state.candles_1m.append(candle)
            self.state.live_1m = None
            await self._emit(self._candle_1m_handlers, candle)
        elif tf == "5m":
            self.state.candles_5m.append(candle)
            self.state.live_5m = None
            await self._emit(self._candle_5m_handlers, candle)
        else:
            self.state.candles_15m.append(candle)
            self.state.live_15m = None
            await self._emit(self._candle_15m_handlers, candle)

    async def _emit(self, handlers: List[_Handler], *args) -> None:
        for h in handlers:
            await h(*args)


def _build_exchange():
    import ccxt
    return ccxt.binance({"enableRateLimit": True})
