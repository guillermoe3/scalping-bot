from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timezone
from typing import List, Optional

CACHE_DIR = "backtest_cache"


def day_str(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")


def day_path(day: str) -> str:
    return os.path.join(CACHE_DIR, f"BTCUSDT_aggtrades_{day}.json.gz")


def has_day(day: str) -> bool:
    return os.path.exists(day_path(day))


def read_day(day: str) -> Optional[List[list]]:
    path = day_path(day)
    if not os.path.exists(path):
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def write_day(day: str, rows: List[list]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = day_path(day)
    tmp_path = path + ".tmp"
    try:
        with gzip.open(tmp_path, "wt", encoding="utf-8") as f:
            json.dump(rows, f)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
