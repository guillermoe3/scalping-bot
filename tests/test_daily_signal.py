import pytest

from config import TSMOM_LOOKBACK_DAYS, VOL_TARGET_ANNUALIZED
from daily_signal import objetivo_exposicion
from estudios.nucleo import exposiciones, retornos_diarios, senal_tsmom


def _synthetic_closes(n: int = 120) -> list[float]:
    """Deterministic, non-monotonic walk — no randomness, reproducible."""
    closes = [100.0]
    for i in range(1, n):
        step = 1.0 if (i * 7) % 5 < 3 else -0.8
        closes.append(closes[-1] + step)
    return closes


def test_objetivo_exposicion_matches_estudios_formulas_directly():
    closes = _synthetic_closes(120)

    for cutoff in range(40, len(closes) + 1):
        window = closes[:cutoff]
        got = objetivo_exposicion(window)

        i = len(window) - 1
        s = senal_tsmom(window, i, TSMOM_LOOKBACK_DAYS)
        signal = max(s, 0) if s is not None else 0
        rets = retornos_diarios(window)
        exp_series = exposiciones(rets, VOL_TARGET_ANNUALIZED)
        expected = float(signal) * exp_series[i]

        assert got == pytest.approx(expected), f"mismatch at cutoff={cutoff}"


def test_objetivo_exposicion_zero_before_lookback_fills():
    closes = [100.0 + i for i in range(10)]  # only 10 days; k=14 needs i >= 14

    assert objetivo_exposicion(closes) == 0.0


def test_objetivo_exposicion_zero_when_signal_is_flat_or_down():
    closes = [float(c) for c in range(140, 100, -1)]  # 40 days, strictly declining

    assert objetivo_exposicion(closes) == 0.0


def test_objetivo_exposicion_empty_history_returns_zero():
    assert objetivo_exposicion([]) == 0.0
