from __future__ import annotations

import json
import os
from typing import List, Optional

CACHE_DIR = "backtest_cache"


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
