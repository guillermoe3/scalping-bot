# Ciclo limpieza + estudios de tasa base — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dejar el bot sin señal muerta ni gates ciegos (backtest = live), extender los datos a funding y klines 15m multi-año (BTC+ETH), y correr tres estudios de tasa base pre-registrados (C2 sesión, C1 funding, C3 cascadas) que decidan la próxima hipótesis de señal sin escribir código del bot.

**Architecture:** La limpieza reduce `signals.py` a un harness de gates sin disparador (`check_entry_signal` devuelve `None`; los gates viven en `_passes_gates`, reutilizables y testeados) y elimina `MacroFilter` y el imbalance del order book. Los datos nuevos siguen el patrón de P0-6 (dumps mensuales de Binance Vision → cache compacto en `backtest_cache/`). Los estudios son scripts sobre una librería mínima (`estudios/`) con partición calibración/verificación bloqueada por flag y reportes que imprimen su pre-registro.

**Tech Stack:** Python 3.12, stdlib pura (urllib, zipfile, gzip, json, csv, statistics), pytest. Sin dependencias nuevas; se ELIMINA yfinance.

**Spec:** `docs/superpowers/specs/2026-07-14-ciclo-limpieza-y-estudios-tasa-base-design.md` (leerla antes de la Task 1; los umbrales pre-registrados de ahí son ley).

## Global Constraints

- Tests: `.venv/bin/python -m pytest -q` — la suite completa debe quedar verde al final de cada task.
- Sin dependencias nuevas en `requirements.txt`; `yfinance` se elimina (Task 2).
- Código y comentarios en inglés; docs y reportes en español.
- TDD estricto: test que falla → implementación mínima → verde → commit.
- Commits: imperativo corto en inglés + footer de co-autoría del harness.
- Descargas y agregaciones SIEMPRE mes a mes (o día a día para ticks); nunca el histórico entero en RAM; un solo proceso pesado a la vez (lección del OOM 2026-07-13).
- Constantes pre-registradas (fuente: la spec; no cambiarlas al ver datos):
  - Costos: round-trip = 0.07% del notional; "holgado" = 0.14%.
  - C1: percentiles 90/10 sobre ventana rodante de 90 observaciones de funding (30 días); evento = cruce de entrada a la cola; horizontes 8h/24h/72h; n mínimo 150 por cola y símbolo; adopción = mediana firmada ≥ 0.14% Y media mismo signo Y hit rate > 50%, en calibración y sostenido en verificación (mismo signo, magnitud ≥ ½ de calibración).
  - C3: |z| > 3 contra desvío de retornos 15m de las 96 velas previas; flujo unidireccional ≥ 0.6; horizontes 1h/4h/8h; n < 50 → solo "descartar" o "extender datos".
  - Splits: C2/C1 calibración 2020-01-01→2024-12-31, verificación 2025-01-01→presente. C3 calibración 2026-04-01→2026-05-31, verificación 2026-06-01→2026-07-01.
- Gates finales del bot: `GATE_NAMES = ("spread", "trend_1h", "cvd")`, con `cvd` desactivado por default.

---

### Task 1: signals.py y state.py sin disparador — harness de gates reutilizable + invariante D4

El squeeze deja de ser disparador y pierde su tesis direccional. `check_entry_signal` devuelve `None` siempre. Los gates sobrevivientes (`spread`, `trend_1h`, `cvd`) se mueven a `_passes_gates(state, direction)` para que la próxima señal los reuse. Los gates `regime_known`, `breakout_align`, `macro` y `ob_imbalance` desaparecen de `GATE_NAMES` (macro/OB se terminan de borrar en Tasks 2-3). `run_ablation.py` se retira: su matriz de 12 corridas codifica las variantes A/B muertas (recuperable por git; la próxima ablación escribe su propio runner sobre los flags del CLI, que se conservan).

**Files:**
- Modify: `signals.py` (reescritura completa, abajo)
- Modify: `state.py:126-137` (campos de squeeze)
- Modify: `backtest.py` (flags `--variant` fuera, `--enable-gate` nuevo)
- Delete: `run_ablation.py`, `tests/test_run_ablation.py`
- Test: `tests/test_signals.py` (reescritura completa), `tests/test_state.py`, `tests/test_backtest.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: nada de tasks previas.
- Produces (Tasks 2-4 y cualquier señal futura dependen de esto):

```python
# signals.py
GATE_NAMES: tuple[str, ...] = ("spread", "trend_1h", "cvd")
BACKTEST_EVALUABLE_GATES: tuple[str, ...] = ("spread", "trend_1h", "cvd")
DEFAULT_DISABLED_GATES: frozenset = frozenset({"cvd"})
DISABLED_GATES: set  # mutable, arranca como set(DEFAULT_DISABLED_GATES)
def _passes_gates(state: MarketState, direction: Side) -> bool
def check_entry_signal(state: MarketState) -> Optional[Side]  # siempre None
def update_squeeze(state: MarketState) -> None  # solo compresión, sin tesis
def reset_signal_stats() -> None  # counters, no toca DISABLED_GATES
```

- En `state.py` DEJAN DE EXISTIR: `squeeze_direction`, `squeeze_reference_level`, `squeeze_price_above_level`, `squeeze_broken`, `squeeze_broken_direction`, `squeeze_broken_level`, `squeeze_broken_ttl`. Se conservan `in_squeeze` y `squeeze_bar_count`.

- [ ] **Step 1: Reescribir `tests/test_signals.py` (failing-first)**

Contenido completo nuevo del archivo:

```python
import pytest

import signals
from signals import (
    BACKTEST_EVALUABLE_GATES,
    DEFAULT_DISABLED_GATES,
    GATE_NAMES,
    GATE_VETO_COUNTS,
    _nearest_key_level,
    _passes_gates,
    check_entry_signal,
    reset_signal_stats,
    update_squeeze,
)
from state import Candle, MarketState, Side


@pytest.fixture(autouse=True)
def _reset_gates():
    signals.DISABLED_GATES = set(DEFAULT_DISABLED_GATES)
    reset_signal_stats()
    yield
    signals.DISABLED_GATES = set(DEFAULT_DISABLED_GATES)
    reset_signal_stats()


def _candle(o=100.0, h=101.0, low=99.0, c=100.0, ts=0) -> Candle:
    return Candle(open=o, high=h, low=low, close=c, volume=1.0, timestamp=ts)


def _armed_state() -> MarketState:
    """A state that under the old code would have produced a LONG fade signal."""
    state = MarketState()
    state.atr = 2.0
    state.last_price = 100.4
    state.spread = 0.0001
    state.trend_1h = Side.LONG
    state.swing_lows.append(100.0)  # support right under price
    for i in range(5):
        state.candles_15m.append(_candle(c=100.4, h=100.6, low=100.2, ts=i * 900_000))
    for _ in range(4):
        update_squeeze(state)
    assert state.in_squeeze  # sanity: the detector still arms
    return state


# --- no entry trigger ---

def test_check_entry_signal_returns_none_even_with_fully_armed_setup():
    state = _armed_state()
    assert check_entry_signal(state) is None


def test_check_entry_signal_fires_no_stats():
    state = _armed_state()
    check_entry_signal(state)
    assert signals.SIGNAL_STATS["fired"] == 0
    assert all(v == 0 for v in GATE_VETO_COUNTS.values())


# --- squeeze reduced to a compression detector ---

def test_update_squeeze_arms_without_directional_state():
    state = _armed_state()
    assert not hasattr(state, "squeeze_direction")
    assert not hasattr(state, "squeeze_broken")
    assert not hasattr(state, "squeeze_reference_level")


def test_update_squeeze_resets_when_compression_ends():
    state = _armed_state()
    state.candles_15m.append(_candle(c=104.0, h=105.0, low=99.5, ts=99 * 900_000))
    update_squeeze(state)
    assert not state.in_squeeze
    assert state.squeeze_bar_count == 0


# --- gate harness ---

def test_gate_names_are_exactly_the_survivors():
    assert GATE_NAMES == ("spread", "trend_1h", "cvd")


def test_cvd_gate_is_disabled_by_default():
    assert "cvd" in DEFAULT_DISABLED_GATES
    assert signals.DISABLED_GATES == set(DEFAULT_DISABLED_GATES)


def test_backtest_live_invariant_every_gate_is_backtest_evaluable():
    # D4: reintroducing a gate the backtest engine cannot evaluate must break CI.
    assert set(GATE_NAMES) <= set(BACKTEST_EVALUABLE_GATES)


def test_passes_gates_spread_veto():
    state = MarketState()
    state.atr = 2.0
    state.spread = 1.0  # >> SPREAD_FILTER_ATR_PCT * atr = 0.02
    assert _passes_gates(state, Side.LONG) is False
    assert GATE_VETO_COUNTS["spread"] == 1


def test_passes_gates_trend_veto():
    state = MarketState()
    state.atr = 2.0
    state.trend_1h = Side.SHORT
    assert _passes_gates(state, Side.LONG) is False
    assert GATE_VETO_COUNTS["trend_1h"] == 1


def test_passes_gates_ok_when_aligned_and_tight_spread():
    state = MarketState()
    state.atr = 2.0
    state.spread = 0.0001
    state.trend_1h = Side.LONG
    assert _passes_gates(state, Side.LONG) is True


def test_passes_gates_cvd_ignored_while_disabled(monkeypatch):
    state = MarketState()
    state.atr = 2.0
    state.spread = 0.0001
    state.trend_1h = Side.LONG
    monkeypatch.setattr(signals, "detect_cvd_divergence", lambda s: "bearish_divergence")
    assert _passes_gates(state, Side.LONG) is True  # cvd is in DISABLED_GATES
    assert GATE_VETO_COUNTS["cvd"] == 0


def test_passes_gates_cvd_vetoes_when_enabled(monkeypatch):
    state = MarketState()
    state.atr = 2.0
    state.spread = 0.0001
    state.trend_1h = Side.LONG
    signals.DISABLED_GATES = set()
    monkeypatch.setattr(signals, "detect_cvd_divergence", lambda s: "bearish_divergence")
    assert _passes_gates(state, Side.LONG) is False
    assert GATE_VETO_COUNTS["cvd"] == 1


# --- _nearest_key_level (unchanged behaviour, kept because update_squeeze uses it) ---

def test_nearest_key_level_prefers_consistent_side_on_tie():
    state = MarketState()
    state.swing_lows.append(99.0)
    state.swing_highs.append(101.0)
    level, dist, kind = _nearest_key_level(100.0, state)
    assert (level, kind) == (99.0, "support")
    assert dist == pytest.approx(1.0)


def test_nearest_key_level_empty_state():
    state = MarketState()
    level, dist, kind = _nearest_key_level(100.0, state)
    assert level == 0.0 and dist == float("inf")
```

- [ ] **Step 2: Verificar que fallan**

Run: `.venv/bin/python -m pytest tests/test_signals.py -v`
Expected: FAIL (`ImportError: cannot import name 'BACKTEST_EVALUABLE_GATES'`).

- [ ] **Step 3: Reescribir `signals.py`**

Contenido completo nuevo (conserva `_nearest_key_level` idéntico al actual):

```python
from __future__ import annotations

import logging
from typing import Optional, Tuple

import config
from config import SPREAD_FILTER_ATR_PCT, SQUEEZE_LEVEL_ATR_PROXIMITY
from order_flow import detect_cvd_divergence
from state import MarketState, Side

logger = logging.getLogger(__name__)


# --- Key level proximity ---

def _nearest_key_level(price: float, state: MarketState) -> Tuple[float, float, str]:
    """Return (level, distance, kind) for the closest swing level.

    kind is "support" (swing low) or "resistance" (swing high). On an exact
    distance tie the level consistent with the price side wins (support at or
    below price, resistance at or above); if both qualify, support wins.
    """
    candidates = [(lvl, abs(lvl - price), "support") for lvl in state.swing_lows]
    candidates += [(lvl, abs(lvl - price), "resistance") for lvl in state.swing_highs]
    if not candidates:
        return 0.0, float("inf"), "support"

    def _rank(candidate):
        lvl, dist, kind = candidate
        consistent = (kind == "support" and lvl <= price) or (kind == "resistance" and lvl >= price)
        return (dist, 0 if consistent else 1, 0 if kind == "support" else 1)

    return min(candidates, key=_rank)


# --- Squeeze detection (compression detector only — no directional thesis) ---

def update_squeeze(state: MarketState) -> None:
    """Detect range compression near a swing level.

    The squeeze-based ENTRY hypothesis was rejected twice with clean
    measurement (backtest_runs/ablation-2026-07-14.md: no direction edge, and
    volatility CONTRACTS after a squeeze). What survives is the detector
    itself: compression predicts calm, so `in_squeeze` is a candidate
    "do not trade" filter for future signals. It carries no direction.
    """
    if state.atr <= 0:
        return

    candles = list(state.candles_15m)
    if not candles:
        return

    latest = candles[-1]
    is_compressed = latest.range <= config.SQUEEZE_COMPRESSION_ATR * state.atr
    key_level, distance, _kind = _nearest_key_level(state.last_price, state)
    near_level = key_level > 0 and distance <= SQUEEZE_LEVEL_ATR_PROXIMITY * state.atr

    if is_compressed and near_level:
        state.squeeze_bar_count += 1
        if state.squeeze_bar_count >= config.SQUEEZE_MIN_BARS:
            state.in_squeeze = True
    else:
        state.squeeze_bar_count = 0
        state.in_squeeze = False


# --- Entry gate harness ---
#
# Gates named here MUST be evaluable by the backtest engine (their inputs are
# updated during replay). That is the backtest=live invariant: a gate the
# simulator cannot exercise gives the live bot a behaviour no measurement can
# audit. macro and ob_imbalance were removed for exactly that reason
# (spec 2026-07-14). Enforced by test_backtest_live_invariant_*.
GATE_NAMES = ("spread", "trend_1h", "cvd")
BACKTEST_EVALUABLE_GATES = ("spread", "trend_1h", "cvd")

# cvd is off by default: the 2026-07-14 ablation showed it vetoing good trades
# (PF 0.30 -> 0.51 without it). It stays implemented so a future ablation can
# re-measure it (backtest --enable-gate cvd).
DEFAULT_DISABLED_GATES = frozenset({"cvd"})
DISABLED_GATES: set = set(DEFAULT_DISABLED_GATES)

# Diagnostic counters, reset per backtest run via reset_signal_stats().
GATE_VETO_COUNTS = {name: 0 for name in GATE_NAMES}
SIGNAL_STATS = {"fired": 0}


def reset_signal_stats() -> None:
    for name in GATE_NAMES:
        GATE_VETO_COUNTS[name] = 0
    SIGNAL_STATS["fired"] = 0


def _vetoed(name: str, opposes: bool) -> bool:
    """A named gate rejects the candidate signal (unless disabled)."""
    if name in DISABLED_GATES or not opposes:
        return False
    GATE_VETO_COUNTS[name] += 1
    return True


def _passes_gates(state: MarketState, direction: Side) -> bool:
    """Run every named gate against a candidate direction.

    Kept fully wired (and unit-tested) even though no trigger currently
    calls it: this is the reusable half of the ablation harness that the
    next adopted signal must pass through.
    """
    if _vetoed("spread", state.atr > 0 and state.spread > SPREAD_FILTER_ATR_PCT * state.atr):
        logger.debug(
            "Signal rejected: spread %.4f exceeds %.0f%% of ATR %.4f",
            state.spread, SPREAD_FILTER_ATR_PCT * 100, state.atr,
        )
        return False

    if _vetoed("trend_1h", state.trend_1h is not None and state.trend_1h != direction):
        logger.debug("Signal rejected: 1h trend %s opposes %s", state.trend_1h, direction)
        return False

    divergence = detect_cvd_divergence(state)
    cvd_opposes = (direction == Side.LONG and divergence == "bearish_divergence") or \
                  (direction == Side.SHORT and divergence == "bullish_divergence")
    if _vetoed("cvd", cvd_opposes):
        logger.debug("Signal rejected: %s against %s setup", divergence, direction.value)
        return False

    return True


# --- Entry signal ---

def check_entry_signal(state: MarketState) -> Optional[Side]:
    """No entry trigger is currently adopted — always returns None.

    The squeeze trigger was retired after its pre-registered rejection
    (backtest_runs/ablation-2026-07-14.md). A bot with no signal that does
    not trade is the CORRECT state. The next trigger must come from an
    approved base-rate study (see docs/superpowers/specs/
    2026-07-14-ciclo-limpieza-y-estudios-tasa-base-design.md), be expressed
    as trigger + _passes_gates, and survive the ablation harness.
    """
    return None
```

Nota: tras esta reescritura `check_entry_signal` ya no referencia `macro_blocks_*` ni `get_book_imbalance` — eso deja a Tasks 2-3 borrar sus módulos sin tocar signals de nuevo.

- [ ] **Step 4: Recortar `state.py`**

Reemplazar el bloque de squeeze (líneas 126-137) por:

```python
    # Compression detector (candidate future "calm filter" — no direction;
    # the squeeze entry hypothesis was rejected, see ablation-2026-07-14)
    in_squeeze: bool = False
    squeeze_bar_count: int = 0
```

- [ ] **Step 5: Ajustar `backtest.py`**

En `parse_args`: eliminar el argumento `--variant`; agregar:

```python
    parser.add_argument("--enable-gate", action="append", default=None,
                        choices=signals.GATE_NAMES, dest="enable_gate",
                        help="Re-enciende un gate desactivado por default (repetible)")
```

En `run_backtest`: eliminar `signals.ENTRY_VARIANT = args.variant` y reemplazar la línea de `DISABLED_GATES` por:

```python
    signals.DISABLED_GATES = (
        set(signals.DEFAULT_DISABLED_GATES) | set(args.disable_gate or ())
    ) - set(args.enable_gate or ())
```

En `meta`: eliminar la clave `"variant"`; `"disabled_gates": sorted(signals.DISABLED_GATES)` queda igual (ahora incluirá `cvd` por default — correcto y auditable).

- [ ] **Step 6: Retirar el runner de la ablación muerta**

```bash
git rm run_ablation.py tests/test_run_ablation.py
```

(Codifica la matriz de las variantes A/B retiradas; la próxima señal escribe su propio runner sobre `--disable-gate`/`--enable-gate`.)

- [ ] **Step 7: Podar tests que referencian lo eliminado**

```bash
grep -rln "ENTRY_VARIANT\|squeeze_direction\|squeeze_broken\|squeeze_reference_level\|squeeze_price_above_level\|--variant\|regime_known\|breakout_align" tests/
```

Regla por archivo: en `tests/test_state.py` y `tests/test_main.py`, borrar solo los tests/asserts de los símbolos muertos. En `tests/test_backtest.py`, quitar usos de `--variant` de los argv y actualizar cualquier assert sobre `meta` que espere la clave `variant`; si algún test asserteaba `disabled_gates == []`, ahora espera `["cvd"]`. No "arreglar" tests conservando el comportamiento viejo: el comportamiento nuevo es la spec.

- [ ] **Step 8: Suite completa verde**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add signals.py state.py backtest.py tests/
git commit -m "Retire the squeeze entry trigger; keep gates as a reusable, invariant-checked harness"
```

---

### Task 2: Retirar el filtro macro BTC-SPY

**Files:**
- Delete: `context.py`, `tests/test_context.py`
- Modify: `main.py:10,105,117-121`, `state.py:146-148`, `config.py:55-57`, `requirements.txt`
- Test: suite existente (verifica que nada más dependía)

**Interfaces:**
- Consumes: Task 1 (signals ya no lee `macro_blocks_*`).
- Produces: `MarketState` sin `macro_blocks_longs`/`macro_blocks_shorts`; `main.run()` sin `MacroFilter`.

- [ ] **Step 1: Test failing-first (en `tests/test_state.py`)**

```python
def test_state_has_no_macro_gate_fields():
    state = MarketState()
    assert not hasattr(state, "macro_blocks_longs")
    assert not hasattr(state, "macro_blocks_shorts")
```

Run: `.venv/bin/python -m pytest tests/test_state.py -v -k macro` → FAIL.

- [ ] **Step 2: Eliminar el módulo y sus referencias**

1. `git rm context.py tests/test_context.py`
2. `main.py`: borrar `from context import MacroFilter`, la línea `macro = MacroFilter(state)` y sacar `macro.run(),` del `asyncio.gather` (quedan `feed.connect()` y `notifier.run()`).
3. `state.py`: borrar el bloque "Macro context gates" (los dos campos).
4. `config.py`: borrar `CORRELATION_BLOCK_THRESHOLD` y `MACRO_UPDATE_SECONDS` (y el comentario de sección).
5. `requirements.txt`: borrar la línea `yfinance>=0.2.40`.

- [ ] **Step 3: Barrido**

```bash
grep -rn "MacroFilter\|macro_blocks\|yfinance\|CORRELATION_BLOCK\|MACRO_UPDATE" --include="*.py" . | grep -v .venv | grep -v docs/
```

Expected: cero resultados (si `backtest_feed.py` o `notifications.py` mencionan macro, borrar esas referencias también).

- [ ] **Step 4: Suite verde + commit**

```bash
.venv/bin/python -m pytest -q
git add -A
git commit -m "Remove the BTC-SPY macro filter (unmeasurable in backtest, fragile dependency)"
```

---

### Task 3: Retirar el imbalance del order book (conservando el top-of-book)

El stream de depth sigue: alimenta `last_bid`/`last_ask`/`spread` (los usan el gate de spread y las entradas maker). Muere solo la señal de imbalance por profundidad y su estado.

**Files:**
- Modify: `order_flow.py:49-93` (borrar sección), `data_feed.py:158-170`, `state.py:57-67,124`, `config.py:35-37,62`
- Test: `tests/test_order_flow.py`, `tests/test_data_feed.py`, `tests/test_state.py`

**Interfaces:**
- Consumes: Task 1 (signals ya no llama `get_book_imbalance`).
- Produces: `data_feed._handle_depth` que solo actualiza top-of-book; `state` sin `ob_snapshots`; `order_flow` solo con CVD.

- [ ] **Step 1: Tests failing-first**

En `tests/test_state.py`:

```python
def test_state_has_no_order_book_snapshot_buffer():
    state = MarketState()
    assert not hasattr(state, "ob_snapshots")
```

En `tests/test_data_feed.py`, agregar (adaptando el helper de construcción del feed que ya usa ese archivo):

```python
def test_handle_depth_updates_top_of_book_only():
    state = MarketState()
    feed = DataFeed(state)
    payload = {"bids": [["100.0", "2.0"], ["99.5", "1.0"]],
               "asks": [["100.5", "3.0"], ["101.0", "1.0"]]}
    asyncio.run(feed._handle_depth(payload))
    assert state.last_bid == 100.0
    assert state.last_ask == 100.5
    assert state.spread == pytest.approx(0.5)
```

Run: `.venv/bin/python -m pytest tests/test_state.py tests/test_data_feed.py -v -k "order_book or depth"` → FAIL.

- [ ] **Step 2: Implementar**

1. `order_flow.py`: borrar la sección "# --- Order book ---" completa (`_averaged_bid_ask_volume`, `get_book_imbalance`) y los imports que quedan sin uso (`OB_SNAPSHOTS`, `OB_IMBALANCE_RATIO`, `BookSnapshot`, `List`, `Tuple` si corresponde).
2. `data_feed.py` — `_handle_depth` queda:

```python
    async def _handle_depth(self, d: dict) -> None:
        bids = d.get("bids") or []
        asks = d.get("asks") or []
        if bids and asks:
            self.state.last_bid = float(bids[0][0])
            self.state.last_ask = float(asks[0][0])
            self.state.spread = self.state.last_ask - self.state.last_bid
```

   Borrar también la maquinaria de `_orderbook_handlers`/`on_orderbook` si `grep -rn "on_orderbook" --include="*.py" . | grep -v .venv` muestra que nadie la consume, y los imports de `BookSnapshot`/`OrderBookLevel`.
3. `state.py`: borrar `OrderBookLevel`, `BookSnapshot`, el campo `ob_snapshots` y el import de `OB_SNAPSHOT_BUFFER`.
4. `config.py`: borrar `OB_SNAPSHOTS`, `OB_IMBALANCE_RATIO` (sección "Order book anti-spoofing") y `OB_SNAPSHOT_BUFFER` de los buffers.
5. `tests/test_order_flow.py`: borrar los tests de imbalance/snapshots (los de CVD quedan). `tests/test_data_feed.py`: actualizar los tests de depth existentes al nuevo comportamiento.

- [ ] **Step 3: Barrido + suite + commit**

```bash
grep -rn "ob_snapshots\|BookSnapshot\|OrderBookLevel\|get_book_imbalance\|OB_IMBALANCE\|OB_SNAPSHOT" --include="*.py" . | grep -v .venv
.venv/bin/python -m pytest -q
git add -A
git commit -m "Remove order-book imbalance signal; depth stream now feeds top-of-book only"
```

---

### Task 4: Cierre de la limpieza — nota B4, README y smoke de 3 meses

**Files:**
- Modify: `safety.py:82` (comentario), `README.md`
- No new tests (verificación por corrida).

**Interfaces:**
- Consumes: Tasks 1-3 completas.
- Produces: rama con la limpieza verificada de punta a punta (backtest 3 meses = 0 señales, 0 trades).

- [ ] **Step 1: Comentario B4 en `safety.py`**

Encima de la línea `daily_loss_breached = ...` dentro de `after_trade_closed`:

```python
    # NOTE: pnl_today is REALIZED PnL only. This is safe today because the bot
    # holds at most one position and this check runs at full close (no open
    # position exists here, so unrealized PnL is zero by construction), and
    # new entries are blocked while any position or pending entry exists.
    # If multi-position support or force-close-on-kill is ever added, this
    # check MUST switch to total equity (balance + unrealized).
```

- [ ] **Step 2: README honesto**

En `README.md`, en la sección que describe la estrategia, reemplazar la descripción de la señal de entrada por:

```markdown
**Current signal status: no entry trigger is adopted.** The original squeeze
hypothesis was rejected with pre-registered criteria after a clean ablation
(`backtest_runs/ablation-2026-07-14.md`); the bot deliberately does not trade
until a new signal passes the base-rate studies and the ablation harness
(see `docs/superpowers/specs/2026-07-14-ciclo-limpieza-y-estudios-tasa-base-design.md`).
Risk management, execution (post-only maker entries), safety rails and the
backtest harness remain fully operational.
```

- [ ] **Step 3: Barrido global de símbolos muertos**

```bash
grep -rn "ENTRY_VARIANT\|squeeze_direction\|squeeze_broken\|MacroFilter\|get_book_imbalance\|ob_snapshots" --include="*.py" . | grep -v .venv
```

Expected: cero resultados.

- [ ] **Step 4: Smoke backtest de 3 meses (criterio de aceptación de la spec)**

```bash
.venv/bin/python backtest.py --start 2026-04-01 --end 2026-07-01 --label limpieza-smoke
```

Expected (~11 min): termina sin excepción, `Trades: 0`, `signals_fired = 0` en el summary, y `disabled_gates: ["cvd"]` en el meta de la corrida.

- [ ] **Step 5: Suite completa + commit**

```bash
.venv/bin/python -m pytest -q
git add safety.py README.md
git commit -m "Document the single-position kill-switch invariant and the no-trigger state"
```

---

### Task 5: Descargador de funding rate (`funding_history.py` nuevo)

Dumps mensuales verificados (2026-07-14): `https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2020-01.zip` … `2026-06.zip`. Formato CSV con posible fila de header; columnas esperadas `calc_time,funding_interval_hours,last_funding_rate` (verificar contra un archivo real en el Step 3 y ajustar el parser si difiere — el test debe usar líneas REALES copiadas del dump).

**Files:**
- Create: `funding_history.py`
- Test: `tests/test_funding_history.py`

**Interfaces:**
- Consumes: patrón de `download_history.py` (reintentos, `DayNotAvailable`→`MonthNotAvailable`, escritura atómica como `trade_cache.write_day`).
- Produces (Task 7/9-10 consumen):

```python
# funding_history.py
def build_url(symbol: str, month: str) -> str            # month = "YYYY-MM"
def parse_funding_csv(fileobj) -> list[list]             # [[ts_ms, rate], ...] ordenado
def cache_path(symbol: str) -> str                       # backtest_cache/{symbol}_funding.json.gz
def read_funding(symbol: str) -> list[list]              # [] si no existe
def download_range(symbol: str, start_month: str, end_month: str, fetcher=None) -> dict
# CLI: .venv/bin/python funding_history.py --symbol BTCUSDT --start 2020-01 --end 2026-07
```

`download_range` procesa mes a mes: baja un zip, parsea, mergea contra el cache existente (dedupe por ts, sort) y escribe; nunca acumula más de un mes sin escribir. El cache entero de funding cabe de sobra en RAM (~7k filas/símbolo): un solo `.json.gz` por símbolo con filas `[ts_ms, rate]`.

- [ ] **Step 1: Tests failing-first**

```python
import gzip
import json

import pytest

import funding_history
from funding_history import build_url, parse_funding_csv


def test_build_url():
    assert build_url("BTCUSDT", "2020-01") == (
        "https://data.binance.vision/data/futures/um/monthly/"
        "fundingRate/BTCUSDT/BTCUSDT-fundingRate-2020-01.zip"
    )


def test_parse_funding_csv_skips_header_and_sorts():
    lines = [
        "calc_time,funding_interval_hours,last_funding_rate",
        "1577865600000,8,0.00010000",
        "1577836800000,8,-0.00025000",
    ]
    rows = parse_funding_csv(iter(lines))
    assert rows == [[1577836800000, -0.00025], [1577865600000, 0.0001]]


def test_parse_funding_csv_tolerates_microsecond_timestamps():
    rows = parse_funding_csv(iter(["1577836800000000,8,0.0001"]))
    assert rows == [[1577836800000, 0.0001]]


def test_download_range_merges_and_dedupes(tmp_path, monkeypatch):
    monkeypatch.setattr(funding_history, "CACHE_DIR", str(tmp_path))
    payload_by_url = {}

    def fake_fetch(url):
        return payload_by_url[url]

    payload_by_url[build_url("BTCUSDT", "2020-01")] = _zip_with(
        "BTCUSDT-fundingRate-2020-01.csv",
        "1577836800000,8,0.0001\n1577865600000,8,0.0002\n",
    )
    counts = funding_history.download_range("BTCUSDT", "2020-01", "2020-02", fetcher=fake_fetch)
    assert counts["downloaded"] == 1
    assert funding_history.read_funding("BTCUSDT") == [
        [1577836800000, 0.0001], [1577865600000, 0.0002],
    ]
    # re-run: idempotent
    counts = funding_history.download_range("BTCUSDT", "2020-01", "2020-02", fetcher=fake_fetch)
    assert funding_history.read_funding("BTCUSDT") == [
        [1577836800000, 0.0001], [1577865600000, 0.0002],
    ]


def _zip_with(name: str, content: str) -> bytes:
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, content)
    return buf.getvalue()
```

Run → FAIL (`ModuleNotFoundError: funding_history`).

- [ ] **Step 2: Implementar `funding_history.py`**

Estructura (siguiendo `download_history.py`; `CACHE_DIR = "backtest_cache"` como constante de módulo para monkeypatch):

```python
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
```

Run tests → PASS.

- [ ] **Step 3: Descarga real + verificación de paridad contra la API REST**

```bash
.venv/bin/python funding_history.py --symbol BTCUSDT --start 2020-01 --end 2026-08
.venv/bin/python funding_history.py --symbol ETHUSDT --start 2020-01 --end 2026-08
```

Expected: ~78 meses c/u, `failed: 0` (meses futuros: `missing`, aceptable). Verificar el formato real: si la primera columna del CSV real no es el timestamp o la última no es el rate, ajustar `parse_funding_csv` Y el test con líneas reales del dump.

Paridad (muestra): comparar los últimos 30 días contra REST —

```bash
.venv/bin/python - <<'EOF'
import json, urllib.request
import funding_history
rest = json.load(urllib.request.urlopen(
    "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=90"))
# Binance a veces reporta fundingTime con unos ms de deriva: comparar por hora redondeada
cache = {round(r[0] / 3_600_000): r[1] for r in funding_history.read_funding("BTCUSDT")}
hits = sum(1 for r in rest
           if abs(cache.get(round(int(r["fundingTime"]) / 3_600_000), 9) - float(r["fundingRate"])) < 1e-9)
print(f"match {hits}/{len(rest)}")
EOF
```

Expected: match ≥ 85/90 (los últimos registros pueden no estar aún en el dump mensual — documentar el número en el commit).

- [ ] **Step 4: Commit**

```bash
git add funding_history.py tests/test_funding_history.py
git commit -m "Add monthly funding-rate downloader with compact per-symbol cache"
```

---

### Task 6: Descargador de klines 15m multi-año (`klines_history.py` nuevo)

Dumps mensuales: `https://data.binance.vision/data/futures/um/monthly/klines/{SYMBOL}/15m/{SYMBOL}-15m-{YYYY-MM}.zip`. CSV de 12 columnas (open_time, open, high, low, close, volume, close_time, quote_volume, count, taker_buy_base, taker_buy_quote, ignore), posible header, timestamps en µs en dumps recientes. Se guarda `[open_time_ms, open, high, low, close, volume, taker_buy_base]` — `taker_buy_base` da el flujo agresor por vela sin necesidad de ticks (lo usa C3).

**Files:**
- Create: `klines_history.py`
- Test: `tests/test_klines_history.py`

**Interfaces:**
- Consumes: patrón de Task 5.
- Produces (Tasks 7/9/10/11 consumen):

```python
# klines_history.py
def build_url(symbol: str, month: str) -> str
def parse_klines_csv(fileobj) -> list[list]        # [[ts_ms,o,h,l,c,vol,taker_buy], ...]
def month_cache_path(symbol: str, month: str) -> str  # backtest_cache/{symbol}_klines15m_{YYYY-MM}.json.gz
def read_month(symbol: str, month: str) -> Optional[list[list]]
def download_range(symbol: str, start_month: str, end_month: str, fetcher=None) -> dict
# CLI: .venv/bin/python klines_history.py --symbol BTCUSDT --start 2020-01 --end 2026-08
```

- [ ] **Step 1: Tests failing-first**

```python
import pytest

import klines_history
from klines_history import build_url, parse_klines_csv


def test_build_url():
    assert build_url("ETHUSDT", "2023-05") == (
        "https://data.binance.vision/data/futures/um/monthly/"
        "klines/ETHUSDT/15m/ETHUSDT-15m-2023-05.zip"
    )


def test_parse_klines_csv_extracts_compact_row_and_skips_header():
    lines = [
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore",
        "1577836800000,7189.43,7190.52,7177.00,7182.44,246.092,1577837699999,1767430.35,2135,113.680,816482.71,0",
    ]
    rows = parse_klines_csv(iter(lines))
    assert rows == [[1577836800000, 7189.43, 7190.52, 7177.0, 7182.44, 246.092, 113.68]]


def test_parse_klines_csv_converts_microsecond_open_time():
    rows = parse_klines_csv(iter([
        "1577836800000000,1,2,0.5,1.5,10,1577837699999999,15,3,4,6,0",
    ]))
    assert rows[0][0] == 1577836800000


def test_month_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_history, "CACHE_DIR", str(tmp_path))
    rows = [[1577836800000, 1.0, 2.0, 0.5, 1.5, 10.0, 4.0]]
    klines_history._write_month("BTCUSDT", "2020-01", rows)
    assert klines_history.read_month("BTCUSDT", "2020-01") == rows
    assert klines_history.read_month("BTCUSDT", "2020-02") is None
```

Run → FAIL.

- [ ] **Step 2: Implementar**

Mismo esqueleto que `funding_history.py` (reusar `_http_get`, `_iter_months`, `MonthNotAvailable`, reintentos — importándolos desde `funding_history` para no duplicar: `from funding_history import MonthNotAvailable, _http_get, _iter_months`). Diferencias:

```python
CACHE_DIR = "backtest_cache"
BASE_URL = "https://data.binance.vision/data/futures/um/monthly/klines"
_MICROSECOND_THRESHOLD = 100_000_000_000_000


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
            continue  # header
        if ts > _MICROSECOND_THRESHOLD:
            ts //= 1000
        rows.append([ts, float(rec[1]), float(rec[2]), float(rec[3]),
                     float(rec[4]), float(rec[5]), float(rec[9])])
    rows.sort(key=lambda r: r[0])
    return rows
```

`download_range` escribe cada mes a su propio archivo (`_write_month` con escritura atómica igual que `trade_cache.write_day`) y saltea meses ya cacheados (`read_month` no-None → "cached").

- [ ] **Step 3: Descarga real (los 4 juegos, uno por vez)**

```bash
.venv/bin/python klines_history.py --symbol BTCUSDT --start 2020-01 --end 2026-08
.venv/bin/python klines_history.py --symbol ETHUSDT --start 2020-01 --end 2026-08
```

Expected: ~78 meses c/u (~300 KB/mes), `failed: 0`. Si el CSV real difiere del layout asumido (columna 9 no es taker_buy_base), corregir parser + test con una línea real.

- [ ] **Step 4: Paridad doble**

(a) Contra REST, un mes de muestra:

```bash
.venv/bin/python - <<'EOF'
import json, urllib.request
import klines_history
cached = klines_history.read_month("BTCUSDT", "2026-05")
rest = json.load(urllib.request.urlopen(
    "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=15m"
    "&startTime=1777593600000&limit=1500"))  # 2026-05-01T00:00:00Z
by_ts = {r[0]: r for r in cached}
sample = [k for k in rest if int(k[0]) in by_ts][:500]
bad = [k for k in sample if abs(float(k[4]) - by_ts[int(k[0])][4]) > 1e-6]
print(f"closes match: {len(sample) - len(bad)}/{len(sample)}")
EOF
```

Expected: 500/500.

(b) Contra los ticks propios (valida las columnas de volumen/flujo): reconstruir 3 días de barras 15m desde `trade_cache` y comparar contra el cache de klines —

```bash
.venv/bin/python - <<'EOF'
import trade_cache, klines_history
rows = klines_history.read_month("BTCUSDT", "2026-05")
by_ts = {r[0]: r for r in rows}
for day in ("2026-05-05", "2026-05-06", "2026-05-07"):
    ticks = trade_cache.read_day(day)
    bars = {}
    for ts, price, qty, is_sell in ticks:
        b = ts - ts % 900_000
        o = bars.setdefault(b, [0.0, 0.0])  # [volume, taker_buy]
        o[0] += qty
        if not is_sell:
            o[1] += qty
    diffs = [abs(by_ts[b][5] - v[0]) / max(v[0], 1e-9) for b, v in bars.items() if b in by_ts]
    print(day, f"bars={len(diffs)} max_vol_diff={max(diffs):.4%}")
EOF
```

Expected: `max_vol_diff` < 1% en los 3 días (aggTrades ≈ klines; documentar los números reales en el commit).

- [ ] **Step 5: Commit**

```bash
git add klines_history.py tests/test_klines_history.py
git commit -m "Add multi-year 15m klines downloader with per-month cache and taker flow column"
```

---

### Task 7: Librería de estudios (`estudios/` nueva) con candado de verificación

**Files:**
- Create: `estudios/__init__.py` (vacío), `estudios/nucleo.py`, `estudios/reporte.py`
- Test: `tests/test_estudios_nucleo.py`, `tests/test_estudios_reporte.py`

**Interfaces:**
- Consumes: `klines_history.read_month`, `funding_history.read_funding`.
- Produces (los tres estudios consumen EXACTAMENTE esto):

```python
# estudios/nucleo.py
CORTE_VERIFICACION_MS = 1735689600000  # 2025-01-01T00:00:00Z

def cargar_klines(symbol: str, start_month: str, end_month: str) -> list[list]
    # concatena meses cacheados en orden; error claro si falta un mes intermedio

def ventana(rows: list[list], modo: str, corte_ms: int = CORTE_VERIFICACION_MS,
            verificacion_habilitada: bool = False) -> list[list]
    # modo "calibracion": filas con ts < corte_ms
    # modo "verificacion": exige verificacion_habilitada=True o ValueError
    #   ("verification window is locked; run with --verificacion")

def retorno_forward(closes: list[float], i: int, horizonte_barras: int) -> Optional[float]
    # (closes[i+h] - closes[i]) / closes[i]; None si i+h fuera de rango

def percentil_rodante(valores: list[float], i: int, ventana_n: int, valor: float) -> Optional[float]
    # fracción de las ventana_n observaciones ANTERIORES a i que son < valor;
    # None si no hay ventana_n previas (sin lookahead: excluye la posición i)

def resumen(muestras: list[float]) -> dict
    # {"n", "media", "mediana", "hit_rate"}  (hit_rate = fracción > 0)

# estudios/reporte.py
def escribir_reporte(nombre: str, preregistro: dict, celdas: int,
                     resultados: dict, base_dir: str = "backtest_runs/estudios") -> str
    # crea <base_dir>/<UTC yyyy-mm-dd_HH-MM-SS>_<nombre>/ con resultados.json y
    # reporte.md; el md SIEMPRE arranca con el bloque de pre-registro y el
    # número de celdas miradas; devuelve la ruta del directorio
```

- [ ] **Step 1: Tests failing-first de `nucleo` (completos)**

```python
import pytest

from estudios.nucleo import (
    CORTE_VERIFICACION_MS,
    percentil_rodante,
    resumen,
    retorno_forward,
    ventana,
)


def _row(ts_ms, close=100.0):
    return [ts_ms, close, close, close, close, 1.0, 0.5]


def test_ventana_calibracion_filtra_por_corte():
    rows = [_row(CORTE_VERIFICACION_MS - 1), _row(CORTE_VERIFICACION_MS)]
    assert ventana(rows, "calibracion") == [rows[0]]


def test_ventana_verificacion_bloqueada_por_default():
    with pytest.raises(ValueError, match="locked"):
        ventana([_row(CORTE_VERIFICACION_MS)], "verificacion")


def test_ventana_verificacion_con_flag():
    rows = [_row(CORTE_VERIFICACION_MS - 1), _row(CORTE_VERIFICACION_MS)]
    assert ventana(rows, "verificacion", verificacion_habilitada=True) == [rows[1]]


def test_retorno_forward_y_borde():
    closes = [100.0, 101.0, 102.0]
    assert retorno_forward(closes, 0, 2) == pytest.approx(0.02)
    assert retorno_forward(closes, 1, 2) is None


def test_percentil_rodante_excluye_la_posicion_actual():
    vals = [1.0, 2.0, 3.0, 4.0, 10.0]
    # ventana = las 4 anteriores a i=4; 10.0 es mayor que todas
    assert percentil_rodante(vals, 4, 4, 10.0) == pytest.approx(1.0)
    assert percentil_rodante(vals, 3, 4, 4.0) is None  # solo 3 previas


def test_resumen():
    r = resumen([0.01, -0.02, 0.03])
    assert r["n"] == 3
    assert r["media"] == pytest.approx(0.00333, abs=1e-4)
    assert r["mediana"] == pytest.approx(0.01)
    assert r["hit_rate"] == pytest.approx(2 / 3)
```

Y de `reporte`:

```python
import json
import os

from estudios.reporte import escribir_reporte


def test_escribir_reporte_incluye_preregistro_y_celdas(tmp_path):
    ruta = escribir_reporte(
        "demo", {"umbral": "mediana >= 0.14%"}, celdas=12,
        resultados={"grupo": {"n": 3}}, base_dir=str(tmp_path),
    )
    md = open(os.path.join(ruta, "reporte.md")).read()
    assert "Pre-registro" in md and "mediana >= 0.14%" in md
    assert "Celdas miradas: 12" in md
    datos = json.load(open(os.path.join(ruta, "resultados.json")))
    assert datos["preregistro"]["umbral"] == "mediana >= 0.14%"
    assert datos["celdas"] == 12
```

Run → FAIL.

- [ ] **Step 2: Implementar `estudios/nucleo.py` y `estudios/reporte.py`**

`nucleo.py` (usar `statistics.median`/`fmean`; `cargar_klines` itera `_iter_months` de `funding_history` y levanta `ValueError(f"missing cached month {symbol} {month}")` si un mes intermedio no está). `reporte.py` arma el md con secciones fijas: título, `## Pre-registro` (dict volcado como lista `- clave: valor`), `Celdas miradas: N`, `## Resultados` (JSON pretty embebido en bloque de código). Sin librerías nuevas.

- [ ] **Step 3: Suite verde + commit**

```bash
.venv/bin/python -m pytest tests/test_estudios_nucleo.py tests/test_estudios_reporte.py -v
.venv/bin/python -m pytest -q
git add estudios/ tests/test_estudios_nucleo.py tests/test_estudios_reporte.py
git commit -m "Add study library: forward returns, rolling percentile, locked verification window, pre-registered reports"
```

---

### Task 8: Estudio C2 — sesión/hora del día (`estudios/estudio_sesion.py`)

Rol pre-registrado: **insumo, no señal** — sin umbral de adopción. 24 buckets de hora UTC × {hábil, finde} × 2 símbolos.

**Files:**
- Create: `estudios/estudio_sesion.py`
- Test: `tests/test_estudio_sesion.py`

**Interfaces:**
- Consumes: `cargar_klines`, `ventana`, `retorno_forward`, `resumen`, `escribir_reporte`.
- Produces: reporte en `backtest_runs/estudios/`; función pura `bucketear(rows) -> dict[(hora, es_finde)] -> list[int]` (índices de filas) para test.

- [ ] **Step 1: Test failing-first**

```python
from datetime import datetime, timezone

from estudios.estudio_sesion import bucketear


def _row_at(iso: str):
    ts = int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)
    return [ts, 100.0, 100.0, 100.0, 100.0, 1.0, 0.5]


def test_bucketear_por_hora_y_finde():
    rows = [
        _row_at("2026-01-05T14:00:00"),  # lunes 14 UTC
        _row_at("2026-01-10T14:00:00"),  # sábado 14 UTC
        _row_at("2026-01-05T15:00:00"),  # lunes 15 UTC
    ]
    b = bucketear(rows)
    assert b[(14, False)] == [0]
    assert b[(14, True)] == [1]
    assert b[(15, False)] == [2]
```

Run → FAIL.

- [ ] **Step 2: Implementar el script**

`bucketear` usa `datetime.fromtimestamp(ts/1000, tz=timezone.utc)` (`.hour`, `.weekday() >= 5`). El `main` del script:

```
argv: --modo {calibracion,verificacion} [--verificacion] --symbols BTCUSDT,ETHUSDT
1. per symbol: rows = ventana(cargar_klines(symbol, "2020-01", "2026-08"), modo,
   verificacion_habilitada=args.verificacion)
2. per bucket: muestras = retorno de la vela SIGUIENTE a cada fila del bucket
   (retorno_forward(closes, i, 1)); métricas = resumen(muestras) + media de
   |ret| + volumen medio
3. escribir_reporte(f"sesion-{modo}", preregistro, celdas=24*2*2, resultados)
   preregistro = {"rol": "insumo, sin umbral de adopcion (spec 2026-07-14)",
                  "split": "calibracion 2020-01->2024-12, verificacion 2025-01->presente",
                  "evento": "cada vela 15m, bucket hora UTC x habil/finde",
                  "metricas": "media, mediana, hit_rate, |ret| media, volumen medio"}
```

Guardas: el modo `verificacion` sin `--verificacion` debe morir con el ValueError del candado (comportamiento heredado de `ventana`, no reimplementar).

- [ ] **Step 3: Corrida de calibración (la única de esta task)**

```bash
.venv/bin/python -m estudios.estudio_sesion --modo calibracion --symbols BTCUSDT,ETHUSDT
```

Expected: reporte con 24×2 filas por símbolo, n por bucket ~3.500-4.500 (5 años de velas 15m / 48 buckets). NO correr `--modo verificacion` (Task 11 lo hace tras la revisión).

- [ ] **Step 4: Commit**

```bash
git add estudios/estudio_sesion.py tests/test_estudio_sesion.py backtest_runs/estudios/
git commit -m "Add session-of-day base-rate study (C2) and its calibration report"
```

---

### Task 9: Estudio C1 — funding extremo (`estudios/estudio_funding.py`)

La apuesta principal del ciclo. Umbrales de Global Constraints, verbatim en el pre-registro del reporte.

**Files:**
- Create: `estudios/estudio_funding.py`
- Test: `tests/test_estudio_funding.py`

**Interfaces:**
- Consumes: `read_funding`, `cargar_klines`, `ventana`, `percentil_rodante`, `retorno_forward`, `resumen`, `escribir_reporte`.
- Produces: reporte; funciones puras testeables:

```python
def detectar_eventos(funding: list[list]) -> list[tuple[int, str]]
    # [(indice_en_funding, "alta"|"baja"), ...] — cruces de ENTRADA a la cola:
    # extremo(i) = percentil_rodante(rates, i, 90, rates[i]) > 0.90 (alta)
    #              o < 0.10 (baja); evento si extremo(i) y no extremo(i-1)
def indexar_klines(rows: list[list]) -> dict[int, int]   # ts_ms -> indice
def retornos_firmados(eventos, funding, rows, horizonte_barras) -> list[float]
    # ancla: vela 15m cuyo ts == ts_funding - 900_000 (la que CIERRA en el
    # funding); si falta, saltear el evento. Firma: cola alta -> tesis SHORT
    # (retorno * -1), cola baja -> tesis LONG (retorno * +1)
```

- [ ] **Step 1: Tests failing-first**

```python
import pytest

from estudios.estudio_funding import detectar_eventos, retornos_firmados


def _funding_series():
    # 92 lecturas: 90 neutras en 0.0001, luego un salto extremo sostenido
    rows = [[i * 28_800_000, 0.0001 + (i % 3) * 1e-6] for i in range(90)]
    rows.append([90 * 28_800_000, 0.01])   # cruce de entrada a cola alta
    rows.append([91 * 28_800_000, 0.011])  # sigue extremo: NO es evento nuevo
    return rows


def test_detectar_eventos_solo_el_cruce_de_entrada():
    eventos = detectar_eventos(_funding_series())
    assert eventos == [(90, "alta")]


def test_detectar_eventos_ignora_sin_ventana_completa():
    corta = _funding_series()[:50]
    assert detectar_eventos(corta) == []


def test_retornos_firmados_cola_alta_es_tesis_short():
    funding = _funding_series()
    ts_evento = funding[90][0]
    # klines 15m: la vela que cierra en el funding abre 900_000 antes
    rows = []
    for k in range(-1, 40):
        ts = ts_evento - 900_000 + k * 900_000
        close = 100.0 if k <= 0 else 90.0  # el precio CAE tras el evento
        rows.append([ts, close, close, close, close, 1.0, 0.5])
    firmados = retornos_firmados([(90, "alta")], funding, rows, horizonte_barras=32)
    assert len(firmados) == 1
    assert firmados[0] == pytest.approx(0.10)  # caida del 10% firmada positiva
```

Run → FAIL.

- [ ] **Step 2: Implementar**

`detectar_eventos` recorre `i` de 90 a len-1 con `percentil_rodante(rates, i, 90, rates[i])`; guarda el estado extremo del `i-1` para detectar cruces. `retornos_firmados` ancla con `indexar_klines` y `retorno_forward(closes, idx, h)`. El `main`:

```
argv: --modo {calibracion,verificacion} [--verificacion] --symbols BTCUSDT,ETHUSDT
horizontes: {"8h": 32, "24h": 96, "72h": 288}
1. per symbol: funding filtrado por ventana(modo) ANTES de detectar eventos
   (los 90 previos al corte pueden quedar fuera: aceptado y documentado en el
   reporte — la primera ventana de verificación arranca 30 dias adentro).
2. resultados[symbol][cola][horizonte] = resumen(retornos_firmados(...))
3. chequeo n>=150 por cola (calibracion): si falla, el reporte marca la celda
   "n insuficiente — solo descartar o extender datos".
4. escribir_reporte(f"funding-{modo}", preregistro, celdas=12, resultados)
   preregistro (verbatim de la spec): percentiles 90/10 sobre 90 obs,
   evento = cruce de entrada, umbral adopcion = "mediana firmada >= 0.14% Y
   media mismo signo Y hit_rate > 50% en calibracion, sostenido en
   verificacion (mismo signo, magnitud >= 1/2 de calibracion)", solo BTC
   adopta/veta; ETH es robustez.
```

- [ ] **Step 3: Corrida de calibración**

```bash
.venv/bin/python -m estudios.estudio_funding --modo calibracion --symbols BTCUSDT,ETHUSDT
```

Expected: reporte con n por cola (≥150 esperado con 5 años: ~5.400 lecturas de funding por símbolo). NO correr verificación.

- [ ] **Step 4: Commit**

```bash
git add estudios/estudio_funding.py tests/test_estudio_funding.py backtest_runs/estudios/
git commit -m "Add funding-extreme base-rate study (C1) and its calibration report"
```

---

### Task 10: Estudio C3 — reversión post-movimiento extremo (`estudios/estudio_cascadas.py`)

Usa el cache de klines 15m (columna `taker_buy` validada contra ticks en Task 6 Step 4b — mismo agregado, sin re-leer 91 días de ticks).

**Files:**
- Create: `estudios/estudio_cascadas.py`
- Test: `tests/test_estudio_cascadas.py`

**Interfaces:**
- Consumes: `cargar_klines`, `retorno_forward`, `resumen`, `escribir_reporte` (el split de C3 NO usa `CORTE_VERIFICACION_MS`: usa corte propio 2026-06-01, pasado como `corte_ms` a `ventana`).
- Produces: reporte; función pura:

```python
def detectar_cascadas(rows: list[list]) -> list[tuple[int, int]]
    # [(indice, direccion)] con direccion +1 (movida alcista) o -1 (bajista):
    # ret[i] = (c[i]-c[i-1])/c[i-1]; sigma = stdev(ret[i-96:i]); |ret[i]| > 3*sigma
    # y flujo unidireccional: |2*taker_buy[i] - vol[i]| / vol[i] >= 0.6
    # (equivale a |buy-sell|/(buy+sell) >= 0.6); requiere i >= 97 y vol > 0
```

- [ ] **Step 1: Test failing-first**

```python
import pytest

from estudios.estudio_cascadas import detectar_cascadas


def _rows_con_cascada():
    rows = []
    price = 100.0
    for i in range(120):
        # ruido suave +-0.05%, volumen balanceado (flujo 0)
        price *= 1.0005 if i % 2 == 0 else 0.9995
        rows.append([i * 900_000, price, price, price, price, 10.0, 5.0])
    # vela 120: caida del 3% con flujo vendedor unidireccional (taker_buy=1/10)
    crash = rows[-1][4] * 0.97
    rows.append([120 * 900_000, crash, crash, crash, crash, 10.0, 1.0])
    return rows


def test_detectar_cascadas_encuentra_la_caida():
    eventos = detectar_cascadas(_rows_con_cascada())
    assert eventos == [(120, -1)]


def test_sin_flujo_unidireccional_no_hay_evento():
    rows = _rows_con_cascada()
    rows[-1][6] = 5.0  # flujo balanceado
    assert detectar_cascadas(rows) == []
```

Run → FAIL.

- [ ] **Step 2: Implementar**

`detectar_cascadas` con `statistics.stdev` sobre los 96 retornos previos. El `main`:

```
argv: --modo {calibracion,verificacion} [--verificacion]
datos: cargar_klines("BTCUSDT", "2026-03", "2026-08") recortado a
       2026-04-01 -> 2026-07-01 (el mes previo solo alimenta la ventana de
       sigma; los eventos se cuentan desde 2026-04-01)
corte: ventana(rows_evento, modo, corte_ms=1780272000000)  # 2026-06-01T00:00:00Z
horizontes: {"1h": 4, "4h": 16, "8h": 32}
firma: retorno forward CONTRA la direccion del movimiento
       (firmado = -direccion * retorno_forward(...))
reporte: preregistro con la regla dura "n_total < 50 -> conclusiones
         permitidas: solo 'descartar' o 'extender datos'" y el conteo real;
         celdas = 2 colas x 3 horizontes = 6
nota en el reporte: ETH sin ticks locales queda fuera de C3 (spec).
```

- [ ] **Step 3: Corrida de calibración**

```bash
.venv/bin/python -m estudios.estudio_cascadas --modo calibracion
```

Expected: n chico (decenas); el reporte imprime la regla de n<50. NO correr verificación.

- [ ] **Step 4: Suite completa + commit**

```bash
.venv/bin/python -m pytest -q
git add estudios/estudio_cascadas.py tests/test_estudio_cascadas.py backtest_runs/estudios/
git commit -m "Add cascade-reversion base-rate study (C3) and its calibration report"
```

---

### Task 11: CHECKPOINT de revisión + corridas de verificación + veredicto

**Esta task empieza con una pausa obligatoria:** los scripts de estudio deben estar revisados y congelados ANTES de abrir la ventana de verificación (spec, sección Testing). No ejecutar el Step 2 hasta que la revisión de código de las Tasks 7-10 esté aprobada.

**Files:**
- Modify: `docs/mejoras-propuestas.md` (nueva sección de estado)
- Create: `backtest_runs/estudios/veredicto-2026-07.md` (a mano, con los números reales)

**Interfaces:**
- Consumes: reportes de calibración (Tasks 8-10) + scripts congelados.
- Produces: veredicto del ciclo contra los criterios pre-registrados de la spec.

- [ ] **Step 1: Confirmar revisión aprobada de Tasks 7-10 (gate humano/reviewer del flujo SDD)**

- [ ] **Step 2: Corridas de verificación (una sola vez, sin re-tocar los scripts)**

```bash
.venv/bin/python -m estudios.estudio_sesion   --modo verificacion --verificacion --symbols BTCUSDT,ETHUSDT
.venv/bin/python -m estudios.estudio_funding  --modo verificacion --verificacion --symbols BTCUSDT,ETHUSDT
.venv/bin/python -m estudios.estudio_cascadas --modo verificacion --verificacion
```

Si después de estas corridas aparece un bug en un script: se arregla, se re-corre TODO (calibración y verificación) y el veredicto lo declara explícitamente ("re-corrida post-fix", como se hizo con la ablación del trail).

- [ ] **Step 3: Redactar `backtest_runs/estudios/veredicto-2026-07.md`**

Estructura fija: tabla por estudio (calibración vs verificación, todas las celdas), evaluación textual contra el umbral pre-registrado de la spec COPIADO verbatim, y una de tres conclusiones por estudio: PASA / NO PASA / N INSUFICIENTE. Cierre: aplicar el "Criterio de salida del ciclo" de la spec (si C1 pasa → diseño de señal; si todo falla → decisión de Guille entre plan B momentum o congelar — NO decidir en el veredicto, solo dejar planteada la bifurcación).

- [ ] **Step 4: Actualizar `docs/mejoras-propuestas.md`**

Agregar al final:

```markdown
**Ciclo limpieza + estudios de tasa base (2026-07, spec:
`docs/superpowers/specs/2026-07-14-ciclo-limpieza-y-estudios-tasa-base-design.md`):**
pipeline limpiado (squeeze retirado como disparador, gates reducidos a
spread/trend_1h con cvd desactivado por default, macro y ob_imbalance
eliminados, invariante backtest=live como test permanente); datos extendidos
(funding 2020→hoy y klines 15m multi-año, BTC+ETH); estudios C2/C1/C3
corridos con pre-registro. Veredicto: `backtest_runs/estudios/veredicto-2026-07.md`.
[Completar con el resultado real: qué pasó/falló y cuál es el siguiente paso.]
```

(El corchete se reemplaza por el resultado real — es el único texto que depende de los números.)

- [ ] **Step 5: Suite completa + commit final**

```bash
.venv/bin/python -m pytest -q
git add backtest_runs/estudios/ docs/mejoras-propuestas.md
git commit -m "Run verification windows for the three base-rate studies and record the cycle verdict"
```

---

## Notas de diseño para el ejecutor

1. **El candado de verificación es sagrado.** Ningún script corre `--modo verificacion` antes del checkpoint de la Task 11. Si durante el desarrollo necesitás datos para probar el flujo, usá calibración o fixtures sintéticos.
2. **Los umbrales pre-registrados no se ajustan al ver datos.** Si un resultado queda "casi" en el umbral, el veredicto es NO PASA — la spec lo dice y la historia del proyecto (dos señales muertas medidas honestamente) es la razón.
3. **Nada de pandas/numpy.** Los volúmenes (≤230k filas por símbolo) andan sobrados con listas y `statistics`. Mantiene requirements limpio y la VM tranquila.
4. **Un proceso pesado por vez** en descargas y corridas (VM de 4 cores/7.7 GB; lección del OOM 2026-07-13).
5. **taker_buy de klines ≡ agregado de ticks** — validado en Task 6 Step 4b antes de que C3 lo consuma. Si esa validación fallara (>1% de diferencia), C3 vuelve al plan original de agregar ticks día a día y hay que decírselo al supervisor.
6. **El bot queda sin operar a propósito.** Si algún test o corrida "espera trades", el test está mal, no el bot.
