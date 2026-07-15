# Pivot de estrategia: señal en 15m + entradas maker (post-only) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mover el reloj de señal del bot de velas de 1m a velas de 15m y convertir las entradas de market/taker a limit post-only/maker, para que el fee drag por trade baje de ~1.30R a ~0.17R (entrada maker 0.02% + salidas taker 0.05%).

**Architecture:** El pipeline de señal (ATR, régimen, squeeze, CVD, swing points) pasa a consumir `state.candles_15m` y a evaluarse en el cierre de cada vela de 15m. El filtro de tendencia multi-timeframe pasa de "EMA 15m sobre señal 1m" a "EMA-80 sobre cierres de 15m" (equivalente a una EMA-20 de 1h, sin agregar streams nuevos). La entrada deja de abrir posición al instante: coloca una orden límite en el mejor bid/ask, que en paper/backtest se llena solo si el precio la atraviesa (simulación de cola conservadora) y en live se envía post-only (GTX) a Binance Futures; si no se llena en un timeout, se cancela y el trade se pierde. Las salidas (SL, TP1, time exit, momentum abort) siguen siendo market/taker sin cambios.

**Tech Stack:** Python 3.12, asyncio, pytest, ccxt (solo live). Sin dependencias nuevas.

## Contexto y justificación (medido contra datos del repo)

ATR% mediano y fee drag round-trip en R (medidos sobre 30 días de klines 1m de BTC en `backtest_cache/`, Wilder ATR-14, fórmula `F/R = fees_rt / (1.5·ATR%)`):

| TF | ATR% p50 | taker 0.05% ambos lados | maker 0.02% entrada + taker salida |
|---|---:|---:|---:|
| 1m (actual) | 0.051% | 1.30R | — |
| 15m (objetivo) | 0.280% | 0.24R | **~0.17R** |

En 1m taker cada trade arranca perdido >1R solo en fees. El pivot ataca las dos palancas a la vez. Documentos de referencia: `docs/mejoras-propuestas.md` (P0-2, P0-4), `docs/revisiones/tercera-opinion-logica-implementacion-fable.md`.

**Interacción crítica spread-sintético × filtro de spread (corregida en Task 1):** el backtest simula spread = 0.01% del precio (`BACKTEST_SYNTHETIC_SPREAD_PCT = 0.0001`). El techo del filtro pasa a ser `0.01 × ATR(15m)` ≈ 0.0028% del precio (mediana), que es **menor** que 0.01% → sin corregir, el backtest rechazaría el 100% de las señales por spread. Se baja el spread sintético a 0.001% del precio (~$1 en BTC a 100k, todavía ~10× el spread real típico de BTCUSDT futures).

## Global Constraints

- Python del venv del repo: ejecutar tests con `.venv/bin/python -m pytest -q` (o `pytest -q` con el venv activado).
- Sin dependencias nuevas en `requirements.txt`.
- Código y comentarios en inglés (estilo del codebase); docs en español.
- TDD estricto: test que falla → implementación mínima → test verde → commit.
- Después de cada task, la suite completa debe estar verde: `.venv/bin/python -m pytest -q`.
- Valores exactos de config nuevos/cambiados (fuente de verdad de todo el plan):
  - `TIME_EXIT_MINUTES = 225` (15 barras de 15m; antes 15)
  - `MOMENTUM_ABORT_MINUTES = 45` (3 barras de 15m; antes 3)
  - `SPREAD_FILTER_ATR_PCT = 0.01` (antes 0.05; el ATR de 15m es ~5.5× el de 1m)
  - `BACKTEST_SYNTHETIC_SPREAD_PCT = 0.00001` (antes 0.0001; ver arriba)
  - `TREND_EMA_1H_ON_15M = 80` (nueva; reemplaza `TREND_EMA_5M = 12` y `TREND_EMA_15M = 20`, que se eliminan)
  - `MAKER_FEE_RATE = 0.0002` (nueva; 0.02%/lado Binance Futures USDT-M maker sin descuento BNB)
  - `ENTRY_ORDER_TIMEOUT_SECONDS = 300` (nueva; cancela la limit de entrada si no se llenó en 5 min)
  - Sin cambios: `ATR_PERIOD = 14`, `SQUEEZE_*`, `REGIME_*`, `ACCOUNT_RISK_PCT`, `INITIAL_SL_ATR`, `TP1_RR`, `TAKER_FEE_RATE = 0.0005`, `CVD_DIVERGENCE_LOOKBACK = 5`, buffers.
- Convención de mensajes de commit del repo: imperativo corto en inglés ("Add X", "Switch Y"), más el footer de co-autoría que agregue el harness.

---

### Task 1: Reloj de señal en 15m (buffers, wiring y parámetros de tiempo)

Cambio mecánico coherente: todo consumidor del pipeline de señal pasa de `candles_1m` a `candles_15m`, el pipeline entero se evalúa en `on_candle_15m`, y los parámetros expresados en minutos escalan ×15. La lógica interna de cada función NO cambia.

**Files:**
- Modify: `config.py` (líneas de `TIME_EXIT_MINUTES`, `MOMENTUM_ABORT_MINUTES`, `SPREAD_FILTER_ATR_PCT`, `BACKTEST_SYNTHETIC_SPREAD_PCT`)
- Modify: `indicators.py:84-98` (`update_indicators`)
- Modify: `regime.py:62-96` (`_infer_candidate`, `update_regime`; `_ema_is_sloping` y `_has_liquidity_sweeps_at_both_extremes` reciben las velas por parámetro/estado)
- Modify: `signals.py:38, 113` (`update_squeeze`, confirmación BREAKOUT en `check_entry_signal`)
- Modify: `order_flow.py:29` (`detect_cvd_divergence`)
- Modify: `risk.py:174` (`_apply_structural_trail`)
- Modify: `main.py:41-111` (`wire_strategy`)
- Test: `tests/test_signals.py`, `tests/test_regime.py`, `tests/test_order_flow.py`, `tests/test_indicators.py`, `tests/test_main.py`, `tests/test_risk.py`, `tests/test_momentum.py`

**Interfaces:**
- Consumes: `state.candles_15m` (deque de `Candle`, ya poblada idénticamente por `DataFeed` y `BacktestFeed` — no tocar los feeds).
- Produces: pipeline de señal completo disparado en cierre de vela 15m; `state.atr` y `state.ema` calculados sobre 15m. Tasks 2-5 asumen esto.

- [ ] **Step 1: Test de wiring que falla — el pipeline corre en el cierre de 15m, no en el de 1m**

Reemplazar el contenido completo de `tests/test_main.py` por:

```python
import asyncio

from execution import ExecutionEngine
from main import wire_strategy
from state import Candle, MarketState


class _FakeFeed:
    def __init__(self):
        self.trade_handlers = []
        self.candle_1m_handlers = []
        self.candle_5m_handlers = []
        self.candle_15m_handlers = []

    def on_trade(self, fn):
        self.trade_handlers.append(fn)

    def on_candle_1m(self, fn):
        self.candle_1m_handlers.append(fn)

    def on_candle_5m(self, fn):
        self.candle_5m_handlers.append(fn)

    def on_candle_15m(self, fn):
        self.candle_15m_handlers.append(fn)


def _candle(i: int) -> Candle:
    return Candle(open=100.0 + i, high=101.0 + i, low=99.0 + i,
                  close=100.0 + i, volume=1.0, timestamp=i * 900_000)


def test_wire_strategy_registers_trade_1m_and_15m_handlers_only():
    state = MarketState()
    feed = _FakeFeed()
    engine = ExecutionEngine(state)

    wire_strategy(state, feed, engine)

    assert len(feed.trade_handlers) == 1
    assert len(feed.candle_1m_handlers) == 1   # debug logging only
    assert len(feed.candle_5m_handlers) == 0   # nothing left to do on 5m closes
    assert len(feed.candle_15m_handlers) == 1  # full signal pipeline


def test_wire_strategy_on_trade_handler_runs_without_raising():
    state = MarketState()
    feed = _FakeFeed()
    engine = ExecutionEngine(state)
    wire_strategy(state, feed, engine)

    asyncio.run(feed.trade_handlers[0](100.0, 1.0, False, 0.0))  # must not raise


def test_on_candle_15m_handler_updates_atr_from_15m_buffer():
    state = MarketState()
    for i in range(25):
        state.candles_15m.append(_candle(i))
    feed = _FakeFeed()
    engine = ExecutionEngine(state)
    wire_strategy(state, feed, engine)

    asyncio.run(feed.candle_15m_handlers[0](_candle(25)))

    assert state.atr > 0.0


def test_on_candle_1m_handler_does_not_run_the_signal_pipeline():
    state = MarketState()
    for i in range(25):
        state.candles_1m.append(_candle(i))
    feed = _FakeFeed()
    engine = ExecutionEngine(state)
    wire_strategy(state, feed, engine)

    asyncio.run(feed.candle_1m_handlers[0](_candle(25)))

    assert state.atr == 0.0  # ATR now comes only from the 15m pipeline
```

- [ ] **Step 2: Correr los tests nuevos y verificar que fallan**

Run: `.venv/bin/python -m pytest tests/test_main.py -v`
Expected: FAIL (`candle_5m_handlers` tiene 1 handler; el handler de 1m sí actualiza ATR).

- [ ] **Step 3: Cambiar config.py**

En `config.py`, reemplazar estas cuatro líneas (mantener el resto igual):

```python
# Time-based exits (minutes; the signal clock is the 15m candle close)
TIME_EXIT_MINUTES = 225       # 15 bars of 15m
MOMENTUM_ABORT_MINUTES = 45   # 3 bars of 15m
```

```python
# Spread filter
SPREAD_FILTER_ATR_PCT = 0.01  # block entries when spread > 1% of 15m ATR (~5.5x the old 1m ATR)
```

```python
# Backtesting
BACKTEST_SYNTHETIC_SPREAD_PCT = 0.00001  # 0.001% of price per side (~10x the typical real BTCUSDT futures spread); must stay well below SPREAD_FILTER_ATR_PCT * typical 15m ATR% or the spread gate blocks every backtest entry
```

- [ ] **Step 4: Re-apuntar los consumidores de velas de señal a `candles_15m`**

Cambios exactos, uno por archivo (solo se muestra la línea afectada; el resto de cada función queda igual):

`indicators.py` — en `update_indicators`, el primer bloque:

```python
    if len(state.candles_15m) >= 2:
        state.atr = compute_atr(state.candles_15m)
        closes_signal = [c.close for c in state.candles_15m]
        period = ema_period_for_regime(state.regime)
        state.ema = compute_ema(closes_signal, period)
```

(dejar por ahora los bloques de `ema_5m`/`ema_15m` como están — Task 2 los reemplaza).

`regime.py` — en `_infer_candidate`: `c_list = list(state.candles_15m)` y `swept = _has_liquidity_sweeps_at_both_extremes(state.candles_15m)`. En `_ema_is_sloping`: `c_list = list(state.candles_15m)`. En `update_regime`: `if len(state.candles_15m) < 10:`.

`signals.py` — en `update_squeeze`: `candles = list(state.candles_15m)`. En `check_entry_signal`, bloque BREAKOUT: `candles = list(state.candles_15m)`.

`order_flow.py` — en `detect_cvd_divergence`: `candles = list(state.candles_15m)`.

`risk.py` — en `_apply_structural_trail`: `highs, lows = detect_swing_points(state.candles_15m, lookback=3)`.

- [ ] **Step 5: Reescribir `wire_strategy` en `main.py`**

Reemplazar los cuatro handlers dentro de `wire_strategy` (mismo docstring, mismos imports salvo que ya no se registra `on_candle_5m`):

```python
    # -------------------------------------------------------------------------
    # Tick handler — runs on every trade event (sub-second)
    # -------------------------------------------------------------------------
    async def on_trade(price: float, qty: float, is_buyer_maker: bool, ts: float) -> None:
        update_volume_velocity(state)
        await engine.monitor_and_exit()

    # -------------------------------------------------------------------------
    # 1-minute candle close — debug heartbeat only (signal clock is 15m)
    # -------------------------------------------------------------------------
    async def on_candle_1m(candle: Candle) -> None:
        logger.debug("1m | close=%.2f", candle.close)

    # -------------------------------------------------------------------------
    # 15-minute candle close — primary signal evaluation clock
    # -------------------------------------------------------------------------
    async def on_candle_15m(candle: Candle) -> None:
        # 1. Snapshot CVD for this closed candle, reset for next
        snapshot_cvd_on_close(state)

        # 2. Recompute adaptive indicators (ATR, regime-aware EMA)
        update_indicators(state)

        # 3. Update regime state machine (hysteresis protected)
        update_regime(state)

        # 4. Update MTF trend bias
        update_mtf_trend(state)
        update_mtf_trends(state)

        # 5. Refresh structural swing points
        highs, lows = detect_swing_points(state.candles_15m)
        state.swing_highs.clear()
        state.swing_highs.extend(highs)
        state.swing_lows.clear()
        state.swing_lows.extend(lows)

        # 6. Evaluate squeeze state
        update_squeeze(state)

        # 7. Check for entry signal (only if flat and kill switch is not active)
        if state.position is None and safety.can_open_new_position(state, engine.exchange):
            signal = check_entry_signal(state)
            if signal is not None:
                await engine.enter(signal)

        logger.info(
            "15m | close=%.2f atr=%.2f ema=%.2f regime=%s squeeze=%s",
            candle.close, state.atr, state.ema, state.regime.value, state.in_squeeze,
        )

    feed.on_trade(on_trade)
    feed.on_candle_1m(on_candle_1m)
    feed.on_candle_15m(on_candle_15m)
```

Nota: los antiguos handlers `on_candle_5m`/`on_candle_15m` (que solo hacían `update_indicators` + `update_mtf_trend`) desaparecen; su trabajo vive ahora dentro del pipeline de 15m.

- [ ] **Step 6: Verificar que los tests de wiring pasan**

Run: `.venv/bin/python -m pytest tests/test_main.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Migrar los tests de módulos de señal (mecánico)**

```bash
sed -i 's/candles_1m/candles_15m/g' tests/test_signals.py tests/test_regime.py tests/test_order_flow.py
```

En `tests/test_indicators.py` el sed NO sirve (tiene tests legítimos de `candles_5m`/`candles_15m` para las EMAs MTF): editar a mano solo los tests de ATR y de la EMA regime-adaptive (los que hoy pueblan `state.candles_1m` y assertean `state.atr`/`state.ema`) para poblar `state.candles_15m`. Dejar intactos los tests de `ema_5m`/`ema_15m` (Task 2 los reemplaza).

- [ ] **Step 8: Correr la suite completa y arreglar supuestos de tiempo hardcodeados**

Run: `.venv/bin/python -m pytest -q`

Fallos esperables y su fix (regla única: los tests no deben hardcodear minutos, deben importar la constante):
- Tests de time exit que avanzan el reloj 15 minutos → `from config import TIME_EXIT_MINUTES` y avanzar `TIME_EXIT_MINUTES * 60` segundos.
- Tests de momentum abort que avanzan 3 minutos → `from config import MOMENTUM_ABORT_MINUTES` y avanzar `MOMENTUM_ABORT_MINUTES * 60`.
- Tests de spread filter que asuman el umbral 0.05 → usar `SPREAD_FILTER_ATR_PCT` importado.
- `tests/test_backtest.py` no requiere cambios (su e2e espera 0 trades por falta de warmup, lo cual sigue siendo cierto).

Expected final: PASS toda la suite.

- [ ] **Step 9: Commit**

```bash
git add config.py indicators.py regime.py signals.py order_flow.py risk.py main.py tests/
git commit -m "Switch the signal clock from 1m to 15m candles"
```

---

### Task 2: Filtro de tendencia 1h y deduplicación del cálculo MTF

El gate de tendencia dejaba de tener sentido (filtraba señal de 1m con EMA de 15m; ahora la señal ES de 15m). Se reemplaza por una EMA-80 sobre cierres de 15m ≈ EMA-20 de 1h, sin streams nuevos. De paso se elimina la duplicación `regime.update_mtf_trend` / `context.update_mtf_trends` y el estado muerto `trend_5m` (hallazgo N7 y P1-4 de los docs de revisión).

**Files:**
- Modify: `config.py` (eliminar `TREND_EMA_5M`, `TREND_EMA_15M`; agregar `TREND_EMA_1H_ON_15M`)
- Modify: `state.py:105-139` (campos de EMA/trend)
- Modify: `indicators.py` (import y `update_indicators`)
- Modify: `regime.py:120-139` (reemplazar `update_mtf_trend` por `update_trend_1h`)
- Modify: `context.py:12-28` (borrar `update_mtf_trends`)
- Modify: `signals.py:98-101` (gate de tendencia)
- Modify: `main.py` (imports y llamadas)
- Test: `tests/test_regime.py`, `tests/test_signals.py`, `tests/test_indicators.py`, `tests/test_context.py`

**Interfaces:**
- Consumes: `state.candles_15m` (Task 1).
- Produces: `state.ema_1h: float` (default 0.0) y `state.trend_1h: Optional[Side]` (default None); función `regime.update_trend_1h(state: MarketState) -> None`. El gate de `check_entry_signal` lee `state.trend_1h`. Los campos `ema_5m`, `ema_15m`, `trend_5m`, `trend_15m` DEJAN DE EXISTIR.

- [ ] **Step 1: Tests que fallan para `update_trend_1h` y el gate**

En `tests/test_regime.py`, borrar los tests existentes de `update_mtf_trend` (los que assertean `trend_15m`/`trend_5m`) y agregar:

```python
from regime import update_trend_1h
from state import Side


def test_trend_1h_long_when_price_above_ema_band():
    state = MarketState()
    state.ema_1h = 100.0
    state.last_price = 100.1  # > 100 * 1.0005
    update_trend_1h(state)
    assert state.trend_1h == Side.LONG


def test_trend_1h_short_when_price_below_ema_band():
    state = MarketState()
    state.ema_1h = 100.0
    state.last_price = 99.9  # < 100 * 0.9995
    update_trend_1h(state)
    assert state.trend_1h == Side.SHORT


def test_trend_1h_unchanged_inside_deadband():
    state = MarketState()
    state.ema_1h = 100.0
    state.trend_1h = Side.LONG
    state.last_price = 100.01  # inside +-0.05% deadband
    update_trend_1h(state)
    assert state.trend_1h == Side.LONG  # no flip-flop at the EMA


def test_trend_1h_noop_without_ema():
    state = MarketState()
    state.last_price = 100.0
    update_trend_1h(state)
    assert state.trend_1h is None
```

En `tests/test_signals.py`, en el test del gate de tendencia (el que hoy setea `state.trend_15m` opuesto y espera rechazo): renombrar `trend_15m` → `trend_1h` (el sed de Task 1 no lo tocó porque no es un buffer de velas).

En `tests/test_indicators.py`, reemplazar los tests de `ema_5m`/`ema_15m` por:

```python
def test_update_indicators_computes_ema_1h_from_15m_closes():
    state = MarketState()
    for i in range(30):
        state.candles_15m.append(
            Candle(open=100.0, high=101.0, low=99.0, close=100.0 + i, volume=1.0, timestamp=i * 900_000)
        )
    update_indicators(state)
    assert state.ema_1h > 0.0
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `.venv/bin/python -m pytest tests/test_regime.py tests/test_indicators.py -v`
Expected: FAIL con `ImportError: cannot import name 'update_trend_1h'` y `AttributeError: ema_1h`.

- [ ] **Step 3: Implementar**

`config.py` — reemplazar el bloque MTF:

```python
# Higher-timeframe trend filter: EMA over 15m closes approximating a 20-period 1h EMA
TREND_EMA_1H_ON_15M = 80
```

`state.py` — en `MarketState`, reemplazar:

```python
    # Adaptive indicators
    atr: float = 0.0
    ema: float = 0.0       # signal-timeframe (15m) EMA, period varies by regime
    ema_1h: float = 0.0    # EMA-80 over 15m closes ~ 1h EMA-20
```

y reemplazar el bloque "Multi-timeframe trend bias" por:

```python
    # Higher-timeframe trend bias
    trend_1h: Optional[Side] = None
```

`indicators.py` — actualizar el import (`TREND_EMA_1H_ON_15M` en vez de `TREND_EMA_5M, TREND_EMA_15M`) y dejar `update_indicators` así:

```python
def update_indicators(state: MarketState) -> None:
    """Recompute ATR, the regime-adaptive signal EMA, and the 1h-equivalent trend EMA,
    all from the 15m candle buffer (the signal timeframe)."""
    if len(state.candles_15m) >= 2:
        state.atr = compute_atr(state.candles_15m)
        closes = [c.close for c in state.candles_15m]
        state.ema = compute_ema(closes, ema_period_for_regime(state.regime))
        state.ema_1h = compute_ema(closes, TREND_EMA_1H_ON_15M)
```

`regime.py` — reemplazar `update_mtf_trend` completo por:

```python
def update_trend_1h(state: MarketState) -> None:
    """Set the 1h-equivalent trend bias from price vs the EMA-80-on-15m,
    with a +-0.05% deadband to avoid flip-flopping at the EMA."""
    p = state.last_price
    if p <= 0 or state.ema_1h <= 0:
        return
    if p > state.ema_1h * 1.0005:
        state.trend_1h = Side.LONG
    elif p < state.ema_1h * 0.9995:
        state.trend_1h = Side.SHORT
```

`context.py` — borrar la función `update_mtf_trends` entera (líneas 12-28) y el import de `Side` si queda sin uso. `MacroFilter` no se toca.

`signals.py` — el gate:

```python
    # Hard block: never trade against the confirmed higher-timeframe trend
    if state.trend_1h is not None and state.trend_1h != direction:
        logger.debug("Signal rejected: 1h trend %s opposes %s", state.trend_1h, direction)
        return None
```

`main.py` — actualizar imports (`from regime import update_regime, update_trend_1h`; quitar `update_mtf_trends` del import de `context`, dejando solo `MacroFilter`) y en `on_candle_15m` reemplazar el paso 4 por:

```python
        # 4. Update higher-timeframe trend bias
        update_trend_1h(state)
```

- [ ] **Step 4: Barrido de referencias muertas**

```bash
grep -rn "trend_15m\|trend_5m\|ema_5m\|ema_15m\|update_mtf_trend" --include="*.py" . | grep -v .venv
```

Expected: cero resultados fuera de este plan. Si aparece algo (p. ej. en `tests/test_context.py`, que testea `update_mtf_trends`): borrar esos tests; los de `MacroFilter` se conservan. `indicators.update_indicators` ya no computa `ema_5m`/`ema_15m` (los buffers `candles_5m` siguen llenándose en los feeds; queda como dato disponible sin consumidor, no romper los feeds).

- [ ] **Step 5: Suite completa verde**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add config.py state.py indicators.py regime.py context.py signals.py main.py tests/
git commit -m "Replace the MTF trend gate with a 1h-equivalent EMA on 15m closes"
```

---

### Task 3: API de entrada planificada en risk.py (`plan_entry` / `open_planned` + fee parametrizable)

La entrada maker necesita separar "calcular tamaño/niveles" (al colocar la orden) de "abrir la posición" (al llenarse, quizá minutos después, con fee maker). Hoy `open_position` hace ambas cosas con `TAKER_FEE_RATE` hardcodeado.

**Files:**
- Modify: `risk.py:25-85`
- Test: `tests/test_risk.py`

**Interfaces:**
- Consumes: `state.atr`, `state.daily_starting_balance`, helpers privados existentes `_compute_levels` / `_compute_size`.
- Produces (Task 4 y 5 dependen de esto, firmas exactas):

```python
@dataclass
class EntryPlan:
    side: Side
    price: float       # limit price the plan was built around
    size: float        # BTC
    stop_loss: float
    tp1: float
    atr: float         # ATR at planning time → Position.initial_atr

def plan_entry(state: MarketState, side: Side, price: float,
               balance: Optional[float] = None) -> Optional[EntryPlan]
def open_planned(state: MarketState, plan: EntryPlan,
                 fee_rate: float = TAKER_FEE_RATE) -> None
def open_position(state, side, price, balance=None) -> None  # wrapper preservado
```

- [ ] **Step 1: Tests que fallan**

Agregar a `tests/test_risk.py`:

```python
from config import ACCOUNT_RISK_PCT, INITIAL_SL_ATR, MAKER_FEE_RATE, TAKER_FEE_RATE
from risk import EntryPlan, open_planned, plan_entry


def test_plan_entry_builds_size_and_levels_without_opening():
    state = MarketState()
    state.atr = 2.0
    plan = plan_entry(state, Side.LONG, 100.0, balance=10_000.0)

    assert state.position is None
    assert plan.side == Side.LONG
    assert plan.price == pytest.approx(100.0)
    assert plan.stop_loss == pytest.approx(100.0 - INITIAL_SL_ATR * 2.0)
    assert plan.size == pytest.approx(10_000.0 * ACCOUNT_RISK_PCT / (INITIAL_SL_ATR * 2.0))
    assert plan.atr == pytest.approx(2.0)


def test_plan_entry_returns_none_when_atr_is_zero():
    state = MarketState()
    state.atr = 0.0
    assert plan_entry(state, Side.LONG, 100.0, balance=10_000.0) is None


def test_open_planned_applies_the_given_fee_rate():
    state = MarketState()
    state.atr = 2.0
    plan = plan_entry(state, Side.LONG, 100.0, balance=10_000.0)

    open_planned(state, plan, fee_rate=MAKER_FEE_RATE)

    pos = state.position
    assert pos is not None
    assert pos.entry_price == pytest.approx(100.0)
    assert pos.fees_paid == pytest.approx(plan.size * 100.0 * MAKER_FEE_RATE)
    assert state.pnl_today == pytest.approx(-pos.fees_paid)


def test_open_position_wrapper_still_charges_taker_fee():
    state = MarketState()
    state.atr = 2.0
    open_position(state, Side.LONG, 100.0, balance=10_000.0)
    pos = state.position
    assert pos.fees_paid == pytest.approx(pos.size * 100.0 * TAKER_FEE_RATE)
```

(Nota: `MAKER_FEE_RATE` aún no existe en config — este task la agrega; los tests de `test_risk.py` ya tienen el fixture `_isolate_state_file`-equivalente vía `safety.save_state`; si el archivo usa un fixture de aislamiento como `tests/test_execution.py`, respetarlo.)

- [ ] **Step 2: Correr y verificar que fallan**

Run: `.venv/bin/python -m pytest tests/test_risk.py -v`
Expected: FAIL con `ImportError: cannot import name 'plan_entry'`.

- [ ] **Step 3: Implementar en `risk.py`**

Agregar a `config.py` (sección Fees):

```python
MAKER_FEE_RATE = 0.0002   # 0.02% per side, Binance Futures USDT-M maker, no BNB discount
```

En `risk.py`, agregar `from dataclasses import dataclass` al tope y reemplazar `open_position` por:

```python
@dataclass
class EntryPlan:
    """Sizing and levels computed at order placement time; consumed at fill time."""
    side: Side
    price: float
    size: float
    stop_loss: float
    tp1: float
    atr: float


def plan_entry(
    state: MarketState,
    side: Side,
    price: float,
    balance: Optional[float] = None,
) -> Optional[EntryPlan]:
    if balance is None:
        balance = (
            state.daily_starting_balance
            if state.daily_starting_balance is not None
            else PAPER_BALANCE_USDT
        )
    stop_loss, tp1 = _compute_levels(side, price, state.atr)
    size = _compute_size(price, stop_loss, balance)
    if size <= 0:
        return None
    return EntryPlan(side=side, price=price, size=size, stop_loss=stop_loss, tp1=tp1, atr=state.atr)


def open_planned(state: MarketState, plan: EntryPlan, fee_rate: float = TAKER_FEE_RATE) -> None:
    sl_dist = abs(plan.price - plan.stop_loss)
    entry_fee = plan.size * plan.price * fee_rate

    state.position = Position(
        side=plan.side,
        entry_price=plan.price,
        size=plan.size,
        entry_time=clock.now(),
        stop_loss=plan.stop_loss,
        tp1=plan.tp1,
        initial_atr=plan.atr,
        initial_sl_distance=sl_dist,
        fees_paid=entry_fee,
        realized_pnl=-entry_fee,
    )
    state.pnl_today -= entry_fee
    state.prior_volume_velocity = state.volume_velocity

    logger.info(
        "OPEN %s @ %.2f | SL=%.2f | TP1=%.2f | size=%.6f BTC | risk=$%.2f | entry_fee=$%.2f",
        plan.side.value.upper(), plan.price, plan.stop_loss, plan.tp1,
        plan.size, plan.size * sl_dist, entry_fee,
    )
    safety.save_state(state)


def open_position(
    state: MarketState,
    side: Side,
    price: float,
    balance: Optional[float] = None,
) -> None:
    plan = plan_entry(state, side, price, balance)
    if plan is None:
        return
    open_planned(state, plan, fee_rate=TAKER_FEE_RATE)
```

- [ ] **Step 4: Suite verde**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (el wrapper preserva el comportamiento de todos los llamadores existentes).

- [ ] **Step 5: Commit**

```bash
git add config.py risk.py tests/test_risk.py
git commit -m "Add plan_entry/open_planned with parametrizable entry fee"
```

---

### Task 4: Entrada maker en paper/backtest (orden límite pendiente con fill-through y timeout)

`enter()` deja de abrir al instante: coloca una `PendingEntry` en el mejor bid (LONG) / ask (SHORT). En cada trade tick, `check_pending_entry()` la llena **solo si el precio la atraviesa estrictamente** (supuesto de cola conservador: estar al mejor precio no garantiza fill; que se opere a través de tu precio, sí) con `MAKER_FEE_RATE`, o la cancela pasado `ENTRY_ORDER_TIMEOUT_SECONDS`. El backtest replaya trades reales, así que esta simulación corre idéntica en paper y backtest sin tocar `backtest_feed.py`.

**Files:**
- Modify: `config.py` (nueva constante)
- Modify: `execution.py` (PendingEntry, `enter`, `check_pending_entry`, `has_pending_entry`)
- Modify: `main.py` (hook en `on_trade`)
- Test: `tests/test_execution.py` (reescritura), `tests/test_main.py` (un test nuevo)

**Interfaces:**
- Consumes: `EntryPlan`, `plan_entry`, `open_planned` (Task 3); `clock.now()`; `MAKER_FEE_RATE`, `ENTRY_ORDER_TIMEOUT_SECONDS`.
- Produces:

```python
@dataclass
class PendingEntry:
    plan: EntryPlan
    placed_at: float                 # clock seconds
    order_id: Optional[str] = None   # live only (Task 5)

ExecutionEngine.has_pending_entry -> bool                 # property
async ExecutionEngine.enter(side) -> bool                 # True = order placed (NOT filled)
async ExecutionEngine.check_pending_entry() -> None       # called on every trade tick
```

`_on_trade_opened` pasa a dispararse en el FILL, no al colocar la orden.

- [ ] **Step 1: Reescribir `tests/test_execution.py`**

Contenido completo nuevo del archivo:

```python
import asyncio

import pytest

import clock
import execution as execution_module
import safety
from config import ENTRY_ORDER_TIMEOUT_SECONDS, MAKER_FEE_RATE
from execution import ExecutionEngine
from state import MarketState, Side


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    path = tmp_path / "safety_state.json"
    monkeypatch.setattr(safety, "STATE_FILE_PATH", str(path))
    return path


def _state_with_book(bid: float = 99.0, ask: float = 101.0, last_price: float = 100.0) -> MarketState:
    state = MarketState()
    state.last_bid = bid
    state.last_ask = ask
    state.last_price = last_price
    state.atr = 2.0
    return state


def _fill_pending(engine: ExecutionEngine, state: MarketState, through_price: float) -> None:
    """Simulate a trade tick printing through the pending limit price."""
    state.last_price = through_price
    asyncio.run(engine.check_pending_entry())


def _open_long(engine: ExecutionEngine, state: MarketState) -> None:
    asyncio.run(engine.enter(Side.LONG))
    _fill_pending(engine, state, state.last_bid - 0.01)


# --- placement ---

def test_enter_long_places_pending_limit_at_bid_not_a_position():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)

    result = asyncio.run(engine.enter(Side.LONG))

    assert result is True
    assert state.position is None
    assert engine.has_pending_entry
    assert engine._pending_entry.plan.price == pytest.approx(99.0)


def test_enter_short_places_pending_limit_at_ask():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)

    asyncio.run(engine.enter(Side.SHORT))

    assert engine._pending_entry.plan.price == pytest.approx(101.0)


def test_enter_rejects_when_book_not_yet_received():
    state = MarketState()  # last_bid/last_ask default to 0.0
    state.last_price = 100.0
    engine = ExecutionEngine(state)

    result = asyncio.run(engine.enter(Side.LONG))

    assert result is False
    assert not engine.has_pending_entry


def test_enter_rejects_while_another_entry_is_pending():
    state = _state_with_book()
    engine = ExecutionEngine(state)
    asyncio.run(engine.enter(Side.LONG))

    result = asyncio.run(engine.enter(Side.LONG))

    assert result is False


# --- paper fills ---

def test_pending_long_fills_at_limit_when_price_trades_through():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    asyncio.run(engine.enter(Side.LONG))

    _fill_pending(engine, state, 98.9)

    pos = state.position
    assert pos is not None
    assert not engine.has_pending_entry
    assert pos.entry_price == pytest.approx(99.0)
    assert pos.fees_paid == pytest.approx(pos.size * 99.0 * MAKER_FEE_RATE)


def test_pending_long_does_not_fill_at_exactly_the_limit_price():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    asyncio.run(engine.enter(Side.LONG))

    _fill_pending(engine, state, 99.0)  # touched, not traded through

    assert state.position is None
    assert engine.has_pending_entry


def test_pending_short_fills_when_price_trades_above_limit():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    asyncio.run(engine.enter(Side.SHORT))

    _fill_pending(engine, state, 101.1)

    assert state.position is not None
    assert state.position.entry_price == pytest.approx(101.0)


def test_pending_entry_times_out_and_is_cancelled(monkeypatch):
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    t0 = clock.now()
    asyncio.run(engine.enter(Side.LONG))

    monkeypatch.setattr(clock, "now", lambda: t0 + ENTRY_ORDER_TIMEOUT_SECONDS + 1)
    _fill_pending(engine, state, 98.9)  # would fill, but the order expired first

    assert state.position is None
    assert not engine.has_pending_entry


def test_check_pending_entry_is_a_noop_with_nothing_pending():
    state = _state_with_book()
    engine = ExecutionEngine(state)
    asyncio.run(engine.check_pending_entry())  # must not raise
    assert state.position is None


# --- exits (unchanged mechanics, now driven through the fill helper) ---

def test_exit_long_fills_at_bid_in_paper_mode():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    _open_long(engine, state)

    net = asyncio.run(engine.exit("time_exit"))

    assert state.position is None
    assert isinstance(net, float)


def test_partial_exit_sends_reduce_only_order_in_live_mode(monkeypatch):
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    _open_long(engine, state)

    sent_orders = []

    class _FakeExchange:
        def create_market_order(self, symbol, side, amount, params=None):
            sent_orders.append((symbol, side, amount, params))

    engine._exchange = _FakeExchange()
    monkeypatch.setattr(execution_module, "PAPER_MODE", False)

    close_size = round(state.position.size * 0.5, 6)
    asyncio.run(engine.partial_exit(close_size, "tp1"))

    assert len(sent_orders) == 1
    symbol, side, amount, params = sent_orders[0]
    assert symbol == "BTC/USDT"
    assert side == "sell"
    assert amount == pytest.approx(close_size)
    assert params == {"reduceOnly": True}


def test_exchange_property_exposes_underlying_client():
    state = MarketState()
    engine = ExecutionEngine(state)
    engine._exchange = "fake-client"

    assert engine.exchange == "fake-client"


# --- hooks ---

def test_on_trade_opened_fires_at_fill_not_at_placement():
    state = _state_with_book(bid=99.0, ask=101.0)
    captured = []
    engine = ExecutionEngine(state, on_trade_opened=captured.append)

    asyncio.run(engine.enter(Side.LONG))
    assert captured == []  # placed, not filled

    _fill_pending(engine, state, 98.9)

    assert len(captured) == 1
    record = captured[0]
    assert record["side"] == Side.LONG
    assert record["entry_price"] == pytest.approx(99.0)
    assert record["size"] == pytest.approx(state.position.size)
    assert record["stop_loss"] == pytest.approx(state.position.stop_loss)
    assert record["tp1"] == pytest.approx(state.position.tp1)


def test_exit_calls_on_trade_closed_hook_with_full_trade_details():
    state = _state_with_book(bid=99.0, ask=101.0)
    captured = []
    engine = ExecutionEngine(state, on_trade_closed=captured.append)
    _open_long(engine, state)
    entry_price = state.position.entry_price
    size = state.position.size
    state.last_bid = 99.0  # exit fill reference

    net = asyncio.run(engine.exit("time_exit"))

    assert len(captured) == 1
    record = captured[0]
    assert record["side"] == Side.LONG
    assert record["entry_price"] == pytest.approx(entry_price)
    assert record["exit_price"] == pytest.approx(99.0)
    assert record["size"] == pytest.approx(size)
    assert record["reason"] == "time_exit"
    assert record["leg_net"] == pytest.approx(net)
    assert record["total_trade_net"] is not None
    assert record["is_partial"] is False


def test_partial_exit_calls_on_trade_closed_hook_with_leg_size_not_remaining_size():
    state = _state_with_book(bid=99.0, ask=101.0)
    captured = []
    engine = ExecutionEngine(state, on_trade_closed=captured.append)
    _open_long(engine, state)
    close_size = round(state.position.size * 0.5, 6)

    asyncio.run(engine.partial_exit(close_size, "tp1"))

    assert len(captured) == 1
    record = captured[0]
    assert record["size"] == pytest.approx(close_size)
    assert record["is_partial"] is True
    assert record["total_trade_net"] is None


def test_hooks_default_to_none_and_do_not_raise():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)  # no hooks passed
    _open_long(engine, state)
    asyncio.run(engine.exit("time_exit"))  # must not raise
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `.venv/bin/python -m pytest tests/test_execution.py -v`
Expected: FAIL (`has_pending_entry` no existe; `enter` abre posición al instante).

- [ ] **Step 3: Implementar en `execution.py`**

Agregar a `config.py` (junto a las constantes de fees):

```python
ENTRY_ORDER_TIMEOUT_SECONDS = 300  # cancel an unfilled post-only entry after 5 min (1/3 of a 15m bar)
```

En `execution.py`: reemplazar el import de risk por
`from risk import EntryPlan, apply_partial_close, close_position, manage_position, open_planned, plan_entry`,
agregar `from dataclasses import dataclass` y `from config import ENTRY_ORDER_TIMEOUT_SECONDS, MAKER_FEE_RATE`, y:

```python
@dataclass
class PendingEntry:
    """A resting post-only limit entry, placed but not yet filled."""
    plan: EntryPlan
    placed_at: float                # clock seconds
    order_id: Optional[str] = None  # live only
```

En `ExecutionEngine.__init__`, agregar `self._pending_entry: Optional[PendingEntry] = None`.

Agregar la property y reescribir `enter`:

```python
    @property
    def has_pending_entry(self) -> bool:
        return self._pending_entry is not None

    async def enter(self, side: Side) -> bool:
        """Place a post-only limit entry at the best bid/ask. Returns True if the
        order was placed (NOT filled) — the position opens in check_pending_entry."""
        if self.state.position is not None or self._pending_entry is not None:
            return False
        if self.state.last_bid <= 0 or self.state.last_ask <= 0:
            return False

        limit_price = self.state.last_bid if side == Side.LONG else self.state.last_ask
        plan = plan_entry(self.state, side, limit_price)
        if plan is None:
            return False

        # Live post-only routing lands in Task 5; until then live mode
        # behaves like paper for entries (position is simulated).
        self._pending_entry = PendingEntry(plan=plan, placed_at=clock.now())
        logger.info(
            "ENTRY PENDING %s limit @ %.2f | size=%.6f BTC | timeout=%ds",
            side.value.upper(), limit_price, plan.size, ENTRY_ORDER_TIMEOUT_SECONDS,
        )
        return True

    def _fill_pending(self, plan: EntryPlan) -> None:
        self._pending_entry = None
        open_planned(self.state, plan, fee_rate=MAKER_FEE_RATE)
        opened = self.state.position
        if self._on_trade_opened is not None and opened is not None:
            self._on_trade_opened({
                "side": opened.side, "entry_price": opened.entry_price,
                "size": opened.size, "stop_loss": opened.stop_loss, "tp1": opened.tp1,
            })

    async def check_pending_entry(self) -> None:
        """Called on every trade tick. Fills or expires the resting entry order.

        Paper fill model: the limit fills only when a trade prints strictly THROUGH
        the limit price (conservative queue assumption — touching your price does
        not guarantee a fill; trading through it does)."""
        pending = self._pending_entry
        if pending is None:
            return

        if clock.now() - pending.placed_at >= ENTRY_ORDER_TIMEOUT_SECONDS:
            self._pending_entry = None
            logger.info("Entry order timed out unfilled — cancelled")
            return

        p = self.state.last_price
        plan = pending.plan
        traded_through = (
            (plan.side == Side.LONG and p < plan.price)
            or (plan.side == Side.SHORT and p > plan.price)
        )
        if traded_through:
            self._fill_pending(plan)
```

Actualizar también el docstring de la clase (`PAPER_MODE=true → entries rest as post-only limits filled when price trades through; exits cross the spread as before`).

- [ ] **Step 4: Hook en `main.py`**

En `wire_strategy`, el handler `on_trade` queda:

```python
    async def on_trade(price: float, qty: float, is_buyer_maker: bool, ts: float) -> None:
        update_volume_velocity(state)
        await engine.check_pending_entry()
        await engine.monitor_and_exit()
```

Y agregar a `tests/test_main.py` (cambiando su import de state a `from state import Candle, MarketState, Side`):

```python
def test_on_trade_handler_checks_pending_entries():
    state = MarketState()
    state.last_bid = 99.0
    state.last_ask = 101.0
    state.last_price = 100.0
    state.atr = 2.0
    feed = _FakeFeed()
    engine = ExecutionEngine(state)
    wire_strategy(state, feed, engine)
    asyncio.run(engine.enter(Side.LONG))

    # the trade handler does not mutate last_price (the feed does); simulate the feed:
    state.last_price = 98.9
    asyncio.run(feed.trade_handlers[0](98.9, 1.0, False, 0.0))

    assert state.position is not None
```

- [ ] **Step 5: Suite completa verde**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. Vigilar especialmente `tests/test_backtest.py` (e2e sigue esperando 0 trades) y `tests/test_notifications.py` (el hook de apertura ahora dispara en el fill — su contrato/payload no cambió).

- [ ] **Step 6: Commit**

```bash
git add config.py execution.py main.py tests/
git commit -m "Add resting maker entries with trade-through fills and timeout in paper mode"
```

---

### Task 5: Ruta live post-only (GTX) con polling de fills y cancelación al arrancar

**Files:**
- Modify: `execution.py` (`enter` live branch, `check_pending_entry` live branch, `cancel_open_orders`)
- Modify: `main.py:127-129` (startup live)
- Test: `tests/test_execution.py` (agregar tests con exchange fake)

**Interfaces:**
- Consumes: `PendingEntry.order_id`, `dataclasses.replace`, ccxt (`create_limit_order` con `params={"timeInForce": "GTX"}` — post-only nativo de Binance Futures: la orden se rechaza si cruzaría el book), `fetch_order`, `cancel_order`, `cancel_all_orders`.
- Produces: `ExecutionEngine.cancel_open_orders() -> None` (llamada en el startup live desde `main.run`). Polling de fills con throttle `_LIVE_FILL_POLL_SECONDS = 5.0` (constante de módulo en `execution.py`).

- [ ] **Step 1: Tests que fallan**

Agregar a `tests/test_execution.py`:

```python
class _FakeLiveExchange:
    def __init__(self):
        self.limit_orders = []
        self.cancelled = []
        self.cancel_all_calls = []
        self.order_status = {"status": "open", "filled": 0.0}

    def create_limit_order(self, symbol, side, amount, price, params=None):
        self.limit_orders.append((symbol, side, amount, price, params))
        return {"id": "oid-1"}

    def fetch_order(self, order_id, symbol):
        return dict(self.order_status, id=order_id)

    def cancel_order(self, order_id, symbol):
        self.cancelled.append(order_id)

    def cancel_all_orders(self, symbol):
        self.cancel_all_calls.append(symbol)


def _live_engine(state, monkeypatch):
    engine = ExecutionEngine(state)
    fake = _FakeLiveExchange()
    engine._exchange = fake
    monkeypatch.setattr(execution_module, "PAPER_MODE", False)
    return engine, fake


def test_live_enter_sends_post_only_gtx_limit(monkeypatch):
    state = _state_with_book(bid=99.0, ask=101.0)
    engine, fake = _live_engine(state, monkeypatch)

    result = asyncio.run(engine.enter(Side.LONG))

    assert result is True
    assert state.position is None
    symbol, side, amount, price, params = fake.limit_orders[0]
    assert (symbol, side) == ("BTC/USDT", "buy")
    assert price == pytest.approx(99.0)
    assert params == {"timeInForce": "GTX"}
    assert engine._pending_entry.order_id == "oid-1"


def test_live_post_only_rejection_means_no_trade(monkeypatch):
    state = _state_with_book(bid=99.0, ask=101.0)
    engine, fake = _live_engine(state, monkeypatch)

    def _reject(*a, **k):
        raise RuntimeError("Order would immediately match and take")

    fake.create_limit_order = _reject
    result = asyncio.run(engine.enter(Side.LONG))

    assert result is False
    assert not engine.has_pending_entry


def test_live_fill_detected_by_polling_opens_position_with_maker_fee(monkeypatch):
    state = _state_with_book(bid=99.0, ask=101.0)
    engine, fake = _live_engine(state, monkeypatch)
    asyncio.run(engine.enter(Side.LONG))
    fake.order_status = {"status": "closed", "filled": 0.5}
    engine._last_fill_poll = 0.0  # force the next poll

    asyncio.run(engine.check_pending_entry())

    pos = state.position
    assert pos is not None
    assert pos.entry_price == pytest.approx(99.0)
    assert pos.fees_paid == pytest.approx(pos.size * 99.0 * MAKER_FEE_RATE)


def test_live_timeout_cancels_and_keeps_partial_fill(monkeypatch):
    state = _state_with_book(bid=99.0, ask=101.0)
    engine, fake = _live_engine(state, monkeypatch)
    t0 = clock.now()
    asyncio.run(engine.enter(Side.LONG))
    planned_size = engine._pending_entry.plan.size
    fake.order_status = {"status": "open", "filled": round(planned_size / 2, 6)}

    monkeypatch.setattr(clock, "now", lambda: t0 + ENTRY_ORDER_TIMEOUT_SECONDS + 1)
    asyncio.run(engine.check_pending_entry())

    assert fake.cancelled == ["oid-1"]
    assert state.position is not None
    assert state.position.size == pytest.approx(planned_size / 2, rel=1e-4)


def test_cancel_open_orders_calls_cancel_all(monkeypatch):
    state = _state_with_book()
    engine, fake = _live_engine(state, monkeypatch)

    engine.cancel_open_orders()

    assert fake.cancel_all_calls == ["BTC/USDT"]
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `.venv/bin/python -m pytest tests/test_execution.py -v -k live`
Expected: FAIL (la rama live de `enter` no existe; en modo live actual `enter` se comporta como paper).

- [ ] **Step 3: Implementar la rama live**

En `execution.py`, agregar `from dataclasses import dataclass, replace`, constante de módulo `_LIVE_FILL_POLL_SECONDS = 5.0`, y en `__init__`: `self._last_fill_poll: float = 0.0`.

`enter` — reemplazar el cierre de la función (después de construir `plan`):

```python
        if PAPER_MODE or self._exchange is None:
            self._pending_entry = PendingEntry(plan=plan, placed_at=clock.now())
            logger.info(
                "ENTRY PENDING %s limit @ %.2f | size=%.6f BTC | timeout=%ds",
                side.value.upper(), limit_price, plan.size, ENTRY_ORDER_TIMEOUT_SECONDS,
            )
            return True

        try:
            order_side = "buy" if side == Side.LONG else "sell"
            order = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._exchange.create_limit_order(
                    "BTC/USDT", order_side, plan.size, plan.price,
                    params={"timeInForce": "GTX"},  # Binance Futures post-only
                ),
            )
        except Exception:
            logger.exception("Live post-only entry rejected or failed — no trade")
            return False

        self._pending_entry = PendingEntry(plan=plan, placed_at=clock.now(), order_id=order["id"])
        logger.info(
            "ENTRY PENDING (live GTX) %s limit @ %.2f | size=%.6f BTC | id=%s",
            side.value.upper(), plan.price, plan.size, order["id"],
        )
        return True
```

`check_pending_entry` — insertar la rama live entre el chequeo de timeout y el fill paper. Estructura final completa del método:

```python
    async def check_pending_entry(self) -> None:
        """Called on every trade tick. Fills or expires the resting entry order."""
        pending = self._pending_entry
        if pending is None:
            return

        live = not (PAPER_MODE or self._exchange is None) and pending.order_id is not None

        if clock.now() - pending.placed_at >= ENTRY_ORDER_TIMEOUT_SECONDS:
            self._pending_entry = None
            if live:
                await self._cancel_live_entry_keeping_partial(pending)
            else:
                logger.info("Entry order timed out unfilled — cancelled")
            return

        if live:
            if clock.now() - self._last_fill_poll < _LIVE_FILL_POLL_SECONDS:
                return
            self._last_fill_poll = clock.now()
            try:
                order = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._exchange.fetch_order(pending.order_id, "BTC/USDT"),
                )
            except Exception:
                logger.exception("fetch_order failed for pending entry %s", pending.order_id)
                return
            if order.get("status") == "closed":
                self._fill_pending(pending.plan)
            return

        # Paper/backtest fill model: fill only when a trade prints strictly THROUGH
        # the limit (conservative queue assumption).
        p = self.state.last_price
        plan = pending.plan
        traded_through = (
            (plan.side == Side.LONG and p < plan.price)
            or (plan.side == Side.SHORT and p > plan.price)
        )
        if traded_through:
            self._fill_pending(plan)

    async def _cancel_live_entry_keeping_partial(self, pending: PendingEntry) -> None:
        """Cancel a timed-out live entry; if it was partially filled, keep the
        filled fraction as a (smaller, lower-risk) position."""
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._exchange.cancel_order(pending.order_id, "BTC/USDT"),
            )
            order = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._exchange.fetch_order(pending.order_id, "BTC/USDT"),
            )
        except Exception:
            logger.exception("Cancel/fetch of timed-out entry %s failed — MANUAL CHECK REQUIRED", pending.order_id)
            return
        filled = float(order.get("filled") or 0.0)
        if filled > 0:
            logger.info("Timed-out entry partially filled (%.6f BTC) — keeping the partial", filled)
            self._fill_pending(replace(pending.plan, size=filled))
        else:
            logger.info("Entry order timed out unfilled — cancelled on exchange")

    def cancel_open_orders(self) -> None:
        """Startup hygiene: a crash can leave an orphan resting entry on the exchange."""
        if self._exchange is None:
            return
        try:
            self._exchange.cancel_all_orders("BTC/USDT")
            logger.info("Startup: cancelled all open BTC/USDT orders")
        except Exception:
            logger.exception("Startup cancel_all_orders failed")
```

Nota: `_fill_pending` ya fue definida en Task 4 y sirve sin cambios (el `self._pending_entry = None` del timeout ya ocurrió; `_fill_pending` lo vuelve a poner en None, inofensivo).

En `main.py`, dentro de `run()`, justo después de `reconcile_with_exchange`:

```python
    if not PAPER_MODE:
        safety.reconcile_with_exchange(state, engine.exchange)
        engine.cancel_open_orders()
```

- [ ] **Step 4: Suite completa verde**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add execution.py main.py tests/test_execution.py
git commit -m "Route live entries as post-only GTX limits with fill polling and startup order cleanup"
```

---

### Task 6: Sanity run del backtest y actualización de docs

**Files:**
- Modify: `README.md` (secciones "How the strategy works" y "Architecture")
- Modify: `docs/mejoras-propuestas.md` (nota de estado)
- No code changes.

**Interfaces:**
- Consumes: todo lo anterior; datos cacheados en `backtest_cache/` (klines 1m del rango que incluye 2026-06-09→2026-06-11, con trades cacheados para esos dos días).

- [ ] **Step 1: Sanity run del backtest con datos cacheados**

Run:
```bash
.venv/bin/python backtest.py --start 2026-06-09 --end 2026-06-11 --out /tmp/pivot_sanity_trades.csv
```

Expected: la corrida termina sin excepción, imprime el resumen y escribe el CSV. **Criterio de éxito: no crashear y reportar.** Con señal en 15m sobre solo 2 días es probable que haya 0-2 trades (warmup: el régimen necesita ≥10 velas de 15m ≈ 2.5h; la squeeze, 3 velas más cerca de un swing) — pocas señales acá NO es un fallo. Si aparece cualquier traceback, arreglarlo antes de seguir (causa típica: alguna referencia residual a `candles_1m` o a un campo de estado eliminado en Task 2 — `grep -rn "trend_15m\|ema_5m" --include="*.py" . | grep -v .venv`).

- [ ] **Step 2: Verificar en el log de la corrida que el gate de spread no bloquea todo**

Run: `LOG_LEVEL=DEBUG .venv/bin/python backtest.py --start 2026-06-09 --end 2026-06-10 2>&1 | grep -c "spread"`
Expected: 0 o un número bajo de rechazos por spread. Si TODA señal muere por spread, revisar que Task 1 Step 3 aplicó `BACKTEST_SYNTHETIC_SPREAD_PCT = 0.00001` y `SPREAD_FILTER_ATR_PCT = 0.01`.

- [ ] **Step 3: Actualizar README.md**

En "How the strategy works", punto 3, agregar al final: `Signals are evaluated on 15m candle closes (the signal timeframe).` En el punto 5, reemplazar la descripción de ejecución por:

```markdown
5. **Execution** (`execution.py`) — entries rest as post-only limit orders at the touch
   (maker fee); in paper/backtest they fill only when price trades through the limit, and
   expire unfilled after a timeout. Exits (stop, target, time, momentum) cross the spread
   as market orders (taker fee). Live mode routes the entry as a Binance Futures GTX
   (post-only) order and polls for the fill.
```

En el disclaimer o al final de la intro, agregar una línea: `The signal clock is the 15m candle; this bot is an intraday swing system, not a sub-minute scalper (see docs/revisiones/ for the cost analysis that motivated this).`

- [ ] **Step 4: Nota de estado en `docs/mejoras-propuestas.md`**

Agregar al final del documento:

```markdown
---

## 6. Estado (2026-07-02)

Implementado el pivot de estructura de costos (P0-2 y P0-4 de la sección 4): señal
movida de 1m a 15m y entradas convertidas a maker post-only con timeout
(plan: `docs/superpowers/plans/2026-07-02-pivot-senal-15m-entradas-maker.md`).
Fee drag por round-trip esperado: de ~1.30R a ~0.17R (entrada maker + salidas taker,
ATR% p50 de 15m medido en 0.280%). Siguen pendientes: cost gate explícito (P0-3),
ablation de gates (P0-8), ampliación del histórico (P0-6) y persistencia de
resultados (P0-7).
```

- [ ] **Step 5: Suite completa + commit final**

```bash
.venv/bin/python -m pytest -q
git add README.md docs/mejoras-propuestas.md
git commit -m "Document the 15m maker pivot and record its status"
```

---

## Notas de diseño para el ejecutor (leer antes de la Task 1)

1. **No tocar los feeds.** `DataFeed` y `BacktestFeed` ya construyen y emiten velas de 1m/5m/15m idénticamente; el pivot solo cambia QUÉ buffer consume la señal y CUÁNDO se evalúa. Los buffers `candles_1m`/`candles_5m` siguen llenándose aunque casi nadie los lea (`live_1m` sigue alimentando `update_volume_velocity`).
2. **Momentum queda en su timeframe natural.** `volume_velocity` es BTC/segundo derivado de la vela viva de 1m — es una medida por segundo, independiente del reloj de señal. Solo escala su ventana de espera (`MOMENTUM_ABORT_MINUTES = 45`).
3. **Por qué el fill exige atravesar el precio (no tocarlo):** estar al mejor bid no garantiza prioridad de cola; asumir fill al toque sobreestima el ratio de fills y sesga el backtest a favor. `p < limit` (LONG) es el proxy conservador estándar.
4. **Por qué el timeout es 300s:** la tesis de entrada se renueva en cada cierre de 15m; una limit viva más de ~1/3 de barra ya no responde a la señal que la originó. Además garantiza que nunca hay dos pendientes (la señal siguiente llega a los 900s).
5. **El riesgo de no-fill es el costo del maker:** algunos breakouts se irán sin fill. Ese trade-off es exactamente lo que el ablation de P0-8 debe medir después (fills perdidos vs. 0.06% ahorrado por round-trip). No "mejorar" el modelo de fill sin datos.
6. **Kill switch y pendientes:** `can_open_new_position` se evalúa antes de colocar la orden; una pendiente colocada legítimamente puede llenarse hasta 300s después de que el kill switch se active. Ventana acotada y aceptada — no agregar lógica extra.
7. **Qué NO hace este plan (a propósito, ver docs de revisión):** no toca la lógica de dirección de la squeeze (N1 de la tercera opinión — decisión previa al rediseño), ni el cost gate (P0-3), ni TP1 como maker, ni el breakeven neto (N2), ni la expiración de régimen (N3). Un cambio estructural por vez, medible.
