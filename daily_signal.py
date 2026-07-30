from __future__ import annotations

from typing import List

from config import TSMOM_LOOKBACK_DAYS, VOL_TARGET_ANNUALIZED
from estudios.nucleo import exposiciones, retornos_diarios, senal_tsmom


def objetivo_exposicion(closes: List[float]) -> float:
    """Target long_flat exposure (0.0-1.0) for the period starting right
    after the last close in `closes`, decided at that close — same timing
    convention as the M1/M3 studies (senal_tsmom + exposiciones)."""
    i = len(closes) - 1
    if i < 0:
        return 0.0

    s = senal_tsmom(closes, i, TSMOM_LOOKBACK_DAYS)
    if not s or s <= 0:
        return 0.0

    rets = retornos_diarios(closes)
    exp_series = exposiciones(rets, VOL_TARGET_ANNUALIZED)
    return exp_series[i]
