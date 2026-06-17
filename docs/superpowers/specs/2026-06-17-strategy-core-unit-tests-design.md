# Cobertura de tests para el núcleo de la estrategia — diseño

Fecha: 2026-06-17

## 1. Resumen y objetivo

El proyecto ya tiene pytest configurado y 36 tests pasando, pero toda esa
cobertura es de la sesión de "seguridad operativa" anterior (`safety.py`,
`risk.py`, `execution.py`, y solo el filtro de spread de `signals.py`). El
núcleo real de la estrategia —detección de régimen, indicadores adaptativos,
order flow, momentum, y el resto de las condiciones de entrada— tiene cero
tests. Este diseño lleva esa cobertura a cero faltante en:
`indicators.py`, `momentum.py`, `order_flow.py`, `regime.py`, `context.py`,
y el resto de `signals.py`.

De paso, escribir tests reales para `context.py` expuso dos bugs que se
arreglan como parte de este trabajo porque sin ellos no se puede escribir
un test que ejercite comportamiento correcto (ver sección 2).

### No-goals (fuera de alcance de este diseño)

- Backtesting contra datos históricos de Binance — ciclo de diseño aparte,
  que arranca después de que este se complete.
- Deduplicar `update_mtf_trend` (regime.py) y `update_mtf_trends`
  (context.py) — sesión de calidad de código aparte. Se testean como las
  dos funciones independientes que son hoy, sin tocar su duplicación.
- Cobertura property-based (ej. con `hypothesis`) para las funciones
  matemáticas puras — no se justifica para la complejidad de este código,
  y agregaría una dependencia/paradigma nuevo sin necesidad.
- Testear `MacroFilter.run()` (el loop infinito con `asyncio.sleep`) — solo
  se testea `_update()`, que es la unidad con lógica real.

## 2. Bugs que este diseño corrige

### 2.1 `context.py:76` — branch muerto

```python
btc_candles = list(state.candles_15m) if hasattr(self, '_use_state_attr') else list(self.state.candles_15m)
```

`hasattr(self, '_use_state_attr')` siempre es `False` (ese atributo nunca se
setea en ningún lado), así que la rama `if` —que además sombrea el módulo
`state` importado a nivel de archivo, no una instancia— nunca se ejecuta.
Se reemplaza por:

```python
btc_candles = list(self.state.candles_15m)
```

Comportamiento idéntico, sin la rama confusa.

### 2.2 `MacroFilter._update` — `AttributeError` con la versión instalada de yfinance

Verificado directamente en este entorno (`yfinance==1.4.1`,
`pandas==3.0.3`): `yf.download("SPY", ...)` devuelve un DataFrame con
columnas en MultiIndex (`('Close', 'SPY')`, etc.) incluso para un solo
ticker. Por eso `data["Close"]` es un DataFrame, no una Series, y
`.dropna().tolist()` rompe con `AttributeError: 'DataFrame' object has no
attribute 'tolist'` — exactamente el error que apareció en el smoke test
de la sesión anterior.

Fix verificado: agregar `multi_level_index=False` a la llamada:

```python
spy_data = await loop.run_in_executor(
    None,
    lambda: yf.download(
        "SPY", period="1d", interval="15m", progress=False,
        auto_adjust=True, multi_level_index=False,
    ),
)
```

Con ese parámetro, `data.columns` es un `Index` plano y `data["Close"]` es
una `Series`, que es lo que el resto de la función ya espera.

## 3. Tests por módulo

Todos los tests usan estado sintético construido a mano (instancias reales
de `MarketState`, `Candle`, `BookSnapshot`, deques poblados directamente) —
nunca mocks de la lógica bajo test. Mocks solo se usan para aislar I/O
externo real (la llamada de red de `yfinance`).

### 3.1 `tests/test_indicators.py`

- `compute_atr`: menos de 2 velas → `0.0`; secuencia conocida de
  high/low/close → valor de Wilder calculado a mano.
- `compute_ema`: lista vacía → `0.0`; secuencia conocida → EMA calculado a
  mano.
- `ema_period_for_regime`: `BREAKOUT` → `EMA_PERIOD_BREAKOUT`,
  `TIGHT_CHANNEL` → `EMA_PERIOD_CHANNEL`, `TRADING_RANGE`/`UNKNOWN` →
  `EMA_PERIOD_RANGE`.
- `detect_swing_points`: menos del mínimo de velas (`2*lookback+1`) →
  `([], [])`; secuencia con un pico y un valle conocidos en posiciones
  conocidas → los detecta exactamente ahí y no en otro lado.
- `update_indicators`: con `state.candles_1m`/`5m`/`15m` poblados, confirma
  que `state.atr`, `state.ema`, `state.ema_5m`, `state.ema_15m` quedan
  seteados, y que el período usado para `state.ema` cambia según
  `state.regime` (caso `BREAKOUT` usa un período distinto que `UNKNOWN`).

### 3.2 `tests/test_momentum.py`

- `update_volume_velocity`: `state.live_1m is None` → no muta
  `state.volume_velocity`; con una vela viva y un `timestamp` conocido
  relativo a "ahora" → `volume_velocity ≈ volume / elapsed_seconds`.
- `should_abort_for_momentum`: sin posición → `False`; tiempo en posición
  menor a `MOMENTUM_ABORT_MINUTES` → `False`; `prior_volume_velocity <= 0`
  → `False`; `ratio < _VELOCITY_COLLAPSE_RATIO` (con tiempo y
  `prior_volume_velocity` válidos) → `True`; `ratio >=
  _VELOCITY_COLLAPSE_RATIO` → `False`.

### 3.3 `tests/test_order_flow.py`

- `snapshot_cvd_on_close`: `state.cvd` se mueve a `state.cvd_per_candle` y
  `state.cvd` vuelve a `0.0`.
- `detect_cvd_divergence`: menos de 3 velas/cvds → `None`; secuencia con
  higher-high de precio + CVD cayendo → `"bearish_divergence"`; secuencia
  con lower-low de precio + CVD subiendo → `"bullish_divergence"`; sin
  ninguno de los dos patrones → `None`.
- `_averaged_bid_ask_volume`: lista vacía → `(0.0, 0.0)`; snapshots
  conocidos → promedio de bid/ask calculado a mano.
- `get_book_imbalance`: menos de 2 snapshots → `(1.0, "neutral")`;
  desequilibrio bid fuerte (ratio ≥ `OB_IMBALANCE_RATIO`) → `(ratio,
  "bid")`; desequilibrio ask fuerte → `(ratio, "ask")`; ratio intermedio →
  `(ratio, "neutral")`.

### 3.4 `tests/test_regime.py`

Clasificadores puros, cada uno con un caso por encima y por debajo de su
umbral de `config.py`:
- `_is_breakout_candle` (vs `BREAKOUT_BODY_ATR_MULT`)
- `_is_tight_candle` (vs `CHANNEL_RANGE_ATR_MULT`)
- `_has_liquidity_sweeps_at_both_extremes` (toca ambos extremos del rango
  en las últimas 5 velas vs. no)
- `_ema_is_sloping` (vs 0.15×ATR de drift)

`_infer_candidate`: un caso por cada uno de los 4 resultados posibles
(`BREAKOUT`, `TRADING_RANGE`, `TIGHT_CHANNEL`, `UNKNOWN`), combinando los
clasificadores de arriba.

`update_regime` (la pieza más delicada — máquina de estados con
histéresis): usando secuencias de velas sintéticas armadas a mano,
construidas candle-por-candle para forzar cada candidato:
- Un único candle confirmando un candidato nuevo NO transiciona el
  régimen (`regime_confirm_count` queda en 1, `regime` sin cambios).
- `REGIME_CONFIRM_CANDLES` (3) candles consecutivos confirmando el mismo
  candidato SÍ transicionan `state.regime` y resetean
  `pending_regime`/`regime_confirm_count`.
- Una racha interrumpida por un candidato distinto en el medio resetea el
  contador a 1 con el nuevo candidato como `pending_regime`.
- Un candidato `UNKNOWN` nunca modifica `regime`, `pending_regime`, ni
  `regime_confirm_count` (se preserva el estado a través de barras
  ambiguas).

`update_mtf_trend`: zona muerta alrededor de la EMA (precio dentro del
±0.05%/±0.03% no cambia `trend_15m`/`trend_5m`, fuera de esa banda sí, en
la dirección correcta).

### 3.5 `tests/test_signals.py` (extiende el archivo existente de Task 6)

`update_squeeze`: se activa (`state.in_squeeze=True`) recién al llegar a
`SQUEEZE_MIN_BARS` barras consecutivas comprimidas y cerca de un nivel
clave; `squeeze_direction` se asigna según el lado del nivel en el que
está el precio; se resetea (`in_squeeze=False`, `squeeze_bar_count=0`) en
cuanto se rompe la compresión o la proximidad al nivel.

`check_entry_signal`: un test por cada gate restante (el filtro de spread
ya quedó cubierto en Task 6), cada uno con un estado base válido que pasa
todos los demás gates para aislar el que se está probando:
- `state.regime == Regime.UNKNOWN` → `None`
- `state.in_squeeze == False` → `None`
- `state.position is not None` → `None`
- `state.squeeze_direction is None` → `None`
- `state.trend_15m` opuesto a la dirección del squeeze → `None`
- `state.macro_blocks_longs`/`macro_blocks_shorts` con la dirección
  correspondiente → `None`
- En régimen `BREAKOUT`, squeeze apuntando en contra de la vela de
  breakout → `None`
- Divergencia de CVD en contra de la dirección planeada → `None`
- Desequilibrio del libro en contra de la dirección planeada → `None`
- Estado que pasa todos los gates → devuelve `state.squeeze_direction`

### 3.6 `tests/test_context.py`

- `update_mtf_trends`: mismos casos que `update_mtf_trend` de
  `regime.py`, verificados de forma independiente sobre esta función (sin
  asumir que comparten implementación, ya que la deduplicación queda
  fuera de alcance).
- `_pearson`: dos series perfectamente correlacionadas → `1.0`; dos series
  perfectamente anticorrelacionadas → `-1.0`; series sin relación → un
  valor cercano a `0`; `n < 2` → `0.0`.
- `MacroFilter._update`, con `yfinance.download` reemplazado por un fake
  que devuelve un DataFrame sintético de columnas planas (ya con el fix de
  la sección 2.2 aplicado, así que el shape coincide con lo que el código
  espera):
  - Alta correlación (`|corr| >= CORRELATION_BLOCK_THRESHOLD`) y SPY
    bajando → `state.macro_blocks_longs = True`,
    `macro_blocks_shorts = False`.
  - Alta correlación y SPY subiendo → `macro_blocks_shorts = True`,
    `macro_blocks_longs = False`.
  - Correlación baja → ninguna de las dos flags se activa.
  - Menos de 6 velas BTC de 15m o menos de 6 cierres de SPY → la función
    retorna temprano sin tocar ninguna flag.
  - `yfinance` no instalado, simulado con
    `monkeypatch.setitem(sys.modules, "yfinance", None)` → no se levanta
    ninguna excepción, `self._yfinance_available` queda en `False`, y
    llamadas posteriores a `_update()` no vuelven a intentar el import.

## 4. Infraestructura

No se necesita infraestructura nueva: el venv del proyecto y pytest ya
están configurados (sesión anterior). Los nuevos archivos de test siguen
exactamente el patrón ya establecido (`tests/test_<module>.py`,
sin `__init__.py`, resueltos vía el `conftest.py` vacío en la raíz).

## 5. Manejo de errores

No aplica más allá de los dos fixes de la sección 2 — este diseño no
agrega lógica de runtime nueva, solo cobertura de test para la que ya
existe (más esos dos arreglos puntuales).
