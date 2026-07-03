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
