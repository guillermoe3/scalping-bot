from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from typing import List, Optional

CACHE_DIR = "backtest_cache"
BASE_URL = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
_MICROSECOND_THRESHOLD = 100_000_000_000_000
_MAX_ATTEMPTS = 3


class MonthNotAvailable(Exception):
    pass


def build_url(symbol: str, month: str) -> str:
    return f"{BASE_URL}/{symbol}/{symbol}-fundingRate-{month}.zip"


def parse_funding_csv(fileobj) -> List[list]:
    rows: List[list] = []
    for rec in csv.reader(fileobj):
        if not rec:
            continue
        try:
            ts = int(rec[0])
        except ValueError:
            continue  # header row
        rate = float(rec[-1])  # last column is the funding rate in both layouts
        if ts > _MICROSECOND_THRESHOLD:
            ts //= 1000
        rows.append([ts, rate])
    rows.sort(key=lambda r: r[0])
    return rows


def cache_path(symbol: str) -> str:
    return os.path.join(CACHE_DIR, f"{symbol}_funding.json.gz")


def read_funding(symbol: str) -> List[list]:
    path = cache_path(symbol)
    if not os.path.exists(path):
        return []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _write_funding(symbol: str, rows: List[list]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = cache_path(symbol)
    tmp = path + ".tmp"
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(rows, f)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "scalping-bot-backtest"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise MonthNotAvailable(url) from exc
        raise


def _iter_months(start: str, end: str):
    y, m = (int(x) for x in start.split("-"))
    ye, me = (int(x) for x in end.split("-"))
    while (y, m) < (ye, me):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def download_range(symbol: str, start_month: str, end_month: str, fetcher=None, sleep=None) -> dict:
    """One month at a time: fetch, parse, merge into the per-symbol cache,
    write, move on (never more than one month of raw payload in RAM)."""
    fetch = fetcher if fetcher is not None else _http_get
    _sleep = sleep if sleep is not None else time.sleep
    counts = {"downloaded": 0, "missing": 0, "failed": 0}
    for month in _iter_months(start_month, end_month):
        status = "failed"
        for attempt in range(_MAX_ATTEMPTS):
            try:
                payload = fetch(build_url(symbol, month))
                with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                    with zf.open(zf.namelist()[0]) as f:
                        rows = parse_funding_csv(io.TextIOWrapper(f, encoding="utf-8", newline=""))
                merged = {r[0]: r[1] for r in read_funding(symbol)}
                merged.update({r[0]: r[1] for r in rows})
                _write_funding(symbol, [[ts, merged[ts]] for ts in sorted(merged)])
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
    parser = argparse.ArgumentParser(description="Download monthly funding-rate dumps from data.binance.vision into the compact cache.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM (inclusive)")
    parser.add_argument("--end", required=True, help="YYYY-MM (exclusive)")
    args = parser.parse_args(argv)
    counts = download_range(args.symbol, args.start, args.end, fetcher=fetcher)
    print(", ".join(f"{k}: {v}" for k, v in counts.items()))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
