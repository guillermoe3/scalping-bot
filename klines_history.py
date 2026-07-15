from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import sys
import time
import zipfile
from typing import List, Optional

from funding_history import MonthNotAvailable, _http_get, _iter_months

CACHE_DIR = "backtest_cache"
BASE_URL = "https://data.binance.vision/data/futures/um/monthly/klines"
_MICROSECOND_THRESHOLD = 100_000_000_000_000
_MAX_ATTEMPTS = 3


def build_url(symbol: str, month: str) -> str:
    return f"{BASE_URL}/{symbol}/15m/{symbol}-15m-{month}.zip"


def parse_klines_csv(fileobj) -> List[list]:
    rows: List[list] = []
    for rec in csv.reader(fileobj):
        if not rec:
            continue
        try:
            ts = int(rec[0])
        except ValueError:
            continue  # header row
        if ts > _MICROSECOND_THRESHOLD:
            ts //= 1000
        rows.append([ts, float(rec[1]), float(rec[2]), float(rec[3]),
                     float(rec[4]), float(rec[5]), float(rec[9])])
    rows.sort(key=lambda r: r[0])
    return rows


def month_cache_path(symbol: str, month: str) -> str:
    return os.path.join(CACHE_DIR, f"{symbol}_klines15m_{month}.json.gz")


def read_month(symbol: str, month: str) -> Optional[List[list]]:
    path = month_cache_path(symbol, month)
    if not os.path.exists(path):
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _write_month(symbol: str, month: str, rows: List[list]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = month_cache_path(symbol, month)
    tmp = path + ".tmp"
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(rows, f)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def download_range(symbol: str, start_month: str, end_month: str, fetcher=None, sleep=None) -> dict:
    """One month at a time: fetch, parse, write to that month's own cache
    file, move on. Months already cached are skipped without a request."""
    fetch = fetcher if fetcher is not None else _http_get
    _sleep = sleep if sleep is not None else time.sleep
    counts = {"downloaded": 0, "cached": 0, "missing": 0, "failed": 0}
    for month in _iter_months(start_month, end_month):
        if read_month(symbol, month) is not None:
            counts["cached"] += 1
            print(f"{symbol} {month}: cached")
            continue
        status = "failed"
        for attempt in range(_MAX_ATTEMPTS):
            try:
                payload = fetch(build_url(symbol, month))
                with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                    with zf.open(zf.namelist()[0]) as f:
                        rows = parse_klines_csv(io.TextIOWrapper(f, encoding="utf-8", newline=""))
                _write_month(symbol, month, rows)
                status = "downloaded"
                break
            except MonthNotAvailable:
                status = "missing"
                break
            except Exception:
                if attempt < _MAX_ATTEMPTS - 1:
                    _sleep(2 ** attempt)
        counts[status] += 1
        print(f"{symbol} {month}: {status}")
    return counts


def main(argv=None, fetcher=None) -> int:
    parser = argparse.ArgumentParser(description="Download monthly 15m klines dumps from data.binance.vision into a per-month compact cache.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM (inclusive)")
    parser.add_argument("--end", required=True, help="YYYY-MM (exclusive)")
    args = parser.parse_args(argv)
    counts = download_range(args.symbol, args.start, args.end, fetcher=fetcher)
    print(", ".join(f"{k}: {v}" for k, v in counts.items()))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
