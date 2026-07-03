from __future__ import annotations

import csv
from typing import List

BASE_URL = "https://data.binance.vision/data/spot/daily/aggTrades/BTCUSDT"
_MICROSECOND_THRESHOLD = 100_000_000_000_000  # ts mayores que esto vienen en µs


def build_url(day: str) -> str:
    return f"{BASE_URL}/BTCUSDT-aggTrades-{day}.zip"


def parse_agg_trades_csv(fileobj) -> List[list]:
    """Convierte el CSV diario de aggTrades de Binance Vision a filas
    compactas [ts_ms, price, qty, is_sell]. Tolera fila de header
    (algunos dumps la traen) y timestamps en µs (dumps spot desde
    2025-01-01)."""
    rows: List[list] = []
    for rec in csv.reader(fileobj):
        if not rec:
            continue
        try:
            price = float(rec[1])
        except (ValueError, IndexError):
            continue  # fila de header u otra basura
        qty = float(rec[2])
        ts = int(rec[5])
        if ts > _MICROSECOND_THRESHOLD:
            ts //= 1000
        is_sell = rec[6].strip().lower() == "true"
        rows.append([ts, price, qty, is_sell])
    rows.sort(key=lambda r: r[0])
    return rows


import argparse
import io
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

import trade_cache

_MAX_ATTEMPTS = 3


class DayNotAvailable(Exception):
    """El ZIP del día no existe en Binance Vision (HTTP 404)."""


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "scalping-bot-backtest"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise DayNotAvailable(url) from exc
        raise


def download_day(day: str, fetcher=None, sleep=time.sleep) -> str:
    """Baja, convierte y cachea un día. Procesa de a un día por vez para
    mantener acotada la memoria (lección del OOM: nunca más de un día de
    trades en RAM)."""
    if trade_cache.has_day(day):
        return "cached"
    fetch = fetcher if fetcher is not None else _http_get

    payload = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            payload = fetch(build_url(day))
            break
        except DayNotAvailable:
            return "missing"
        except Exception:
            if attempt < _MAX_ATTEMPTS - 1:
                sleep(2 ** attempt)
    if payload is None:
        return "failed"

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        with zf.open(zf.namelist()[0]) as f:
            rows = parse_agg_trades_csv(io.TextIOWrapper(f, encoding="utf-8", newline=""))
    trade_cache.write_day(day, rows)
    return "downloaded"


def _iter_days(start: str, end: str):
    cursor = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    stop = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    while cursor < stop:
        yield cursor.strftime("%Y-%m-%d")
        cursor += timedelta(days=1)


def main(argv=None, fetcher=None) -> int:
    parser = argparse.ArgumentParser(description="Download daily BTCUSDT aggTrades dumps from data.binance.vision into the compact backtest cache.")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (UTC, inclusive)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (UTC, exclusive)")
    args = parser.parse_args(argv)

    counts = {"downloaded": 0, "cached": 0, "missing": 0, "failed": 0}
    for day in _iter_days(args.start, args.end):
        status = download_day(day, fetcher=fetcher)
        counts[status] += 1
        print(f"{day}: {status}")
    print(", ".join(f"{k}: {v}" for k, v in counts.items()))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
