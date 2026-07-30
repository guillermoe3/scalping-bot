# Integración TSMOM k=14 al bot en vivo (paper trading) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the TSMOM k=14 long_flat + vol-targeting (σ_target=0.40) daily
momentum signal — already validated in `backtest_runs/estudios/veredicto-momentum-2026-07.md`
and `veredicto-histeresis-2026-07.md` — from research into the live bot,
replacing the scalping strategy, running in **paper trading** against
Binance spot market data.

**Architecture:** Nine small, focused modules parallel to the existing
scalping code (`daily_state.py`, `daily_signal.py`, `daily_safety.py`,
`daily_execution.py`, `daily_feed.py`), extending `estudios/nucleo.py` and
`notifications.py`, and rewiring `main.py`'s `run()` to use them. The signal
itself is never reimplemented — `daily_signal.py` calls
`estudios.nucleo.senal_tsmom` and `estudios.nucleo.exposiciones` directly, so
the code running live is the same code that was validated. The existing
scalping modules (`signals.py`, `regime.py`, `order_flow.py`,
`indicators.py`, `momentum.py`, `execution.py`, `risk.py`, `state.py`,
`safety.py`, `data_feed.py`) are left completely untouched and stay wired
into `main.py: wire_strategy` (unused by `run()`, but intact and tested) —
they are dormant, not deleted.

**Tech Stack:** Python stdlib, `websockets`, `ccxt`, `pytest` — all already
project dependencies. No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-30-integracion-tsmom-vivo-design.md` — every task in this plan implements a section of that spec.
- BTCUSDT spot only (per the spec's adoption scope — M1's adopt/veto criterion only ever applied to BTC).
- No leverage, no shorting (long_flat: exposure is always in `[0.0, 1.0]`).
- σ_target = 0.40 annualized, TSMOM lookback = 14 days, rebalance band = 10 percentage points, drawdown circuit breaker = 50% from peak equity — exact values fixed by the spec, not re-derived here.
- Fail-closed on ambiguity: an exchange call that fails or a state mismatch aborts the process (`sys.exit(1)`) rather than guessing — same principle already used throughout `safety.py`.
- Do not modify `signals.py`, `regime.py`, `order_flow.py`, `indicators.py`, `momentum.py`, `execution.py`, `risk.py`, `state.py`, `safety.py`, `data_feed.py`, or their tests. `main.py`'s existing `wire_strategy` function and its imports must remain unchanged and `tests/test_main.py` must keep passing without modification.
- Test style: plain `pytest`, no `pytest-asyncio` — async code is exercised with `asyncio.run(...)` inline (see `tests/test_execution.py`, `tests/test_notifications.py`). Fake exchanges are small hand-written classes exposing only the methods used (see `_FakeBalanceExchange` in `tests/test_safety.py`), not a mocking library.
- Money/size fields are plain `float`, rounding only where the existing codebase already rounds (`risk.py` rounds BTC size to 6 decimals) — match that precision in `daily_execution.py`.

---

### Task 1: Extract the vol-targeting exposure formula into `estudios/nucleo.py`

**Files:**
- Modify: `estudios/nucleo.py`
- Modify: `estudios/estudio_vol_overlay.py`
- Test: `tests/test_estudios_nucleo.py`, `tests/test_estudio_vol_overlay.py` (existing tests only — no new ones; this task changes zero behavior)

**Interfaces:**
- Produces: `estudios.nucleo.VENTANA_SIGMA: int`, `estudios.nucleo.exposiciones(rets: list[float], sigma_target: float) -> list[float]` — consumed by Task 4 (`daily_signal.py`).

This is a pure relocation: the live bot needs the exact same exposure
formula the M3 study validated, and today it lives inside
`estudios/estudio_vol_overlay.py`, a study-runner script, not a shared
module. Moving it next to `senal_tsmom` in `estudios/nucleo.py` (already the
shared core for both studies and — after this plan — the live bot) means
both call sites import from one place. No logic changes.

- [ ] **Step 1: Run the existing tests to confirm the baseline is green**

Run: `pytest tests/test_estudios_nucleo.py tests/test_estudio_vol_overlay.py -v`
Expected: all PASS (this is the safety net for the move — same tests must pass unchanged after Step 2)

- [ ] **Step 2: Move `VENTANA_SIGMA` and `exposiciones` into `estudios/nucleo.py`**

Add to `estudios/nucleo.py`, after the `cambios_de_posicion` function at the
end of the file:

```python
# --- Vol-targeting overlay (M3 study + live daily strategy) ---

VENTANA_SIGMA = 30


def exposiciones(rets: list[float], sigma_target: float) -> list[float]:
    """Volatility-targeted exposure decided at the close of each day."""
    out: list[float] = []
    for t in range(len(rets)):
        if t < VENTANA_SIGMA:
            out.append(0.0)
            continue
        sd = statistics.stdev(rets[t - VENTANA_SIGMA + 1 : t + 1]) * math.sqrt(365)
        out.append(min(1.0, sigma_target / sd) if sd > 0 else 0.0)
    return out
```

`estudios/nucleo.py` already imports `math` and `statistics` at the top of
the file (used by `sharpe_anualizado` and `resumen`) — no new imports
needed there.

Now edit `estudios/estudio_vol_overlay.py`: remove the local `VENTANA_SIGMA`
and `exposiciones` definitions (lines 19–38 in the current file, from
`SIGMA_TARGETS = (0.20, 0.30, 0.40)`'s preceding `VENTANA_SIGMA = 30` through
the end of `exposiciones`'s body — keep `SIGMA_TARGETS`, it's study-CLI-only
and unrelated), and replace the top-of-file imports:

```python
from __future__ import annotations

import argparse
import sys
from typing import List

from estudios import estudio_ma, estudio_momentum
from estudios.nucleo import (
    exposiciones,
    metricas_estrategia,
    peor_mes,
    retornos_diarios,
    serie_estrategia,
)
from estudios.reporte import escribir_reporte

SIGMA_TARGETS = (0.20, 0.30, 0.40)

PREREGISTRO = {
    ...  # unchanged, keep as-is
```

(`math` and `statistics` are no longer used anywhere else in this file —
remove both imports. `VENTANA_SIGMA` is no longer referenced inside this
file's own code, only re-exported by the `from estudios.nucleo import`
above for anything that still does `from estudios.estudio_vol_overlay import
VENTANA_SIGMA` — see Step 3.)

Because `estudio_vol_overlay.py` still does
`from estudios.nucleo import exposiciones`, it needs `VENTANA_SIGMA`
available under its own name too for `tests/test_estudio_vol_overlay.py`
(`from estudios.estudio_vol_overlay import VENTANA_SIGMA, exposiciones`) to
keep working unmodified — add it to the same import line:

```python
from estudios.nucleo import (
    VENTANA_SIGMA,
    exposiciones,
    metricas_estrategia,
    peor_mes,
    retornos_diarios,
    serie_estrategia,
)
```

- [ ] **Step 3: Run the tests again to confirm nothing broke**

Run: `pytest tests/test_estudios_nucleo.py tests/test_estudio_vol_overlay.py -v`
Expected: all PASS, identical to Step 1 — the move changed zero behavior.

- [ ] **Step 4: Run the full test suite as an extra safety net**

Run: `pytest -q`
Expected: PASS (same pass count as before this task, since no behavior changed anywhere)

- [ ] **Step 5: Commit**

```bash
git add estudios/nucleo.py estudios/estudio_vol_overlay.py
git commit -m "$(cat <<'EOF'
Move the vol-targeting exposure formula into estudios/nucleo.py

Pure relocation, no behavior change — the live TSMOM integration
(Task 4) needs to import the exact same formula the M3 study
validated, and estudios/nucleo.py is already the shared core both
studies and the live bot import from.
EOF
)"
```

---

### Task 2: Config constants for the daily strategy

**Files:**
- Modify: `config.py`
- Test: none (pure constants; exercised indirectly by every later task's tests)

**Interfaces:**
- Produces: `TSMOM_LOOKBACK_DAYS`, `TSMOM_VARIANTE`, `VOL_TARGET_ANNUALIZED`, `REBALANCE_BAND_PCT`, `DRAWDOWN_CIRCUIT_BREAKER_PCT`, `DAILY_STATE_FILE_PATH`, `DAILY_CLOSES_BUFFER`, `SPOT_TAKER_FEE_RATE`, `DAILY_WS_STREAM` — consumed by Tasks 3–9.

- [ ] **Step 1: Add the constants to `config.py`**

Append to the end of `config.py`:

```python

# --- Daily TSMOM strategy (live paper-trading integration, spec 2026-07-30) ---
TSMOM_LOOKBACK_DAYS = 14
TSMOM_VARIANTE = "long_flat"       # the only variant implemented — documents scope, not branched on
VOL_TARGET_ANNUALIZED = 0.40       # M3: adopted value with the better Sharpe of the two that passed
REBALANCE_BAND_PCT = 0.10          # exposure must move this many points before a spot trade fires
DRAWDOWN_CIRCUIT_BREAKER_PCT = 0.50  # drawdown from peak equity that forces flat + blocks entries
DAILY_STATE_FILE_PATH = "daily_safety_state.json"
DAILY_CLOSES_BUFFER = 400          # days of history kept in memory (lookback 14d + vol window 30d + margin)
SPOT_TAKER_FEE_RATE = 0.0010       # Binance Spot, no BNB discount — market orders only (see daily_execution.py)
DAILY_WS_STREAM = "btcusdt@kline_1d"  # same WS_STREAM_URL base as the scalping feed (Binance spot)
```

- [ ] **Step 2: Sanity check — the module still imports cleanly**

Run: `python -c "import config; print(config.VOL_TARGET_ANNUALIZED, config.DAILY_WS_STREAM)"`
Expected: `0.4 btcusdt@kline_1d`

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "Add config constants for the live TSMOM daily strategy"
```

---

### Task 3: `daily_state.py` — state and balance/exposure helpers

**Files:**
- Create: `daily_state.py`
- Test: `tests/test_daily_state.py`

**Interfaces:**
- Consumes: `config.DAILY_CLOSES_BUFFER`
- Produces: `DailyClose` (dataclass: `timestamp: int`, `close: float`), `DailyState` (dataclass: `closes: deque[DailyClose]`, `btc_balance: float`, `usdt_balance: float`, `equity_peak_usdt: float`, `breaker_active: bool`, `last_rebalance_date: Optional[str]`), `append_close(state, timestamp: int, close: float) -> None`, `close_values(state) -> list[float]`, `current_equity_usdt(state, last_price: float) -> float`, `current_exposure_pct(state, last_price: float) -> float` — consumed by Tasks 4–9.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_daily_state.py`:

```python
import pytest

from config import DAILY_CLOSES_BUFFER
from daily_state import DailyState, append_close, close_values, current_equity_usdt, current_exposure_pct


def test_append_close_adds_to_history():
    state = DailyState()

    append_close(state, timestamp=1000, close=50000.0)

    assert close_values(state) == [50000.0]


def test_append_close_respects_maxlen():
    state = DailyState()

    for i in range(DAILY_CLOSES_BUFFER + 10):
        append_close(state, timestamp=i, close=float(i))

    assert len(state.closes) == DAILY_CLOSES_BUFFER
    assert close_values(state)[0] == 10.0  # the oldest 10 entries were trimmed
    assert close_values(state)[-1] == float(DAILY_CLOSES_BUFFER + 9)


def test_current_equity_usdt_sums_cash_and_btc_value():
    state = DailyState(usdt_balance=1000.0, btc_balance=0.02)

    assert current_equity_usdt(state, last_price=50000.0) == pytest.approx(2000.0)


def test_current_exposure_pct_fraction_in_btc():
    state = DailyState(usdt_balance=1000.0, btc_balance=0.02)

    assert current_exposure_pct(state, last_price=50000.0) == pytest.approx(0.5)


def test_current_exposure_pct_zero_when_equity_is_zero():
    state = DailyState()

    assert current_exposure_pct(state, last_price=50000.0) == 0.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_daily_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'daily_state'`

- [ ] **Step 3: Write `daily_state.py`**

```python
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional

from config import DAILY_CLOSES_BUFFER


@dataclass
class DailyClose:
    timestamp: int  # UTC daily candle open time, ms
    close: float


@dataclass
class DailyState:
    closes: deque = field(default_factory=lambda: deque(maxlen=DAILY_CLOSES_BUFFER))
    btc_balance: float = 0.0
    usdt_balance: float = 0.0
    equity_peak_usdt: float = 0.0
    breaker_active: bool = False
    last_rebalance_date: Optional[str] = None


def append_close(state: DailyState, timestamp: int, close: float) -> None:
    state.closes.append(DailyClose(timestamp=timestamp, close=close))


def close_values(state: DailyState) -> List[float]:
    return [c.close for c in state.closes]


def current_equity_usdt(state: DailyState, last_price: float) -> float:
    return state.usdt_balance + state.btc_balance * last_price


def current_exposure_pct(state: DailyState, last_price: float) -> float:
    equity = current_equity_usdt(state, last_price)
    if equity <= 0:
        return 0.0
    return (state.btc_balance * last_price) / equity
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_daily_state.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add daily_state.py tests/test_daily_state.py
git commit -m "Add daily_state.py: state and balance/exposure helpers for the TSMOM bot"
```

---

### Task 4: `daily_signal.py` — target exposure computation

**Files:**
- Create: `daily_signal.py`
- Test: `tests/test_daily_signal.py`

**Interfaces:**
- Consumes: `config.TSMOM_LOOKBACK_DAYS`, `config.VOL_TARGET_ANNUALIZED`, `estudios.nucleo.senal_tsmom`, `estudios.nucleo.retornos_diarios`, `estudios.nucleo.exposiciones` (Task 1)
- Produces: `objetivo_exposicion(closes: list[float]) -> float` — consumed by Task 9 (`main.py`).

This is the fidelity-critical module: it must produce, on live data, exactly
what the validated study would produce on the same data. It does this by
calling the study's own functions rather than re-deriving the math.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_daily_signal.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_daily_signal.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'daily_signal'`

- [ ] **Step 3: Write `daily_signal.py`**

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_daily_signal.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add daily_signal.py tests/test_daily_signal.py
git commit -m "Add daily_signal.py: TSMOM target exposure, reusing the validated study formulas"
```

---

### Task 5: `daily_safety.py` — circuit breaker, persistence, reconciliation

**Files:**
- Create: `daily_safety.py`
- Test: `tests/test_daily_safety.py`

**Interfaces:**
- Consumes: `config.DAILY_STATE_FILE_PATH`, `config.DRAWDOWN_CIRCUIT_BREAKER_PCT`, `config.PAPER_BALANCE_USDT`, `daily_state.DailyState`, `daily_state.DailyClose`, `daily_state.append_close`, `daily_state.current_equity_usdt` (Task 3)
- Produces: `update_circuit_breaker(state, last_price: float, on_breaker_tripped: Optional[Callable[[dict], None]] = None) -> None`, `save_state(state) -> None`, `load_into_state(state) -> bool`, `fetch_spot_balances(exchange) -> tuple[float, float]`, `reconcile_with_exchange(state, exchange) -> None`, `ensure_initialized(state, exchange, found_persisted: bool, last_price: float) -> None` — consumed by Tasks 6 and 9.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_daily_safety.py`:

```python
import json

import pytest

import daily_safety
from config import DRAWDOWN_CIRCUIT_BREAKER_PCT, PAPER_BALANCE_USDT
from daily_state import DailyState


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    path = tmp_path / "daily_safety_state.json"
    monkeypatch.setattr(daily_safety, "DAILY_STATE_FILE_PATH", str(path))
    return path


# --- circuit breaker ---

def test_update_circuit_breaker_trips_at_threshold():
    state = DailyState(usdt_balance=400.0, equity_peak_usdt=1000.0)

    daily_safety.update_circuit_breaker(state, last_price=0.0)

    assert state.breaker_active is True  # drawdown 0.6 >= 0.50


def test_update_circuit_breaker_does_not_trip_below_threshold():
    state = DailyState(usdt_balance=600.0, equity_peak_usdt=1000.0)

    daily_safety.update_circuit_breaker(state, last_price=0.0)

    assert state.breaker_active is False  # drawdown 0.4 < 0.50


def test_update_circuit_breaker_tracks_new_peak():
    state = DailyState(usdt_balance=1500.0, equity_peak_usdt=1000.0)

    daily_safety.update_circuit_breaker(state, last_price=0.0)

    assert state.equity_peak_usdt == pytest.approx(1500.0)
    assert state.breaker_active is False


def test_update_circuit_breaker_calls_hook_once_on_trip():
    state = DailyState(usdt_balance=400.0, equity_peak_usdt=1000.0)
    captured = []

    daily_safety.update_circuit_breaker(state, last_price=0.0, on_breaker_tripped=captured.append)
    daily_safety.update_circuit_breaker(state, last_price=0.0, on_breaker_tripped=captured.append)

    assert len(captured) == 1  # already active the second time — no re-trip
    assert captured[0]["drawdown_pct"] == pytest.approx(0.6)
    assert captured[0]["equity_usdt"] == pytest.approx(400.0)


# --- persistence ---

def test_save_then_load_round_trips_state(_isolate_state_file):
    state = DailyState(btc_balance=0.015, usdt_balance=200.0,
                        equity_peak_usdt=1200.0, breaker_active=True,
                        last_rebalance_date="2026-07-30")
    from daily_state import append_close
    append_close(state, timestamp=1000, close=50000.0)

    daily_safety.save_state(state)
    loaded = DailyState()
    found = daily_safety.load_into_state(loaded)

    assert found is True
    assert loaded.btc_balance == pytest.approx(0.015)
    assert loaded.usdt_balance == pytest.approx(200.0)
    assert loaded.equity_peak_usdt == pytest.approx(1200.0)
    assert loaded.breaker_active is True
    assert loaded.last_rebalance_date == "2026-07-30"
    assert [c.close for c in loaded.closes] == [50000.0]


def test_load_into_state_returns_false_when_file_missing(_isolate_state_file):
    state = DailyState()

    found = daily_safety.load_into_state(state)

    assert found is False
    assert state.btc_balance == 0.0


def test_load_into_state_returns_false_on_corrupt_json(_isolate_state_file):
    with open(daily_safety.DAILY_STATE_FILE_PATH, "w") as f:
        f.write("{not valid json")
    state = DailyState()

    found = daily_safety.load_into_state(state)

    assert found is False


# --- exchange balances / reconciliation ---

class _FakeBalanceExchange:
    def __init__(self, btc, usdt):
        self._btc = btc
        self._usdt = usdt

    def fetch_balance(self):
        return {"total": {"BTC": self._btc, "USDT": self._usdt}}


class _FailingExchange:
    def fetch_balance(self):
        raise RuntimeError("network down")


def test_fetch_spot_balances_returns_btc_and_usdt():
    exchange = _FakeBalanceExchange(0.5, 1000.0)

    btc, usdt = daily_safety.fetch_spot_balances(exchange)

    assert btc == pytest.approx(0.5)
    assert usdt == pytest.approx(1000.0)


def test_fetch_spot_balances_exits_on_failure():
    with pytest.raises(SystemExit):
        daily_safety.fetch_spot_balances(_FailingExchange())


def test_reconcile_ok_within_tolerance():
    state = DailyState(btc_balance=0.5, usdt_balance=1000.0)
    exchange = _FakeBalanceExchange(0.5, 1000.0)

    daily_safety.reconcile_with_exchange(state, exchange)  # must not raise


def test_reconcile_exits_on_mismatch():
    state = DailyState(btc_balance=0.5, usdt_balance=1000.0)
    exchange = _FakeBalanceExchange(0.9, 1000.0)

    with pytest.raises(SystemExit):
        daily_safety.reconcile_with_exchange(state, exchange)


# --- bootstrap ---

def test_ensure_initialized_seeds_paper_balance_when_fresh_and_no_exchange():
    state = DailyState()

    daily_safety.ensure_initialized(state, exchange=None, found_persisted=False, last_price=50000.0)

    assert state.usdt_balance == pytest.approx(PAPER_BALANCE_USDT)
    assert state.btc_balance == 0.0
    assert state.equity_peak_usdt == pytest.approx(PAPER_BALANCE_USDT)


def test_ensure_initialized_seeds_from_exchange_when_fresh_and_live():
    state = DailyState()
    exchange = _FakeBalanceExchange(0.1, 500.0)

    daily_safety.ensure_initialized(state, exchange, found_persisted=False, last_price=50000.0)

    assert state.btc_balance == pytest.approx(0.1)
    assert state.usdt_balance == pytest.approx(500.0)
    assert state.equity_peak_usdt == pytest.approx(0.1 * 50000.0 + 500.0)


def test_ensure_initialized_reconciles_when_persisted_and_live():
    state = DailyState(btc_balance=0.5, usdt_balance=1000.0)
    exchange = _FakeBalanceExchange(0.9, 1000.0)  # mismatch

    with pytest.raises(SystemExit):
        daily_safety.ensure_initialized(state, exchange, found_persisted=True, last_price=50000.0)


def test_ensure_initialized_skips_reconcile_when_persisted_and_paper():
    state = DailyState(btc_balance=0.5, usdt_balance=1000.0)

    daily_safety.ensure_initialized(state, exchange=None, found_persisted=True, last_price=50000.0)  # must not raise

    assert state.btc_balance == pytest.approx(0.5)  # untouched
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_daily_safety.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'daily_safety'`

- [ ] **Step 3: Write `daily_safety.py`**

```python
from __future__ import annotations

import json
import logging
import sys
from typing import Callable, Optional, Tuple

from config import DAILY_STATE_FILE_PATH, DRAWDOWN_CIRCUIT_BREAKER_PCT, PAPER_BALANCE_USDT
from daily_state import DailyState, append_close, current_equity_usdt

logger = logging.getLogger(__name__)

_BALANCE_TOLERANCE_PCT = 0.001


def update_circuit_breaker(
    state: DailyState,
    last_price: float,
    on_breaker_tripped: Optional[Callable[[dict], None]] = None,
) -> None:
    equity = current_equity_usdt(state, last_price)
    state.equity_peak_usdt = max(state.equity_peak_usdt, equity)
    if state.equity_peak_usdt <= 0:
        return

    drawdown = 1.0 - equity / state.equity_peak_usdt
    if drawdown >= DRAWDOWN_CIRCUIT_BREAKER_PCT and not state.breaker_active:
        state.breaker_active = True
        logger.warning(
            "DAILY CIRCUIT BREAKER ACTIVATED | drawdown=%.1f%% equity=$%.2f peak=$%.2f",
            drawdown * 100, equity, state.equity_peak_usdt,
        )
        if on_breaker_tripped is not None:
            on_breaker_tripped({"drawdown_pct": drawdown, "equity_usdt": equity})


def save_state(state: DailyState) -> None:
    payload = {
        "closes": [{"timestamp": c.timestamp, "close": c.close} for c in state.closes],
        "btc_balance": state.btc_balance,
        "usdt_balance": state.usdt_balance,
        "equity_peak_usdt": state.equity_peak_usdt,
        "breaker_active": state.breaker_active,
        "last_rebalance_date": state.last_rebalance_date,
    }
    try:
        with open(DAILY_STATE_FILE_PATH, "w") as f:
            json.dump(payload, f)
    except OSError:
        logger.exception("Failed to write %s", DAILY_STATE_FILE_PATH)


def load_into_state(state: DailyState) -> bool:
    """Returns True if a persisted state file was found and loaded."""
    try:
        with open(DAILY_STATE_FILE_PATH, "r") as f:
            payload = json.load(f)
    except FileNotFoundError:
        return False
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not parse %s — starting with fresh state", DAILY_STATE_FILE_PATH)
        return False

    try:
        for row in payload.get("closes", []):
            append_close(state, row["timestamp"], row["close"])
        state.btc_balance = payload.get("btc_balance", 0.0)
        state.usdt_balance = payload.get("usdt_balance", 0.0)
        state.equity_peak_usdt = payload.get("equity_peak_usdt", 0.0)
        state.breaker_active = payload.get("breaker_active", False)
        state.last_rebalance_date = payload.get("last_rebalance_date")
    except (TypeError, KeyError, ValueError):
        logger.warning("Could not parse %s — starting with fresh state", DAILY_STATE_FILE_PATH)
        return False
    return True


def fetch_spot_balances(exchange) -> Tuple[float, float]:
    """Returns (btc_total, usdt_total). Exits the process rather than
    guessing when the fetch fails — same fail-closed criterion as
    safety.fetch_real_balance."""
    try:
        balance = exchange.fetch_balance()
        btc = float(balance["total"].get("BTC", 0.0))
        usdt = float(balance["total"].get("USDT", 0.0))
    except Exception:
        logger.error("Could not fetch real spot balances", exc_info=True)
        sys.exit(1)
    return btc, usdt


def reconcile_with_exchange(state: DailyState, exchange) -> None:
    """Compares the persisted balances against the exchange's real reported
    balances. Exits the process rather than guessing when they disagree."""
    btc, usdt = fetch_spot_balances(exchange)

    btc_diff = abs(state.btc_balance - btc)
    usdt_diff = abs(state.usdt_balance - usdt)
    btc_ok = btc_diff <= max(btc, state.btc_balance, 1e-8) * _BALANCE_TOLERANCE_PCT
    usdt_ok = usdt_diff <= max(usdt, state.usdt_balance, 1.0) * _BALANCE_TOLERANCE_PCT

    if btc_ok and usdt_ok:
        logger.info("Reconciliation OK: btc=%.6f usdt=%.2f", btc, usdt)
        return

    logger.error(
        "RECONCILIATION MISMATCH — persisted btc=%.6f usdt=%.2f vs exchange btc=%.6f usdt=%.2f "
        "— refusing to start, manual review required",
        state.btc_balance, state.usdt_balance, btc, usdt,
    )
    sys.exit(1)


def ensure_initialized(state: DailyState, exchange, found_persisted: bool, last_price: float) -> None:
    """Called once at startup, after backfill. On a fresh install (no prior
    save_state ever ran), seeds balances from the paper default or the real
    exchange — there's nothing to reconcile against yet. On a resumed run
    with an exchange configured, reconciles instead."""
    if found_persisted:
        if exchange is not None:
            reconcile_with_exchange(state, exchange)
        return

    if exchange is None:
        state.usdt_balance = PAPER_BALANCE_USDT
        state.btc_balance = 0.0
    else:
        btc, usdt = fetch_spot_balances(exchange)
        state.btc_balance = btc
        state.usdt_balance = usdt

    state.equity_peak_usdt = current_equity_usdt(state, last_price)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_daily_safety.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add daily_safety.py tests/test_daily_safety.py
git commit -m "Add daily_safety.py: drawdown circuit breaker, persistence, and reconciliation"
```

---

### Task 6: `daily_execution.py` — rebalance-band execution engine

**Files:**
- Create: `daily_execution.py`
- Test: `tests/test_daily_execution.py`

**Interfaces:**
- Consumes: `config.REBALANCE_BAND_PCT`, `config.SPOT_TAKER_FEE_RATE`, `daily_state.DailyState`, `daily_state.current_equity_usdt`, `daily_state.current_exposure_pct` (Task 3)
- Produces: `DailyExecutionEngine` (class: `__init__(state, on_rebalanced: Optional[Callable[[dict], None]] = None)`, `async rebalance(target_exposure: float, last_price: float) -> bool`, property `exchange`), module-level `PAPER_MODE: bool` — consumed by Task 9.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_daily_execution.py`:

```python
import asyncio

import pytest

from config import SPOT_TAKER_FEE_RATE
from daily_execution import DailyExecutionEngine
from daily_state import DailyState, current_exposure_pct


def test_rebalance_noop_when_gap_below_band():
    state = DailyState(usdt_balance=1000.0, btc_balance=0.0)
    engine = DailyExecutionEngine(state)

    result = asyncio.run(engine.rebalance(target_exposure=0.05, last_price=50000.0))

    assert result is False
    assert state.btc_balance == 0.0
    assert state.usdt_balance == pytest.approx(1000.0)


def test_rebalance_buys_toward_target_when_gap_above_band():
    state = DailyState(usdt_balance=1000.0, btc_balance=0.0)
    engine = DailyExecutionEngine(state)

    result = asyncio.run(engine.rebalance(target_exposure=0.50, last_price=50000.0))

    assert result is True
    assert state.btc_balance > 0.0
    assert current_exposure_pct(state, 50000.0) == pytest.approx(0.50, abs=0.01)


def test_rebalance_sells_to_flat_when_target_zero():
    state = DailyState(usdt_balance=50.0, btc_balance=1.0)  # ~74% exposure @ price 140
    engine = DailyExecutionEngine(state)

    result = asyncio.run(engine.rebalance(target_exposure=0.0, last_price=140.0))

    assert result is True
    assert state.btc_balance == pytest.approx(0.0, abs=1e-9)


def test_rebalance_charges_taker_fee_on_buy():
    state = DailyState(usdt_balance=1000.0, btc_balance=0.0)
    engine = DailyExecutionEngine(state)

    asyncio.run(engine.rebalance(target_exposure=0.50, last_price=50000.0))

    expected_btc = 500.0 / 50000.0
    expected_fee = expected_btc * 50000.0 * SPOT_TAKER_FEE_RATE
    assert state.usdt_balance == pytest.approx(1000.0 - 500.0 - expected_fee)
    assert state.btc_balance == pytest.approx(expected_btc)


def test_rebalance_calls_on_rebalanced_hook_with_trade_details():
    state = DailyState(usdt_balance=1000.0, btc_balance=0.0)
    captured = []
    engine = DailyExecutionEngine(state, on_rebalanced=captured.append)

    asyncio.run(engine.rebalance(target_exposure=0.50, last_price=50000.0))

    assert len(captured) == 1
    assert captured[0]["side"] == "buy"
    assert captured[0]["price"] == pytest.approx(50000.0)


def test_rebalance_hook_not_called_when_below_band():
    state = DailyState(usdt_balance=1000.0, btc_balance=0.0)
    captured = []
    engine = DailyExecutionEngine(state, on_rebalanced=captured.append)

    asyncio.run(engine.rebalance(target_exposure=0.05, last_price=50000.0))

    assert captured == []


def test_paper_mode_engine_has_no_exchange():
    state = DailyState()
    engine = DailyExecutionEngine(state)

    assert engine.exchange is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_daily_execution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'daily_execution'`

- [ ] **Step 3: Write `daily_execution.py`**

```python
from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, Optional

from config import REBALANCE_BAND_PCT, SPOT_TAKER_FEE_RATE
from daily_state import DailyState, current_equity_usdt, current_exposure_pct

logger = logging.getLogger(__name__)

PAPER_MODE: bool = os.getenv("PAPER_MODE", "true").lower() == "true"


class DailyExecutionEngine:
    """Compares the target exposure against the current one and, if the gap
    clears REBALANCE_BAND_PCT, trades the difference in spot BTC/USDT. Below
    the band, does nothing — this is a deliberate operational approximation
    of the daily-rebalanced study (see spec section 2, no-goals)."""

    def __init__(self, state: DailyState, on_rebalanced: Optional[Callable[[dict], None]] = None) -> None:
        self.state = state
        self._exchange = None
        self._on_rebalanced = on_rebalanced
        if not PAPER_MODE:
            self._init_exchange()

    def _init_exchange(self) -> None:
        try:
            import ccxt
            self._exchange = ccxt.binance({
                "apiKey": os.environ["BINANCE_API_KEY"],
                "secret": os.environ["BINANCE_SECRET"],
                "options": {"defaultType": "spot"},
                "enableRateLimit": True,
            })
            logger.info("Live exchange (Binance Spot) initialized")
        except Exception:
            logger.exception("Exchange init failed — running in paper mode")
            self._exchange = None

    @property
    def exchange(self):
        return self._exchange

    async def rebalance(self, target_exposure: float, last_price: float) -> bool:
        current = current_exposure_pct(self.state, last_price)
        gap = target_exposure - current
        if abs(gap) < REBALANCE_BAND_PCT:
            return False

        equity = current_equity_usdt(self.state, last_price)
        delta_usdt = gap * equity
        side = "buy" if delta_usdt > 0 else "sell"
        btc_amount = round(abs(delta_usdt) / last_price, 6)
        if btc_amount <= 0:
            return False

        if not PAPER_MODE and self._exchange is not None:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._exchange.create_market_order("BTC/USDT", side, btc_amount),
                )
            except Exception:
                logger.exception("Live spot rebalance order failed — will retry next daily close")
                return False

        self._apply_fill(side, btc_amount, last_price)
        return True

    def _apply_fill(self, side: str, btc_amount: float, price: float) -> None:
        fee = btc_amount * price * SPOT_TAKER_FEE_RATE
        if side == "buy":
            self.state.btc_balance += btc_amount
            self.state.usdt_balance -= btc_amount * price + fee
        else:
            self.state.btc_balance -= btc_amount
            self.state.usdt_balance += btc_amount * price - fee

        new_exposure = current_exposure_pct(self.state, price)
        logger.info(
            "REBALANCE %s %.6f BTC @ %.2f | fee=$%.2f | exposure -> %.1f%%",
            side.upper(), btc_amount, price, fee, new_exposure * 100,
        )
        if self._on_rebalanced is not None:
            self._on_rebalanced({
                "side": side, "btc_amount": btc_amount, "price": price,
                "fee": fee, "new_exposure": new_exposure,
            })
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_daily_execution.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add daily_execution.py tests/test_daily_execution.py
git commit -m "Add daily_execution.py: band-based spot rebalancing for the TSMOM bot"
```

---

### Task 7: `daily_feed.py` — daily-candle websocket feed and REST backfill

**Files:**
- Create: `daily_feed.py`
- Test: `tests/test_daily_feed.py`

**Interfaces:**
- Consumes: `config.WS_STREAM_URL`, `config.DAILY_WS_STREAM`, `daily_state.DailyState`, `daily_state.DailyClose`, `daily_state.append_close` (Task 3), `clock.now` (already in the repo)
- Produces: `DailyDataFeed` (class: `__init__(state)`, `on_candle_1d(fn) -> None`, `async connect() -> None`, `async stop() -> None`), `backfill(state, exchange=None, limit: int = 100) -> None` — consumed by Task 9.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_daily_feed.py`:

```python
import asyncio

import clock
from daily_feed import DailyDataFeed, backfill
from daily_state import DailyState, close_values


def test_dispatch_ignores_unclosed_candle():
    state = DailyState()
    feed = DailyDataFeed(state)
    msg = {"data": {"k": {"t": 1000, "c": "50000.0", "x": False}}}

    asyncio.run(feed._dispatch(msg))

    assert close_values(state) == []


def test_dispatch_appends_closed_candle_and_emits():
    state = DailyState()
    feed = DailyDataFeed(state)
    received = []

    async def handler(candle):
        received.append(candle)

    feed.on_candle_1d(handler)
    msg = {"data": {"k": {"t": 1000, "c": "50000.0", "x": True}}}

    asyncio.run(feed._dispatch(msg))

    assert close_values(state) == [50000.0]
    assert len(received) == 1
    assert received[0].close == 50000.0
    assert received[0].timestamp == 1000


def test_dispatch_error_in_handler_does_not_raise():
    state = DailyState()
    feed = DailyDataFeed(state)

    async def bad_handler(candle):
        raise RuntimeError("boom")

    feed.on_candle_1d(bad_handler)
    msg = {"data": {"k": {"t": 1000, "c": "50000.0", "x": True}}}

    asyncio.run(feed._dispatch(msg))  # must not raise


class _FakeExchange:
    def __init__(self, rows):
        self._rows = rows

    def fetch_ohlcv(self, symbol, timeframe="1d", limit=100):
        assert symbol == "BTC/USDT"
        assert timeframe == "1d"
        return self._rows


def test_backfill_drops_the_still_forming_candle(monkeypatch):
    fixed_now = 2_000_000_000.0  # arbitrary fixed "now", seconds
    monkeypatch.setattr(clock, "now", lambda: fixed_now)
    now_ms = fixed_now * 1000.0
    rows = [
        [now_ms - 3 * 86_400_000, 1, 2, 3, 40000.0, 1],  # closed
        [now_ms - 2 * 86_400_000, 1, 2, 3, 41000.0, 1],  # closed
        [now_ms - 1 * 86_400_000, 1, 2, 3, 42000.0, 1],  # closed (exactly at the boundary)
        [now_ms, 1, 2, 3, 43000.0, 1],                   # still forming — must be dropped
    ]
    state = DailyState()
    exchange = _FakeExchange(rows)

    backfill(state, exchange, limit=4)

    assert close_values(state) == [40000.0, 41000.0, 42000.0]


def test_backfill_appends_in_chronological_order(monkeypatch):
    fixed_now = 2_000_000_000.0
    monkeypatch.setattr(clock, "now", lambda: fixed_now)
    now_ms = fixed_now * 1000.0
    rows = [
        [now_ms - 2 * 86_400_000, 0, 0, 0, 10.0, 0],
        [now_ms - 1 * 86_400_000, 0, 0, 0, 20.0, 0],
    ]
    state = DailyState()

    backfill(state, _FakeExchange(rows))

    assert close_values(state) == [10.0, 20.0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_daily_feed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'daily_feed'`

- [ ] **Step 3: Write `daily_feed.py`**

```python
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed

import clock
from config import DAILY_WS_STREAM, WS_STREAM_URL
from daily_state import DailyClose, DailyState, append_close

logger = logging.getLogger(__name__)

_Handler = Callable[[DailyClose], Awaitable[None]]
_ONE_DAY_MS = 86_400_000


class DailyDataFeed:
    """Subscribes to Binance spot's daily-kline stream and emits one event
    per closed UTC day. Handles reconnection with exponential backoff —
    same pattern as data_feed.DataFeed."""

    def __init__(self, state: DailyState) -> None:
        self.state = state
        self._candle_handlers: List[_Handler] = []
        self._running = False
        self._reconnect_delay = 1.0

    def on_candle_1d(self, fn: _Handler) -> None:
        self._candle_handlers.append(fn)

    async def connect(self) -> None:
        self._running = True
        url = f"{WS_STREAM_URL}?streams={DAILY_WS_STREAM}"
        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("Daily WebSocket connected to Binance")
                    self._reconnect_delay = 1.0
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._dispatch(json.loads(raw))
            except ConnectionClosed as exc:
                logger.warning("Daily WebSocket closed (%s) — reconnecting in %.1fs", exc, self._reconnect_delay)
            except Exception:
                logger.exception("Daily WebSocket error — reconnecting in %.1fs", self._reconnect_delay)

            if self._running:
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60.0)

    async def stop(self) -> None:
        self._running = False

    async def _dispatch(self, msg: dict) -> None:
        data = msg.get("data", msg)
        k = data.get("k")
        if k is None or not k.get("x"):
            return  # only closed daily candles matter — the signal is decided once a day
        candle = DailyClose(timestamp=int(k["t"]), close=float(k["c"]))
        append_close(self.state, candle.timestamp, candle.close)
        await self._emit(candle)

    async def _emit(self, candle: DailyClose) -> None:
        for h in self._candle_handlers:
            try:
                await h(candle)
            except Exception:
                logger.exception("Error in daily candle handler %s", getattr(h, "__name__", repr(h)))


def _public_spot_exchange():
    import ccxt
    return ccxt.binance({"options": {"defaultType": "spot"}, "enableRateLimit": True})


def backfill(state: DailyState, exchange: Optional[object] = None, limit: int = 100) -> None:
    """Startup only: fetches the last `limit` daily candles via REST (public
    endpoint — no API keys needed) and seeds state.closes, so the k=14
    lookback and 30-day vol window are populated immediately instead of
    waiting weeks. Drops Binance's still-forming current-day candle."""
    ex = exchange if exchange is not None else _public_spot_exchange()
    rows = ex.fetch_ohlcv("BTC/USDT", timeframe="1d", limit=limit)
    now_ms = clock.now() * 1000.0
    for ts, _o, _h, _l, close, _v in rows:
        if ts + _ONE_DAY_MS > now_ms:
            continue  # still forming — wait for the close event instead
        append_close(state, int(ts), float(close))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_daily_feed.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add daily_feed.py tests/test_daily_feed.py
git commit -m "Add daily_feed.py: daily-kline websocket feed and REST backfill"
```

---

### Task 8: `notifications.py` — rebalance and circuit-breaker messages

**Files:**
- Modify: `notifications.py`
- Test: `tests/test_notifications.py` (append new tests)

**Interfaces:**
- Produces: `TelegramNotifier.notify_rebalance(event: dict) -> None`, `TelegramNotifier.notify_circuit_breaker(drawdown_pct: float, equity_usdt: float) -> None` — consumed by Task 9.

No existing method, class, or test in `notifications.py` is touched — this
task only adds two new methods.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_notifications.py`:

```python
def test_notify_rebalance_formats_side_amount_price_fee_and_exposure():
    notifier = TelegramNotifier("token123", "chat123")

    notifier.notify_rebalance({
        "side": "buy", "btc_amount": 0.01, "price": 50000.0,
        "fee": 0.5, "new_exposure": 0.50,
    })

    text = notifier._queue.get_nowait()
    assert text == (
        "⚖️ Rebalanceo BUY BTC/USDT\n"
        "Monto: 0.010000 BTC @ $50,000.00\n"
        "Fee: $0.50  |  exposición nueva: 50.0%"
    )


def test_notify_circuit_breaker_formats_drawdown_and_equity():
    notifier = TelegramNotifier("token123", "chat123")

    notifier.notify_circuit_breaker(drawdown_pct=0.52, equity_usdt=4800.0)

    text = notifier._queue.get_nowait()
    assert text == (
        "🛑 CIRCUIT BREAKER ACTIVADO (TSMOM)\n"
        "Drawdown desde el pico: 52.0%  |  equity: $4,800.00\n"
        "Posición forzada a flat. No se abren nuevas posiciones hasta reset manual."
    )


def test_notify_rebalance_disabled_when_no_credentials():
    notifier = TelegramNotifier(None, None)

    notifier.notify_rebalance({
        "side": "sell", "btc_amount": 0.01, "price": 50000.0,
        "fee": 0.5, "new_exposure": 0.0,
    })

    assert notifier._queue.empty()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_notifications.py -v -k "rebalance or circuit_breaker"`
Expected: FAIL with `AttributeError: 'TelegramNotifier' object has no attribute 'notify_rebalance'`

- [ ] **Step 3: Add the two methods to `notifications.py`**

Insert into the `TelegramNotifier` class, after `notify_daily_summary`:

```python
    def notify_rebalance(self, event: dict) -> None:
        text = (
            f"⚖️ Rebalanceo {event['side'].upper()} BTC/USDT\n"
            f"Monto: {event['btc_amount']:.6f} BTC @ ${event['price']:,.2f}\n"
            f"Fee: ${event['fee']:,.2f}  |  exposición nueva: {event['new_exposure']*100:.1f}%"
        )
        self._enqueue(text)

    def notify_circuit_breaker(self, drawdown_pct: float, equity_usdt: float) -> None:
        text = (
            "🛑 CIRCUIT BREAKER ACTIVADO (TSMOM)\n"
            f"Drawdown desde el pico: {drawdown_pct*100:.1f}%  |  equity: ${equity_usdt:,.2f}\n"
            "Posición forzada a flat. No se abren nuevas posiciones hasta reset manual."
        )
        self._enqueue(text)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_notifications.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Commit**

```bash
git add notifications.py tests/test_notifications.py
git commit -m "Add rebalance and circuit-breaker Telegram notifications for the TSMOM bot"
```

---

### Task 9: `main.py` — wire the daily TSMOM strategy

**Files:**
- Modify: `main.py`
- Test: `tests/test_main.py` (append new tests; existing tests untouched)

**Interfaces:**
- Consumes: everything from Tasks 1–8 (`daily_state`, `daily_signal`, `daily_safety`, `daily_execution`, `daily_feed`, `notifications`)
- Produces: `wire_daily_strategy(state, feed, engine, on_breaker_tripped: Optional[Callable[[dict], None]] = None) -> None`

This task changes what `main.py: run()` wires up. `wire_strategy` (scalping)
and its imports are **not removed** — they stay exactly as-is, unused by
`run()`, so `tests/test_main.py`'s existing tests keep passing unmodified
and the scalping code stays dormant rather than deleted (per the spec's
no-goals).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main.py`:

```python
import pytest

from daily_execution import DailyExecutionEngine
from daily_state import DailyClose, DailyState, append_close
from main import wire_daily_strategy


class _FakeDailyFeed:
    def __init__(self):
        self.candle_1d_handlers = []

    def on_candle_1d(self, fn):
        self.candle_1d_handlers.append(fn)


def _rising_history(n: int = 40, usdt_balance: float = 1000.0) -> DailyState:
    state = DailyState(usdt_balance=usdt_balance)
    for i in range(n):
        append_close(state, timestamp=i * 86_400_000, close=100.0 + i)
    return state


def test_wire_daily_strategy_registers_one_candle_handler():
    state = DailyState()
    feed = _FakeDailyFeed()
    engine = DailyExecutionEngine(state)

    wire_daily_strategy(state, feed, engine)

    assert len(feed.candle_1d_handlers) == 1


def test_on_candle_1d_updates_equity_peak_and_persists():
    state = _rising_history(40)
    feed = _FakeDailyFeed()
    engine = DailyExecutionEngine(state)
    wire_daily_strategy(state, feed, engine)

    asyncio.run(feed.candle_1d_handlers[0](DailyClose(timestamp=40 * 86_400_000, close=140.0)))

    assert state.equity_peak_usdt > 0.0
    assert state.last_rebalance_date == clock.today_utc()


def test_on_candle_1d_forces_flat_when_breaker_already_active():
    state = _rising_history(40, usdt_balance=50.0)
    state.btc_balance = 1.0  # ~74% exposure at price 140 — well above the 10pp band
    state.breaker_active = True
    feed = _FakeDailyFeed()
    engine = DailyExecutionEngine(state)
    wire_daily_strategy(state, feed, engine)

    asyncio.run(feed.candle_1d_handlers[0](DailyClose(timestamp=40 * 86_400_000, close=140.0)))

    assert state.btc_balance == pytest.approx(0.0, abs=1e-6)


def test_on_candle_1d_calls_on_breaker_tripped_hook():
    state = _rising_history(40, usdt_balance=400.0)
    state.equity_peak_usdt = 1000.0  # current equity (400) is a 60% drawdown from this peak
    captured = []
    feed = _FakeDailyFeed()
    engine = DailyExecutionEngine(state)
    wire_daily_strategy(state, feed, engine, on_breaker_tripped=captured.append)

    asyncio.run(feed.candle_1d_handlers[0](DailyClose(timestamp=40 * 86_400_000, close=140.0)))

    assert len(captured) == 1
    assert state.breaker_active is True
```

Also add the missing imports at the top of `tests/test_main.py` — `asyncio`
is already imported there (keep it), but `pytest` and `clock` are not yet
used in that file and must be added:

```python
import pytest

import clock
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_main.py -v -k daily`
Expected: FAIL with `ImportError: cannot import name 'wire_daily_strategy' from 'main'`

- [ ] **Step 3: Update `main.py`**

Add these imports near the top of `main.py`, alongside the existing ones
(do not remove any existing import):

```python
import daily_safety
from daily_execution import DailyExecutionEngine
from daily_feed import DailyDataFeed, backfill
from daily_signal import objetivo_exposicion
from daily_state import DailyState, DailyClose, close_values
```

Add `wire_daily_strategy`, after the existing `wire_strategy` function:

```python
def wire_daily_strategy(
    state: DailyState,
    feed,
    engine: DailyExecutionEngine,
    on_breaker_tripped: Optional[Callable[[dict], None]] = None,
) -> None:
    """Registers the daily TSMOM strategy's single event handler: one
    signal evaluation + rebalance per closed UTC day. feed can be
    DailyDataFeed (live) — it only needs to expose on_candle_1d
    (duck typing, same convention as wire_strategy)."""

    async def on_candle_1d(candle: DailyClose) -> None:
        daily_safety.update_circuit_breaker(state, candle.close, on_breaker_tripped=on_breaker_tripped)
        target = 0.0 if state.breaker_active else objetivo_exposicion(close_values(state))
        await engine.rebalance(target, candle.close)
        state.last_rebalance_date = clock.today_utc()
        daily_safety.save_state(state)

        logger.info(
            "1d | close=%.2f target_exposure=%.1f%% breaker=%s",
            candle.close, target * 100, state.breaker_active,
        )

    feed.on_candle_1d(on_candle_1d)
```

`wire_daily_strategy` needs `Callable` and `Optional` — add
`from typing import Callable, Optional` to `main.py`'s imports if not
already present (it currently isn't).

Now replace the body of `run()`. The scalping `wire_strategy` call and its
setup (`safety.load_into_state`, `feed = DataFeed(state)`,
`engine = ExecutionEngine(...)`, `safety.reconcile_with_exchange`, etc.) are
**removed from `run()`** (but the `wire_strategy` function itself, and
`DataFeed`/`ExecutionEngine`/`safety` imports, stay in the file — `run()`
just stops calling them):

```python
async def run() -> None:
    daily_state = DailyState()
    found_persisted = daily_safety.load_into_state(daily_state)

    notifier = TelegramNotifier(os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"))

    engine = DailyExecutionEngine(daily_state, on_rebalanced=notifier.notify_rebalance)
    backfill(daily_state, engine.exchange)

    last_close = close_values(daily_state)[-1] if daily_state.closes else 0.0
    daily_safety.ensure_initialized(daily_state, engine.exchange, found_persisted, last_close)

    feed = DailyDataFeed(daily_state)
    on_breaker_tripped = lambda e: notifier.notify_circuit_breaker(e["drawdown_pct"], e["equity_usdt"])
    wire_daily_strategy(daily_state, feed, engine, on_breaker_tripped=on_breaker_tripped)

    mode = "PAPER" if os.getenv("PAPER_MODE", "true").lower() == "true" else "LIVE"
    logger.info("BTC TSMOM Daily Bot starting — mode=%s", mode)

    await asyncio.gather(
        feed.connect(),
        notifier.run(),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_main.py -v`
Expected: PASS (all tests — the pre-existing scalping-wiring tests AND the new daily-wiring tests)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: PASS, every test in the repo (scalping tests untouched and green, new daily-strategy tests green)

- [ ] **Step 6: Manual paper-trading smoke check**

Run: `PAPER_MODE=true LOG_LEVEL=INFO python main.py` and let it run for ~30
seconds, then Ctrl+C.
Expected: log line `BTC TSMOM Daily Bot starting — mode=PAPER`, a successful
`Daily WebSocket connected to Binance` line, and no tracebacks. (The daily
candle only closes once a day, so no rebalance line is expected in a
30-second smoke check — this step only confirms startup, backfill, and the
websocket connection work end-to-end against the real Binance feed.)

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "$(cat <<'EOF'
Wire the daily TSMOM strategy into main.py, running in paper trading

run() now starts the daily momentum bot (TSMOM k=14 long_flat +
vol-targeting, spot, band-based rebalancing, drawdown circuit
breaker) instead of the scalping strategy. wire_strategy and the
scalping modules it depends on are untouched and stay dormant in the
repo, per the spec's no-goals.
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** §3 (components) → Tasks 3–8; §3.1 (nucleo extraction) → Task 1; §4 (data flow: backfill, signal, exposure, breaker, band, persistence, notify) → Tasks 4–9; §5 (error handling: fail-closed order/reconnect/reconciliation) → Tasks 5–7; §6 (config) → Task 2; §7 (testing, including the signal fidelity test) → Task 4 Step 1 is that exact test. §8 (decisions) is reflected throughout (spot in Task 6, paper-first via `PAPER_MODE` default in Task 6, σ=0.40 in Task 2, breaker at 50% in Task 2/5, dormant scalping code preserved in Task 9, band-based rebalance in Task 6).
- **No placeholders:** every step has complete, runnable code; no TBDs.
- **Type consistency checked:** `DailyState`/`DailyClose` (Task 3) are the same names and fields used in Tasks 4–9; `objetivo_exposicion(closes: list[float]) -> float` (Task 4) matches its call site in Task 9 (`close_values(state)` returns `list[float]`); `DailyExecutionEngine.rebalance(target_exposure, last_price) -> bool` (Task 6) matches its call in Task 9; `on_rebalanced`/`on_breaker_tripped` callback dict shapes match what `notify_rebalance`/`notify_circuit_breaker` (Task 8) expect.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-30-integracion-tsmom-vivo.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
