"""Shared core for the pre-registered base-rate studies.

Provides cached-data loading, the locked verification window, and the small
statistical helpers (forward return, rolling percentile, summary stats) that
each study builds on. stdlib only.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
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
    """Forward return from bar i to bar i + horizonte_barras, or None if out of range.

    Caller's responsibility: i must be a valid non-negative index into closes.
    """
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
    Caller's responsibility: i must be a valid index into valores (i <= len).
    """
    if i < ventana_n:
        return None
    previos = valores[i - ventana_n : i]
    return sum(1 for v in previos if v < valor) / ventana_n


def resumen(muestras: list[float]) -> dict:
    """Summary stats for a list of samples: count, mean, median, hit rate (> 0).

    Empty input yields {"n": 0, "media": None, "mediana": None, "hit_rate": None}
    so studies can report empty cells without crashing.
    """
    n = len(muestras)
    if n == 0:
        return {"n": 0, "media": None, "mediana": None, "hit_rate": None}
    return {
        "n": n,
        "media": statistics.fmean(muestras),
        "mediana": statistics.median(muestras),
        "hit_rate": sum(1 for m in muestras if m > 0) / n,
    }


# --- Daily-strategy metrics (M-cycle, spec 2026-07-15) ---

CORTE_MOMENTUM_MS = 1704067200000  # 2024-01-01T00:00:00Z


def senal_tsmom(closes: list[float], i: int, k: int) -> Optional[int]:
    """Sign of the k-day return ending at i; None without a full lookback."""
    if i < k:
        return None
    if closes[i] > closes[i - k]:
        return 1
    if closes[i] < closes[i - k]:
        return -1
    return 0


def ratio_ma(closes: list[float], i: int, n: int) -> Optional[float]:
    """closes[i] over the n-day simple moving average ending at i."""
    if i < n - 1:
        return None
    ma = statistics.fmean(closes[i - n + 1 : i + 1])
    return closes[i] / ma if ma > 0 else None


def retornos_diarios(closes: list[float]) -> list[float]:
    """Simple daily returns, same length as closes (day 0 has no return -> 0.0)."""
    rets = [0.0]
    for t in range(1, len(closes)):
        rets.append(closes[t] / closes[t - 1] - 1.0)
    return rets


def serie_estrategia(retornos: list[float], posiciones: list[float]) -> list[float]:
    """r_strat[t-1] = posiciones[t-1] * retornos[t] (no lookahead by construction)."""
    if len(retornos) != len(posiciones):
        raise ValueError("retornos and posiciones must be aligned")
    return [posiciones[t - 1] * retornos[t] for t in range(1, len(retornos))]


def sharpe_anualizado(rets: list[float]) -> Optional[float]:
    if len(rets) < 2:
        return None
    sd = statistics.stdev(rets)
    if sd == 0:
        return None
    return statistics.fmean(rets) / sd * math.sqrt(365)


def max_drawdown(rets: list[float]) -> float:
    """Peak-to-trough drop of the compounded equity curve (0.2 means -20%)."""
    equity = peak = 1.0
    worst = 0.0
    for r in rets:
        equity *= 1.0 + r
        peak = max(peak, equity)
        worst = max(worst, 1.0 - equity / peak)
    return worst


def peor_mes(ts_list: list[int], rets: list[float]) -> Optional[float]:
    """Worst compounded calendar-month (UTC) return; ts_list[i] is rets[i]'s day."""
    if not rets or len(ts_list) != len(rets):
        return None
    por_mes: dict = {}
    for ts, r in zip(ts_list, rets):
        d = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        clave = (d.year, d.month)
        por_mes[clave] = por_mes.get(clave, 1.0) * (1.0 + r)
    return min(v - 1.0 for v in por_mes.values())


def metricas_estrategia(retornos: list[float], posiciones: list[float],
                        eval_desde: int = 0) -> dict:
    """Adoption metrics of a daily-rebalanced strategy from day max(1, eval_desde)."""
    idx0 = max(1, eval_desde)
    r_full = serie_estrategia(retornos, posiciones)  # r_full[t-1] is day t
    r_strat = r_full[idx0 - 1:]
    en_pos = [r_full[t - 1] for t in range(idx0, len(retornos))
              if posiciones[t - 1] != 0.0]
    return {
        "n_dias": len(r_strat),
        "n_dias_en_posicion": len(en_pos),
        "sharpe": sharpe_anualizado(r_strat),
        "max_drawdown": max_drawdown(r_strat),
        "media": statistics.fmean(r_strat) if r_strat else None,
        "mediana_en_posicion": statistics.median(en_pos) if en_pos else None,
    }


def metricas_buy_and_hold(retornos: list[float], eval_desde: int = 0) -> dict:
    idx0 = max(1, eval_desde)
    bh = retornos[idx0:]
    return {
        "n_dias": len(bh),
        "sharpe": sharpe_anualizado(bh),
        "max_drawdown": max_drawdown(bh),
        "media": statistics.fmean(bh) if bh else None,
    }


# --- Hysteresis-band study (signal-design cycle, spec 2026-07-16) ---

CORTE_HISTERESIS_MS = 1751328000000  # 2025-07-01T00:00:00Z


def cambios_de_posicion(posiciones: list[float]) -> int:
    """Count of days where the position differs from the previous day's."""
    return sum(
        1 for t in range(1, len(posiciones)) if posiciones[t] != posiciones[t - 1]
    )
