# N1: dos variantes de entrada + ablation de gates (P0-8) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar las dos variantes de entrada (A: fade con tipo de nivel; B: confirmación de ruptura) y el harness de ablation de gates, correr la matriz de 12 corridas sobre abr–jun 2026 y producir el veredicto del criterio pre-registrado.

**Architecture:** Todo el cambio de señal vive en `signals.py` + `state.py` (variante seleccionable por parámetro de módulo, default = comportamiento actual). El backtest gana flags de CLI reproducibles que sobreescriben `config`/`signals` en runtime. Un runner nuevo (`run_ablation.py`) enumera la matriz, saltea corridas ya hechas y escribe el reporte con veredicto.

**Tech Stack:** Python 3, pytest, sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-07-12-n1-dos-variantes-ablation-design.md`

## Global Constraints

- Embudo pre-registrado para TODO el ablation: `SQUEEZE_COMPRESSION_ATR = 0.6`, `SQUEEZE_MIN_BARS = 2`.
- Criterio de adopción pre-registrado: corrida **base** rentable neta de fees en abr–jun 2026 con **≥ 30 trades**; si ambas pierden, ninguna se adopta.
- Defaults preservan el bot en vivo: `ENTRY_VARIANT = "fade"`, `DISABLED_GATES = set()`, umbrales de `config.py` sin tocar.
- Backtests SIEMPRE secuenciales (pico ~2.2 GB RAM por corrida; nunca en paralelo).
- Gates inertes en backtest: `macro`, `ob_imbalance` — no reciben corrida de ablation propia; se marcan `inert` en el reporte.
- TDD: test primero en cada task. Commit al final de cada task.
- Correr la suite completa (`pytest -q`) antes de cada commit.

---

### Task 1: `_nearest_key_level` devuelve el tipo de nivel

**Files:**
- Modify: `signals.py:15-21` (`_nearest_key_level`) y su único call site en `update_squeeze` (`signals.py:45`)
- Test: `tests/test_signals.py`

**Interfaces:**
- Produces: `_nearest_key_level(price: float, state: MarketState) -> Tuple[float, float, str]` — retorna `(level, distance, kind)` con `kind ∈ {"support", "resistance"}`. Lista vacía → `(0.0, inf, "support")`. Empate de distancia: gana el nivel coherente con el lado del precio (soporte ≤ precio, resistencia ≥ precio); si persiste el empate, soporte.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_signals.py` (importar `_nearest_key_level` desde `signals`):

```python
from signals import _nearest_key_level, check_entry_signal, update_squeeze


def test_nearest_key_level_reports_support_kind():
    state = MarketState()
    state.swing_lows.append(90.0)
    state.swing_highs.append(120.0)

    level, distance, kind = _nearest_key_level(95.0, state)

    assert (level, distance, kind) == (90.0, 5.0, "support")


def test_nearest_key_level_reports_resistance_kind():
    state = MarketState()
    state.swing_lows.append(50.0)
    state.swing_highs.append(110.0)

    level, distance, kind = _nearest_key_level(108.0, state)

    assert (level, distance, kind) == (110.0, 2.0, "resistance")


def test_nearest_key_level_empty_returns_support_placeholder():
    state = MarketState()

    level, distance, kind = _nearest_key_level(100.0, state)

    assert level == 0.0 and distance == float("inf") and kind == "support"


def test_nearest_key_level_tie_prefers_side_consistent_level():
    state = MarketState()
    state.swing_lows.append(110.0)   # soporte POR ENCIMA del precio: incoherente
    state.swing_highs.append(110.0)  # resistencia por encima: coherente

    level, distance, kind = _nearest_key_level(100.0, state)

    assert (level, kind) == (110.0, "resistance")


def test_nearest_key_level_tie_falls_back_to_support():
    state = MarketState()
    state.swing_lows.append(90.0)    # soporte por debajo: coherente
    state.swing_highs.append(110.0)  # resistencia por encima: coherente, misma distancia
    level, distance, kind = _nearest_key_level(100.0, state)

    assert (level, kind) == (90.0, "support")
```

- [ ] **Step 2: Verificar que fallan**

Run: `pytest tests/test_signals.py -k nearest_key_level -v`
Expected: FAIL (`too many values to unpack` o similar — hoy retorna 2 valores).

- [ ] **Step 3: Implementación mínima**

Reemplazar `_nearest_key_level` en `signals.py`:

```python
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
```

Y actualizar el call site en `update_squeeze` (sin cambiar la lógica todavía):

```python
    key_level, distance, level_kind = _nearest_key_level(state.last_price, state)
```

- [ ] **Step 4: Verificar que pasan y que no rompí nada**

Run: `pytest tests/test_signals.py -v && pytest -q`
Expected: PASS completo.

- [ ] **Step 5: Commit**

```bash
git add signals.py tests/test_signals.py
git commit -m "Track level kind (support/resistance) in _nearest_key_level"
```

---

### Task 2: Variante A — dirección del fade por tipo de nivel

**Files:**
- Modify: `signals.py:48-56` (bloque de armado en `update_squeeze`)
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: `_nearest_key_level(...) -> (level, distance, kind)` (Task 1).
- Produces: `update_squeeze` arma `state.squeeze_direction = LONG` solo sobre soporte con `last_price >= level`, `SHORT` solo bajo resistencia con `last_price <= level`; nivel incoherente → `in_squeeze = True` pero `squeeze_direction = None` (así la variante B de la Task 3 conserva la squeeze armada aunque el fade no tenga tesis).

- [ ] **Step 1: Escribir el test que falla**

```python
def test_update_squeeze_arms_without_direction_when_level_kind_is_incoherent():
    state = MarketState()
    state.atr = 10.0
    state.swing_highs.append(95.0)  # resistencia ya rota, quedó DEBAJO del precio
    state.last_price = 100.0

    for i in range(SQUEEZE_MIN_BARS):
        state.candles_15m.append(_candle(100, 101, 99, 100, i))
        update_squeeze(state)

    assert state.in_squeeze is True
    assert state.squeeze_direction is None
```

- [ ] **Step 2: Verificar que falla**

Run: `pytest tests/test_signals.py::test_update_squeeze_arms_without_direction_when_level_kind_is_incoherent -v`
Expected: FAIL — hoy asigna `LONG` por signo (`price > level`).

- [ ] **Step 3: Implementación mínima**

En `update_squeeze`, reemplazar la asignación de dirección:

```python
    if is_compressed and near_level:
        state.squeeze_bar_count += 1
        if state.squeeze_bar_count >= SQUEEZE_MIN_BARS:
            state.in_squeeze = True
            state.squeeze_reference_level = key_level
            # Fade thesis only makes sense against the level's real kind:
            # compressed on top of support → bounce up; under resistance → bounce down.
            if level_kind == "support" and state.last_price >= key_level:
                state.squeeze_direction = Side.LONG
            elif level_kind == "resistance" and state.last_price <= key_level:
                state.squeeze_direction = Side.SHORT
            else:
                state.squeeze_direction = None
```

Los tests existentes `test_update_squeeze_activates_with_short_direction_when_price_below_level` y `..._long_direction_when_price_above_level` ya usan `swing_highs` para el short y `swing_lows` para el long, así que siguen pasando sin cambios.

- [ ] **Step 4: Verificar**

Run: `pytest tests/test_signals.py -v && pytest -q`
Expected: PASS completo.

- [ ] **Step 5: Commit**

```bash
git add signals.py tests/test_signals.py
git commit -m "Variant A: fade direction requires coherent level kind"
```

---

### Task 3: Variante B — estado `squeeze_broken` con TTL y selector de variante

**Files:**
- Modify: `state.py` (campos nuevos en `MarketState`), `signals.py` (`update_squeeze`, `check_entry_signal`, nuevo parámetro de módulo `ENTRY_VARIANT`)
- Test: `tests/test_signals.py`

**Interfaces:**
- Produces:
  - Campos en `MarketState`: `squeeze_price_above_level: Optional[bool]` (lado del precio al armarse), `squeeze_broken: bool`, `squeeze_broken_direction: Optional[Side]`, `squeeze_broken_level: float`, `squeeze_broken_ttl: int`.
  - `signals.ENTRY_VARIANT: str = "fade"` — valores `"fade" | "break"`; el backtest lo sobreescribe (Task 5).
  - `signals._clear_broken(state) -> None` — limpia los 4 campos broken.
  - Semántica del TTL: la ruptura se detecta al cierre de la vela N (`squeeze_broken_ttl = 2`); en cada cierre posterior se decrementa ANTES de evaluar; al llegar a 0 se limpia. Ventana de entrada efectiva: cierres N y N+1. La entrada consume el estado.

- [ ] **Step 1: Escribir los tests que fallan**

```python
def _armed_squeeze_below_resistance() -> MarketState:
    """Squeeze armada contra resistencia en 110, precio en 108."""
    state = MarketState()
    state.atr = 10.0
    state.swing_highs.append(110.0)
    state.last_price = 108.0
    for i in range(SQUEEZE_MIN_BARS):
        state.candles_15m.append(_candle(108, 109, 107, 108, i))
        update_squeeze(state)
    assert state.in_squeeze is True
    return state


def test_break_above_resistance_sets_broken_state_long():
    state = _armed_squeeze_below_resistance()

    state.candles_15m.append(_candle(108, 120, 107, 115, 99))  # cierra ARRIBA de 110
    update_squeeze(state)

    assert state.squeeze_broken is True
    assert state.squeeze_broken_direction == Side.LONG
    assert state.squeeze_broken_level == 110.0
    assert state.squeeze_broken_ttl == 2
    assert state.in_squeeze is False  # la vela de ruptura sí resetea la squeeze


def test_break_below_support_sets_broken_state_short():
    state = MarketState()
    state.atr = 10.0
    state.swing_lows.append(90.0)
    state.last_price = 92.0
    for i in range(SQUEEZE_MIN_BARS):
        state.candles_15m.append(_candle(92, 93, 91, 92, i))
        update_squeeze(state)
    assert state.in_squeeze is True

    state.candles_15m.append(_candle(92, 93, 80, 85, 99))  # cierra DEBAJO de 90
    update_squeeze(state)

    assert state.squeeze_broken is True
    assert state.squeeze_broken_direction == Side.SHORT


def test_close_exactly_on_level_is_not_a_break():
    state = _armed_squeeze_below_resistance()

    state.candles_15m.append(_candle(108, 120, 107, 110.0, 99))  # cierre exacto en el nivel
    update_squeeze(state)

    assert state.squeeze_broken is False


def test_bounce_away_from_level_is_not_a_break():
    state = _armed_squeeze_below_resistance()

    state.candles_15m.append(_candle(108, 109, 90, 95, 99))  # se aleja SIN cruzar 110
    update_squeeze(state)

    assert state.squeeze_broken is False


def test_broken_state_expires_after_ttl():
    state = _armed_squeeze_below_resistance()
    state.candles_15m.append(_candle(108, 120, 107, 115, 99))
    update_squeeze(state)
    assert state.squeeze_broken is True

    state.candles_15m.append(_candle(115, 130, 114, 128, 100))  # N+1: decrementa a 1
    update_squeeze(state)
    assert state.squeeze_broken is True

    state.candles_15m.append(_candle(128, 140, 127, 138, 101))  # N+2: llega a 0, limpia
    update_squeeze(state)
    assert state.squeeze_broken is False
    assert state.squeeze_broken_direction is None


def _broken_long_setup_state() -> MarketState:
    state = _base_state(direction=Side.LONG)
    state.in_squeeze = False
    state.squeeze_direction = None
    state.squeeze_broken = True
    state.squeeze_broken_direction = Side.LONG
    state.squeeze_broken_level = 95.0
    state.squeeze_broken_ttl = 2
    return state


def test_break_variant_fires_on_broken_state_and_consumes_it():
    state = _broken_long_setup_state()
    signals.ENTRY_VARIANT = "break"

    assert check_entry_signal(state) == Side.LONG
    assert state.squeeze_broken is False  # consumida


def test_break_variant_ignores_plain_armed_squeeze():
    state = _base_state(direction=Side.LONG)  # in_squeeze pero sin break
    signals.ENTRY_VARIANT = "break"

    assert check_entry_signal(state) is None


def test_fade_variant_ignores_broken_state():
    state = _broken_long_setup_state()
    signals.ENTRY_VARIANT = "fade"

    assert check_entry_signal(state) is None
```

Agregar `import signals` al inicio del archivo de tests, y un teardown provisorio: al final de cada test que toca `signals.ENTRY_VARIANT`, restaurarlo no hace falta — en su lugar agregar YA el fixture autouse en `conftest.py` (raíz del repo):

```python
import config
import signals


@pytest.fixture(autouse=True)
def _reset_signal_globals():
    compression = config.SQUEEZE_COMPRESSION_ATR
    min_bars = config.SQUEEZE_MIN_BARS
    yield
    signals.ENTRY_VARIANT = "fade"
    config.SQUEEZE_COMPRESSION_ATR = compression
    config.SQUEEZE_MIN_BARS = min_bars
```

(Si `conftest.py` no importa `pytest` todavía, agregar `import pytest`.)

- [ ] **Step 2: Verificar que fallan**

Run: `pytest tests/test_signals.py -k "break or broken or bounce" -v`
Expected: FAIL con `AttributeError` (campos inexistentes en `MarketState`).

- [ ] **Step 3: Implementación**

En `state.py`, debajo del bloque "Volman squeeze state":

```python
    # Volman squeeze state
    in_squeeze: bool = False
    squeeze_bar_count: int = 0
    squeeze_reference_level: float = 0.0
    squeeze_direction: Optional[Side] = None
    squeeze_price_above_level: Optional[bool] = None

    # Break-confirmation state (variant B): survives the breakout candle
    squeeze_broken: bool = False
    squeeze_broken_direction: Optional[Side] = None
    squeeze_broken_level: float = 0.0
    squeeze_broken_ttl: int = 0
```

En `signals.py`, agregar el selector y el helper, y reestructurar `update_squeeze`:

```python
# Entry model variant: "fade" (bet on level rejection, pre-break) or "break"
# (enter on confirmed break of the squeeze level). Backtest overrides this;
# live default stays "fade".
ENTRY_VARIANT = "fade"


def _clear_broken(state: MarketState) -> None:
    state.squeeze_broken = False
    state.squeeze_broken_direction = None
    state.squeeze_broken_level = 0.0
    state.squeeze_broken_ttl = 0


def update_squeeze(state: MarketState) -> None:
    """
    Detect Volman-style "The Squeeze": price compressing in a tight range
    against a key support/resistance level, and track its resolution.

    Two downstream consumers:
      - fade variant: squeeze_direction is the bounce off the level's kind
        (support → LONG, resistance → SHORT); incoherent kind → no thesis.
      - break variant: when an armed squeeze closes across its reference
        level, squeeze_broken opens a 2-bar entry window in the break's
        real direction.
    """
    if state.atr <= 0:
        return

    candles = list(state.candles_15m)
    if not candles:
        return

    latest = candles[-1]

    # Age out a previous break window (decrement happens on every close
    # AFTER the detection candle; the window covers closes N and N+1).
    if state.squeeze_broken:
        state.squeeze_broken_ttl -= 1
        if state.squeeze_broken_ttl <= 0:
            _clear_broken(state)

    # Break detection must run BEFORE the compression reset wipes the
    # armed squeeze — the breakout candle is by definition not compressed.
    if state.in_squeeze and state.squeeze_reference_level > 0:
        level = state.squeeze_reference_level
        broke_down = state.squeeze_price_above_level is True and latest.close < level
        broke_up = state.squeeze_price_above_level is False and latest.close > level
        if broke_down or broke_up:
            state.squeeze_broken = True
            state.squeeze_broken_direction = Side.SHORT if broke_down else Side.LONG
            state.squeeze_broken_level = level
            state.squeeze_broken_ttl = 2

    is_compressed = latest.range <= SQUEEZE_COMPRESSION_ATR * state.atr
    key_level, distance, level_kind = _nearest_key_level(state.last_price, state)
    near_level = key_level > 0 and distance <= SQUEEZE_LEVEL_ATR_PROXIMITY * state.atr

    if is_compressed and near_level:
        state.squeeze_bar_count += 1
        if state.squeeze_bar_count >= SQUEEZE_MIN_BARS:
            state.in_squeeze = True
            state.squeeze_reference_level = key_level
            state.squeeze_price_above_level = state.last_price > key_level
            # Fade thesis only makes sense against the level's real kind:
            # compressed on top of support → bounce up; under resistance → bounce down.
            if level_kind == "support" and state.last_price >= key_level:
                state.squeeze_direction = Side.LONG
            elif level_kind == "resistance" and state.last_price <= key_level:
                state.squeeze_direction = Side.SHORT
            else:
                state.squeeze_direction = None
    else:
        state.squeeze_bar_count = 0
        state.in_squeeze = False
        state.squeeze_reference_level = 0.0
        state.squeeze_direction = None
        state.squeeze_price_above_level = None
```

En `check_entry_signal`, reemplazar el arranque (regime/squeeze/position) por:

```python
    if ENTRY_VARIANT == "break":
        if not state.squeeze_broken:
            return None
        direction = state.squeeze_broken_direction
    else:
        if not state.in_squeeze:
            return None
        direction = state.squeeze_direction
    if direction is None:
        return None
    if state.position is not None:
        return None
    if state.regime == Regime.UNKNOWN:
        return None
```

(El check de régimen se movió después del de squeeze — son ANDs, no cambia el resultado, y deja los rechazos contables como "señal candidata vetada" para la Task 4.)

Y antes del `return direction` final:

```python
    if ENTRY_VARIANT == "break":
        _clear_broken(state)
```

- [ ] **Step 4: Verificar**

Run: `pytest tests/test_signals.py -v && pytest -q`
Expected: PASS completo (los tests de reset existentes no miran los campos broken).

- [ ] **Step 5: Commit**

```bash
git add signals.py state.py tests/test_signals.py conftest.py
git commit -m "Variant B: squeeze_broken state with 2-bar TTL and entry variant selector"
```

---

### Task 4: Gates con nombre, apagables y con contador de vetos

**Files:**
- Modify: `signals.py` (`check_entry_signal` completo, constantes de módulo)
- Test: `tests/test_signals.py`

**Interfaces:**
- Consumes: variante y estado broken de Task 3.
- Produces:
  - `signals.GATE_NAMES: tuple = ("regime_known", "spread", "trend_1h", "macro", "breakout_align", "cvd", "ob_imbalance")`
  - `signals.DISABLED_GATES: set[str]` (default vacío) — un gate en el set se saltea.
  - `signals.GATE_VETO_COUNTS: dict[str, int]` y `signals.SIGNAL_STATS: dict` con clave `"fired"`.
  - `signals.reset_signal_stats() -> None`.
  - `in_squeeze`/`squeeze_broken`, `direction is None` y `position is not None` NO son gates: no se apagan ni se cuentan.

- [ ] **Step 1: Escribir los tests que fallan**

```python
def test_disabled_gate_lets_signal_through():
    state = _base_state(direction=Side.LONG)
    state.trend_1h = Side.SHORT  # el gate trend_1h vetaría este long
    signals.DISABLED_GATES = {"trend_1h"}

    assert check_entry_signal(state) == Side.LONG


def test_gate_veto_counter_increments_on_rejection():
    signals.reset_signal_stats()
    state = _base_state(direction=Side.LONG)
    state.trend_1h = Side.SHORT

    assert check_entry_signal(state) is None
    assert signals.GATE_VETO_COUNTS["trend_1h"] == 1
    assert signals.SIGNAL_STATS["fired"] == 0


def test_signals_fired_counter_increments_on_pass():
    signals.reset_signal_stats()
    state = _base_state(direction=Side.LONG)

    assert check_entry_signal(state) == Side.LONG
    assert signals.SIGNAL_STATS["fired"] == 1
    assert all(count == 0 for count in signals.GATE_VETO_COUNTS.values())


def test_regime_unknown_counts_as_gate_veto_only_with_live_squeeze():
    signals.reset_signal_stats()
    state = _base_state(direction=Side.LONG, regime=Regime.UNKNOWN)

    assert check_entry_signal(state) is None
    assert signals.GATE_VETO_COUNTS["regime_known"] == 1

    signals.reset_signal_stats()
    state.in_squeeze = False  # sin señal candidata no se cuenta nada
    assert check_entry_signal(state) is None
    assert signals.GATE_VETO_COUNTS["regime_known"] == 0


def test_disabling_regime_gate_allows_unknown_regime():
    state = _base_state(direction=Side.LONG, regime=Regime.UNKNOWN)
    signals.DISABLED_GATES = {"regime_known"}

    assert check_entry_signal(state) == Side.LONG
```

Extender el fixture de `conftest.py` para restaurar también los nuevos globals:

```python
@pytest.fixture(autouse=True)
def _reset_signal_globals():
    compression = config.SQUEEZE_COMPRESSION_ATR
    min_bars = config.SQUEEZE_MIN_BARS
    yield
    signals.ENTRY_VARIANT = "fade"
    signals.DISABLED_GATES = set()
    signals.reset_signal_stats()
    config.SQUEEZE_COMPRESSION_ATR = compression
    config.SQUEEZE_MIN_BARS = min_bars
```

- [ ] **Step 2: Verificar que fallan**

Run: `pytest tests/test_signals.py -k "gate or fired" -v`
Expected: FAIL (`AttributeError: module 'signals' has no attribute 'DISABLED_GATES'`).

- [ ] **Step 3: Implementación**

En `signals.py`, constantes de módulo + helper:

```python
GATE_NAMES = ("regime_known", "spread", "trend_1h", "macro", "breakout_align", "cvd", "ob_imbalance")

# Backtest ablation hooks: gates listed here are skipped entirely.
DISABLED_GATES: set = set()

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
```

`check_entry_signal` completo (reemplaza el cuerpo desde el check de régimen hasta el final; conserva los `logger.debug` con el mismo texto):

```python
    if _vetoed("regime_known", state.regime == Regime.UNKNOWN):
        logger.debug("Signal rejected: regime unknown")
        return None

    if _vetoed("spread", state.atr > 0 and state.spread > SPREAD_FILTER_ATR_PCT * state.atr):
        logger.debug(
            "Signal rejected: spread %.4f exceeds %.0f%% of ATR %.4f",
            state.spread, SPREAD_FILTER_ATR_PCT * 100, state.atr,
        )
        return None

    if _vetoed("trend_1h", state.trend_1h is not None and state.trend_1h != direction):
        logger.debug("Signal rejected: 1h trend %s opposes %s", state.trend_1h, direction)
        return None

    macro_opposes = (direction == Side.LONG and state.macro_blocks_longs) or \
                    (direction == Side.SHORT and state.macro_blocks_shorts)
    if _vetoed("macro", macro_opposes):
        logger.debug("Signal rejected: macro blocks %s", direction.value)
        return None

    breakout_opposes = False
    if state.regime == Regime.BREAKOUT:
        candles = list(state.candles_15m)
        if candles:
            last = candles[-1]
            breakout_opposes = not ((direction == Side.LONG and last.bullish) or
                                    (direction == Side.SHORT and last.bearish))
    if _vetoed("breakout_align", breakout_opposes):
        logger.debug("Signal rejected: squeeze direction opposes breakout candle")
        return None

    divergence = detect_cvd_divergence(state)
    cvd_opposes = (direction == Side.LONG and divergence == "bearish_divergence") or \
                  (direction == Side.SHORT and divergence == "bullish_divergence")
    if _vetoed("cvd", cvd_opposes):
        logger.debug("Signal rejected: %s against %s setup", divergence, direction.value)
        return None

    _, ob_dir = get_book_imbalance(state)
    ob_opposes = (direction == Side.LONG and ob_dir == "ask") or \
                 (direction == Side.SHORT and ob_dir == "bid")
    if _vetoed("ob_imbalance", ob_opposes):
        logger.debug("Signal rejected: %s-side book imbalance on %s setup", ob_dir, direction.value)
        return None

    SIGNAL_STATS["fired"] += 1
    if ENTRY_VARIANT == "break":
        _clear_broken(state)

    logger.info(
        "Entry signal: %s | regime=%s | level=%.2f | divergence=%s | ob=%s",
        direction.value.upper(), state.regime.value,
        state.squeeze_reference_level, divergence, ob_dir,
    )
    return direction
```

- [ ] **Step 4: Verificar**

Run: `pytest tests/test_signals.py -v && pytest -q`
Expected: PASS completo (los tests de gates existentes no cambian: mismos rechazos con defaults).

- [ ] **Step 5: Commit**

```bash
git add signals.py tests/test_signals.py conftest.py
git commit -m "Named, disableable entry gates with per-gate veto counters"
```

---

### Task 5: CLI reproducible del backtest

**Files:**
- Modify: `backtest.py` (`parse_args`, `run_backtest`), `signals.py` (leer umbrales de squeeze vía `config.` en runtime)
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `signals.ENTRY_VARIANT`, `signals.DISABLED_GATES`, `signals.reset_signal_stats()`, `signals.GATE_NAMES`, `signals.GATE_VETO_COUNTS`, `signals.SIGNAL_STATS` (Tasks 3-4).
- Produces:
  - Flags: `--variant {fade,break}` (default `fade`), `--disable-gate <name>` (repetible, validado contra `GATE_NAMES`), `--squeeze-compression <float>`, `--squeeze-min-bars <int>` (defaults: los de `config.py`).
  - `meta.json` gana: `variant`, `disabled_gates` (lista ordenada), `squeeze_compression`, `squeeze_min_bars`.
  - `summary.json["metrics"]` gana: `gate_vetoes` (dict) y `signals_fired` (int).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_backtest.py` (seguir el patrón de `test_run_creates_run_dir_with_meta_summary_and_index`, que ya usa un exchange falso y `tmp_path`; copiar su setup de fixture):

```python
def test_parse_args_accepts_ablation_flags():
    args = backtest.parse_args([
        "--start", "2026-04-01", "--end", "2026-04-02",
        "--variant", "break", "--disable-gate", "cvd", "--disable-gate", "trend_1h",
        "--squeeze-compression", "0.6", "--squeeze-min-bars", "2",
    ])
    assert args.variant == "break"
    assert args.disable_gate == ["cvd", "trend_1h"]
    assert args.squeeze_compression == 0.6
    assert args.squeeze_min_bars == 2


def test_parse_args_rejects_unknown_gate():
    with pytest.raises(SystemExit):
        backtest.parse_args([
            "--start", "2026-04-01", "--end", "2026-04-02",
            "--disable-gate", "no-existe",
        ])


def test_run_records_ablation_params_in_meta_and_gate_stats_in_summary(tmp_path):
    # _FakeExchange, _sample_day, START/END y el fixture autouse _isolate_runs_dir
    # (que redirige backtest.RUNS_DIR a tmp) ya existen en este archivo.
    import signals

    klines_1m, trades = _sample_day()
    exchange = _FakeExchange(klines_1m, trades)

    rc = backtest.main(
        ["--start", START, "--end", END, "--out", str(tmp_path / "t.csv"),
         "--label", "abl-test", "--variant", "break", "--disable-gate", "cvd",
         "--squeeze-compression", "0.6", "--squeeze-min-bars", "2"],
        exchange=exchange,
    )
    assert rc == 0

    run_dirs = [d for d in os.listdir(backtest.RUNS_DIR)
                if os.path.isdir(os.path.join(backtest.RUNS_DIR, d))]
    assert len(run_dirs) == 1
    run = os.path.join(backtest.RUNS_DIR, run_dirs[0])

    meta = json.load(open(os.path.join(run, "meta.json")))
    assert meta["variant"] == "break"
    assert meta["disabled_gates"] == ["cvd"]
    assert meta["squeeze_compression"] == 0.6
    assert meta["squeeze_min_bars"] == 2

    metrics = json.load(open(os.path.join(run, "summary.json")))["metrics"]
    assert isinstance(metrics["gate_vetoes"], dict)
    assert set(metrics["gate_vetoes"]) == set(signals.GATE_NAMES)
    assert isinstance(metrics["signals_fired"], int)
```

- [ ] **Step 2: Verificar que fallan**

Run: `pytest tests/test_backtest.py -k "ablation or unknown_gate" -v`
Expected: FAIL (`unrecognized arguments: --variant`).

- [ ] **Step 3: Implementación**

En `signals.py`: sacar `SQUEEZE_COMPRESSION_ATR` y `SQUEEZE_MIN_BARS` del import de `config` (dejar `SPREAD_FILTER_ATR_PCT` y `SQUEEZE_LEVEL_ATR_PROXIMITY` como están), agregar `import config`, y en `update_squeeze` usar `config.SQUEEZE_COMPRESSION_ATR` y `config.SQUEEZE_MIN_BARS`. Así el backtest puede sobreescribirlos sin editar archivos.

En `backtest.py`:

```python
import config
import signals
```

En `parse_args`:

```python
    parser.add_argument("--variant", choices=("fade", "break"), default="fade",
                        help="Modelo de entrada: fade (anticipado) o break (confirmación de ruptura)")
    parser.add_argument("--disable-gate", action="append", default=None,
                        choices=signals.GATE_NAMES, dest="disable_gate",
                        help="Apaga un gate de entrada (repetible)")
    parser.add_argument("--squeeze-compression", type=float, default=config.SQUEEZE_COMPRESSION_ATR)
    parser.add_argument("--squeeze-min-bars", type=int, default=config.SQUEEZE_MIN_BARS)
```

En `run_backtest`, después de `validate_range(...)`:

```python
    config.SQUEEZE_COMPRESSION_ATR = args.squeeze_compression
    config.SQUEEZE_MIN_BARS = args.squeeze_min_bars
    signals.ENTRY_VARIANT = args.variant
    signals.DISABLED_GATES = set(args.disable_gate or ())
    signals.reset_signal_stats()
```

Después de `summary = compute_summary(trade_records)`:

```python
    summary["gate_vetoes"] = dict(signals.GATE_VETO_COUNTS)
    summary["signals_fired"] = signals.SIGNAL_STATS["fired"]
```

En el dict `meta`:

```python
        "variant": args.variant,
        "disabled_gates": sorted(signals.DISABLED_GATES),
        "squeeze_compression": args.squeeze_compression,
        "squeeze_min_bars": args.squeeze_min_bars,
```

- [ ] **Step 4: Verificar**

Run: `pytest tests/test_backtest.py -v && pytest -q`
Expected: PASS completo. Ojo: si algún test de `test_backtest.py` falla por estado global filtrado entre tests, el fixture autouse de `conftest.py` (Task 4) ya debe estar restaurando `config`/`signals`.

- [ ] **Step 5: Commit**

```bash
git add backtest.py signals.py tests/test_backtest.py
git commit -m "Reproducible backtest CLI: variant, gate and squeeze-threshold flags in meta"
```

---

### Task 6: Columna de vetos en el comparador HTML

**Files:**
- Modify: `backtest_html.py` (`_COLS`, `_row`, helper nuevo)
- Test: `tests/test_backtest_html.py`

**Interfaces:**
- Consumes: `summary.json["metrics"]["gate_vetoes"]` (Task 5); corridas viejas no tienen la clave y deben renderizar `—`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_backtest_html.py` (seguir el patrón de creación de corridas falsas que ya usa el archivo):

El archivo ya tiene un helper `_make_run(base, name, pnl, corrupt)`; extenderlo con un
parámetro opcional `gate_vetoes=None` que, si no es `None`, agrega
`"gate_vetoes": gate_vetoes` al dict `metrics` que escribe en `summary.json`. Después:

```python
def test_index_renders_gate_vetoes_sorted_desc(tmp_path):
    _make_run(str(tmp_path), "2026-07-12_10-00-00",
              gate_vetoes={"trend_1h": 12, "cvd": 3, "spread": 0})

    write_index(str(tmp_path))
    html_text = open(os.path.join(str(tmp_path), "index.html")).read()

    assert "trend_1h:12 cvd:3" in html_text  # orden descendente, los ceros no aparecen
    assert "Vetos" in html_text


def test_index_tolerates_runs_without_gate_vetoes(tmp_path):
    _make_run(str(tmp_path), "2026-07-12_10-00-00")  # formato viejo, sin la clave

    write_index(str(tmp_path))
    html_text = open(os.path.join(str(tmp_path), "index.html")).read()

    assert "Vetos" in html_text  # la columna existe igual; la celda rinde "—"
```

- [ ] **Step 2: Verificar que fallan**

Run: `pytest tests/test_backtest_html.py -k vetoes -v`
Expected: FAIL (no existe la columna).

- [ ] **Step 3: Implementación**

En `backtest_html.py`, insertar en `_COLS` antes de `("equity", "Equity")`:

```python
    ("gate_vetoes", "Vetos"),
```

Helper nuevo (junto a `_fmt`):

```python
def _fmt_vetoes(vetoes) -> str:
    if not isinstance(vetoes, dict) or not vetoes:
        return "—"
    parts = [f"{k}:{v}" for k, v in sorted(vetoes.items(), key=lambda kv: -kv[1]) if v]
    return html.escape(" ".join(parts)) if parts else "0"
```

En `_row`, insertar la celda antes de la del sparkline:

```python
        _fmt_vetoes(m.get("gate_vetoes")),
        _sparkline_svg(run["summary"].get("equity_curve", [])),
```

(`numeric_cols` queda `{4, 5, 6, 7, 8, 9}` — la columna nueva, índice 10, no es numérica.)

- [ ] **Step 4: Verificar**

Run: `pytest tests/test_backtest_html.py -v && pytest -q`
Expected: PASS completo.

- [ ] **Step 5: Commit**

```bash
git add backtest_html.py tests/test_backtest_html.py
git commit -m "Show per-gate veto counts in the backtest run comparator"
```

---

### Task 7: `run_ablation.py` — matriz, skip y reporte con veredicto

**Files:**
- Create: `run_ablation.py`
- Test: `tests/test_run_ablation.py` (nuevo)

**Interfaces:**
- Consumes: `backtest.main(argv) -> int` (existente), flags de Task 5, `meta.json`/`summary.json` de Task 5.
- Produces:
  - `build_run_matrix() -> list[dict]` — 12 specs `{"variant", "disabled_gate", "label"}` (2 variantes × [base + 5 gates ablacionables]).
  - `run_matrix(start, end, runner=backtest.main, runs_dir="backtest_runs")` — corre secuencial, saltea corridas ya hechas (mismo label + mismos parámetros en `meta.json`), aborta si una corrida retorna ≠ 0.
  - `write_report(start, end, runs_dir) -> str` — escribe `backtest_runs/ablation-<YYYY-MM-DD>.md` con tabla por variante, gates inertes anotados y veredicto del criterio pre-registrado (P&L neto > 0 y ≥ 30 trades sobre la corrida BASE).

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_run_ablation.py`:

```python
import json

import run_ablation


def _write_fake_run(runs_dir, name, meta, metrics):
    run_dir = runs_dir / name
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text(json.dumps(meta))
    (run_dir / "summary.json").write_text(json.dumps({"metrics": metrics, "equity_curve": []}))


def _meta_for(spec, start="2026-04-01", end="2026-07-01"):
    return {
        "label": spec["label"], "start": start, "end": end,
        "variant": spec["variant"],
        "disabled_gates": [spec["disabled_gate"]] if spec["disabled_gate"] else [],
        "squeeze_compression": run_ablation.FUNNEL_COMPRESSION,
        "squeeze_min_bars": run_ablation.FUNNEL_MIN_BARS,
    }


def test_matrix_has_12_runs_with_systematic_labels():
    matrix = run_ablation.build_run_matrix()
    labels = [spec["label"] for spec in matrix]

    assert len(matrix) == 12
    assert "ablA-base" in labels and "ablB-base" in labels
    assert "ablA-no-trend_1h" in labels and "ablB-no-cvd" in labels
    assert not any("macro" in l or "ob_imbalance" in l for l in labels)  # inertes excluidos


def test_run_matrix_skips_existing_runs_and_runs_the_rest(tmp_path):
    done = run_ablation.build_run_matrix()[0]  # ablA-base ya corrida
    _write_fake_run(tmp_path, "2026-07-12_00-00-00_ablA-base", _meta_for(done),
                    {"total_trades": 5})
    executed = []

    def fake_runner(argv):
        executed.append(argv)
        # simular que la corrida persiste su run dir para el reporte posterior
        return 0

    run_ablation.run_matrix("2026-04-01", "2026-07-01", runner=fake_runner,
                            runs_dir=str(tmp_path))

    assert len(executed) == 11  # 12 menos la ya corrida
    first = executed[0]
    assert "--variant" in first and "--label" in first
    assert "--squeeze-compression" in first


def test_run_matrix_aborts_when_a_run_fails(tmp_path):
    import pytest

    def failing_runner(argv):
        return 1

    with pytest.raises(RuntimeError):
        run_ablation.run_matrix("2026-04-01", "2026-07-01", runner=failing_runner,
                                runs_dir=str(tmp_path))


def test_report_applies_preregistered_verdict(tmp_path):
    for spec in run_ablation.build_run_matrix():
        profitable = spec["variant"] == "break"
        _write_fake_run(
            tmp_path, f"2026-07-12_01-00-00_{spec['label']}", _meta_for(spec),
            {"total_trades": 40, "win_rate": 0.5, "profit_factor": 1.2,
             "total_net_pnl": 250.0 if profitable else -300.0,
             "signals_fired": 60,
             "gate_vetoes": {"trend_1h": 12, "cvd": 3}},
        )

    path = run_ablation.write_report("2026-04-01", "2026-07-01", runs_dir=str(tmp_path))
    text = open(path).read()

    assert "NO se adopta" in text          # variante A pierde
    assert "SE ADOPTA" in text             # variante B gana con ≥30 trades
    assert "trend_1h:12 cvd:3" in text
    assert "macro" in text and "ob_imbalance" in text  # inertes anotados


def test_report_rejects_profitable_base_with_too_few_trades(tmp_path):
    for spec in run_ablation.build_run_matrix():
        _write_fake_run(
            tmp_path, f"2026-07-12_02-00-00_{spec['label']}", _meta_for(spec),
            {"total_trades": 10, "win_rate": 0.6, "profit_factor": 2.0,
             "total_net_pnl": 500.0, "signals_fired": 12, "gate_vetoes": {}},
        )

    text = open(run_ablation.write_report("2026-04-01", "2026-07-01",
                                          runs_dir=str(tmp_path))).read()

    assert "SE ADOPTA" not in text
```

- [ ] **Step 2: Verificar que fallan**

Run: `pytest tests/test_run_ablation.py -v`
Expected: FAIL (`ModuleNotFoundError: run_ablation`).

- [ ] **Step 3: Implementación — crear `run_ablation.py`**

```python
"""Corre la matriz pre-registrada del ablation de gates (P0-8) para la decisión N1.

Uso: python run_ablation.py --start 2026-04-01 --end 2026-07-01

12 corridas secuenciales (2 variantes × [base + 5 gates]) con el embudo
pre-registrado en el spec de N1. Nunca paralelizar: cada corrida usa ~2.2 GB.
Criterio de adopción (fijado ANTES de correr): la corrida BASE de una variante
debe ser rentable neta de fees con ≥ 30 trades; si no, no se adopta.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import backtest

RUNS_DIR = "backtest_runs"
FUNNEL_COMPRESSION = 0.6
FUNNEL_MIN_BARS = 2
ABLATABLE_GATES = ("regime_known", "spread", "trend_1h", "breakout_align", "cvd")
INERT_GATES = ("macro", "ob_imbalance")  # neutrales en backtest por diseño
MIN_TRADES_FOR_ADOPTION = 30


def build_run_matrix() -> list:
    matrix = []
    for variant, tag in (("fade", "A"), ("break", "B")):
        matrix.append({"variant": variant, "disabled_gate": None, "label": f"abl{tag}-base"})
        for gate in ABLATABLE_GATES:
            matrix.append({"variant": variant, "disabled_gate": gate,
                           "label": f"abl{tag}-no-{gate}"})
    return matrix


def _spec_matches_meta(spec: dict, meta: dict, start: str, end: str) -> bool:
    disabled = [spec["disabled_gate"]] if spec["disabled_gate"] else []
    return (meta.get("label") == spec["label"]
            and meta.get("start") == start and meta.get("end") == end
            and meta.get("variant") == spec["variant"]
            and meta.get("disabled_gates") == disabled
            and meta.get("squeeze_compression") == FUNNEL_COMPRESSION
            and meta.get("squeeze_min_bars") == FUNNEL_MIN_BARS)


def find_existing_run(spec: dict, start: str, end: str, runs_dir: str = RUNS_DIR):
    if not os.path.isdir(runs_dir):
        return None
    for name in sorted(os.listdir(runs_dir)):
        meta_path = os.path.join(runs_dir, name, "meta.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if _spec_matches_meta(spec, meta, start, end):
            return name
    return None


def _argv_for(spec: dict, start: str, end: str) -> list:
    argv = ["--start", start, "--end", end,
            "--variant", spec["variant"],
            "--squeeze-compression", str(FUNNEL_COMPRESSION),
            "--squeeze-min-bars", str(FUNNEL_MIN_BARS),
            "--label", spec["label"]]
    if spec["disabled_gate"]:
        argv += ["--disable-gate", spec["disabled_gate"]]
    return argv


def run_matrix(start: str, end: str, runner=backtest.main, runs_dir: str = RUNS_DIR) -> None:
    for spec in build_run_matrix():
        existing = find_existing_run(spec, start, end, runs_dir)
        if existing:
            print(f"[skip] {spec['label']} ya corrida: {existing}")
            continue
        print(f"[run ] {spec['label']}")
        rc = runner(_argv_for(spec, start, end))
        if rc != 0:
            raise RuntimeError(f"backtest falló para {spec['label']} (rc={rc})")


def _load_metrics(spec: dict, start: str, end: str, runs_dir: str):
    name = find_existing_run(spec, start, end, runs_dir)
    if name is None:
        return None
    with open(os.path.join(runs_dir, name, "summary.json")) as f:
        return json.load(f)["metrics"]


def _fmt_num(value, spec: str) -> str:
    try:
        return format(value, spec)
    except (TypeError, ValueError):
        return str(value)  # p. ej. profit_factor serializado como "inf"


def _verdict_line(tag: str, metrics) -> str:
    if metrics is None:
        return f"- Variante {tag}: SIN DATOS (corrida base no encontrada)"
    pnl = metrics.get("total_net_pnl", 0.0)
    trades = metrics.get("total_trades", 0)
    adopted = isinstance(pnl, (int, float)) and pnl > 0 and trades >= MIN_TRADES_FOR_ADOPTION
    verdict = "SE ADOPTA" if adopted else "NO se adopta"
    return (f"- Variante {tag} (base): {trades} trades, P&L neto ${_fmt_num(pnl, '+.2f')} → "
            f"**{verdict}** (criterio pre-registrado: P&L neto > 0 y "
            f"≥ {MIN_TRADES_FOR_ADOPTION} trades)")


def write_report(start: str, end: str, runs_dir: str = RUNS_DIR) -> str:
    lines = [
        f"# Ablation N1/P0-8 — {start} → {end}", "",
        f"Embudo pre-registrado: compresión {FUNNEL_COMPRESSION} · mínimo {FUNNEL_MIN_BARS} velas.",
        f"Gates inertes en backtest (sin corrida propia; un veto de 0 acá NO significa "
        f"\"no aporta\"): {', '.join(INERT_GATES)}.", "",
    ]
    base_metrics = {}
    for variant, tag in (("fade", "A"), ("break", "B")):
        lines += [f"## Variante {tag} ({variant})", "",
                  "| Corrida | Trades | Win rate | P&L neto | Profit factor | Señales | Vetos |",
                  "|---|---|---|---|---|---|---|"]
        for spec in build_run_matrix():
            if spec["variant"] != variant:
                continue
            m = _load_metrics(spec, start, end, runs_dir)
            if m is None:
                lines.append(f"| {spec['label']} | — | — | — | — | — | corrida faltante |")
                continue
            vetoes = m.get("gate_vetoes") or {}
            veto_str = " ".join(f"{k}:{v}" for k, v in
                                sorted(vetoes.items(), key=lambda kv: -kv[1]) if v) or "0"
            lines.append(
                f"| {spec['label']} | {m.get('total_trades', 0)} "
                f"| {_fmt_num(m.get('win_rate', 0), '.1%')} "
                f"| ${_fmt_num(m.get('total_net_pnl', 0), '+.2f')} "
                f"| {_fmt_num(m.get('profit_factor', 0), '.2f')} "
                f"| {m.get('signals_fired', '—')} | {veto_str} |")
            if spec["disabled_gate"] is None:
                base_metrics[tag] = m
        lines.append("")
    lines += ["## Veredicto (criterio pre-registrado)", "",
              _verdict_line("A", base_metrics.get("A")),
              _verdict_line("B", base_metrics.get("B")), ""]
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(runs_dir, f"ablation-{date}.md")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Matriz de ablation N1/P0-8")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (UTC, inclusive)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (UTC, exclusivo)")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    run_matrix(args.start, args.end)
    path = write_report(args.start, args.end)
    print(f"Reporte: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Verificar**

Run: `pytest tests/test_run_ablation.py -v && pytest -q`
Expected: PASS completo.

- [ ] **Step 5: Commit**

```bash
git add run_ablation.py tests/test_run_ablation.py
git commit -m "Ablation runner: pre-registered 12-run matrix, resume support, verdict report"
```

---

### Task 8: Correr el ablation completo y registrar el veredicto

**Files:**
- Modify: `docs/mejoras-propuestas.md` (§6 Estado)
- Produce: `backtest_runs/ablation-<fecha>.md` + 12 run dirs

Esta task corre en la rama ya mergeada a master (o en el worktree con los 91 días de cache en `trade_cache/` accesibles — verificar antes que `download_history.py`/el cache estén disponibles desde el cwd del worktree; si no, correr desde el checkout principal una vez mergeado).

- [ ] **Step 1: Smoke corto de la matriz (1 día)**

Run: `python run_ablation.py --start 2026-04-01 --end 2026-04-02`
Expected: 12 corridas de ~10 s c/u, reporte generado sin errores. Esto valida el wiring end-to-end antes de gastar 2.5 h. Borrar después los 12 run dirs del smoke y el reporte (`rm -rf backtest_runs/*abl[AB]-*` con cuidado de no tocar corridas previas, y el `ablation-*.md`), porque usarían los mismos labels que la corrida real y el skip los confundiría (el skip compara también `start`/`end`, así que técnicamente no colisionan — pero limpiar evita confusión en el index.html).

- [ ] **Step 2: Corrida real en background**

Run (en background, ~2.5 h): `python run_ablation.py --start 2026-04-01 --end 2026-07-01`
Expected: 12 corridas secuenciales persistidas + `backtest_runs/ablation-2026-XX-XX.md`.

- [ ] **Step 3: Verificar el reporte y aplicar el criterio**

Leer el reporte generado. Confirmar: 12 filas sin "corrida faltante", veredicto presente para A y B, `index.html` regenerado con las corridas nuevas y la columna de vetos.

- [ ] **Step 4: Actualizar `docs/mejoras-propuestas.md` §6**

Agregar al final de §6 un bloque con fecha, resumen de las dos corridas base, el veredicto del criterio pre-registrado y el pointer al reporte. Marcar P0-8 como hecho en §4 si corresponde.

- [ ] **Step 5: Commit**

```bash
git add docs/mejoras-propuestas.md backtest_runs/
git commit -m "Run N1 ablation matrix and record the pre-registered verdict"
```

(Si `backtest_runs/` está gitignoreado, commitear solo el doc y dejar los runs locales — verificar `.gitignore` antes.)
