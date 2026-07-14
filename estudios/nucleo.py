"""Shared core for the pre-registered base-rate studies.

Provides cached-data loading, the locked verification window, and the small
statistical helpers (forward return, rolling percentile, summary stats) that
each study builds on. stdlib only.
"""

from __future__ import annotations

import statistics
from typing import Optional

import funding_history
import klines_history

CORTE_VERIFICACION_MS = 1735689600000  # 2025-01-01T00:00:00Z


def cargar_klines(symbol: str, start_month: str, end_month: str) -> list[list]:
    """Concatenate cached monthly klines for `symbol` over [start_month, end_month).

    Raises ValueError if any month in the range is not cached.
    """
    rows: list = []
    for month in funding_history._iter_months(start_month, end_month):
        month_rows = klines_history.read_month(symbol, month)
        if month_rows is None:
            raise ValueError(f"missing cached month {symbol} {month}")
        rows.extend(month_rows)
    return rows


def ventana(
    rows: list[list],
    modo: str,
    corte_ms: int = CORTE_VERIFICACION_MS,
    verificacion_habilitada: bool = False,
) -> list[list]:
    """Split rows by the calibration/verification boundary.

    modo "calibracion": rows with ts < corte_ms (fair game, always allowed).
    modo "verificacion": rows with ts >= corte_ms; locked unless
    verificacion_habilitada=True, so held-out data can't be peeked at by
    accident.
    """
    if modo == "calibracion":
        return [r for r in rows if r[0] < corte_ms]
    if modo == "verificacion":
        if not verificacion_habilitada:
            raise ValueError(
                "verification window is locked; run with --verificacion"
            )
        return [r for r in rows if r[0] >= corte_ms]
    raise ValueError(f"unknown modo: {modo}")


def retorno_forward(closes: list[float], i: int, horizonte_barras: int) -> Optional[float]:
    """Forward return from bar i to bar i + horizonte_barras, or None if out of range."""
    j = i + horizonte_barras
    if j < 0 or j >= len(closes):
        return None
    return (closes[j] - closes[i]) / closes[i]


def percentil_rodante(
    valores: list[float], i: int, ventana_n: int, valor: float
) -> Optional[float]:
    """Fraction of the ventana_n observations immediately preceding i that are < valor.

    No lookahead: the window is valores[i - ventana_n : i], excluding position i.
    Returns None if there aren't ventana_n prior observations.
    """
    if i < ventana_n:
        return None
    previos = valores[i - ventana_n : i]
    return sum(1 for v in previos if v < valor) / ventana_n


def resumen(muestras: list[float]) -> dict:
    """Summary stats for a list of samples: count, mean, median, hit rate (> 0)."""
    n = len(muestras)
    return {
        "n": n,
        "media": statistics.fmean(muestras),
        "mediana": statistics.median(muestras),
        "hit_rate": sum(1 for m in muestras if m > 0) / n,
    }
