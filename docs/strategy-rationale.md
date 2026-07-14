# Razonamiento de la estrategia — auditoría de reglas y su sustento

Fecha: 2026-06-19

Este documento existe para que otra IA (o un humano) pueda auditar de forma
independiente el razonamiento detrás de cada regla de entrada/salida del bot,
y juzgar si tiene sustento real o es una heurística discrecional sin
validación empírica dentro de este repo. Cada sección cita archivo:línea y el
valor exacto de los parámetros en `config.py`.

**Conclusión adelantada (ver sección 7 para el detalle):** el bot es la
codificación de un método de price-action discrecional conocido (estilo Bob
Volman, "compresión antes de la ruptura"), reforzado con filtros de
confluencia estándar de TA / order-flow. **No** hay, dentro de este repo, un
backtest que demuestre edge estadístico neto de fees. El propio diseño del
backtest harness lo declara explícitamente como herramienta de "señal
direccional", no de validación rigurosa de rentabilidad.

---

## 1. Pipeline de decisión (orden real de evaluación)

`check_entry_signal` (`signals.py:66-145`) es el único punto donde se decide
LONG/SHORT/None. Evalúa, en este orden, y **todas** las condiciones deben
pasar (AND lógico, cortocircuito en la primera que falla):

1. `state.regime != UNKNOWN` (`signals.py:79-80`)
2. `state.in_squeeze == True` (`signals.py:81-82`)
3. No hay posición abierta ya (`signals.py:83-84`)
4. `state.squeeze_direction is not None` (`signals.py:86-88`)
5. Spread aceptable (`signals.py:91-96`)
6. No-contra-tendencia 15m (`signals.py:99-101`)
7. No bloqueo macro (`signals.py:104-109`)
8. Si régimen es BREAKOUT, la última vela debe confirmar la dirección
   (`signals.py:112-120`)
9. Sin divergencia de CVD en contra (`signals.py:123-129`)
10. Sin imbalance del book en contra (`signals.py:132-138`)

Si las 10 pasan, devuelve `direction` y lo loguea (`signals.py:140-145`).

---

## 2. La señal primaria: "The Squeeze" (`signals.py:26-61`)

### Mecánica exacta

```
is_compressed = latest.range <= SQUEEZE_COMPRESSION_ATR * state.atr   # 0.4× ATR
near_level    = distance al swing high/low más cercano <= SQUEEZE_LEVEL_ATR_PROXIMITY * state.atr  # 0.5× ATR
```

Si ambas son verdaderas durante `SQUEEZE_MIN_BARS` (3) velas consecutivas →
`in_squeeze = True`, y la dirección esperada de ruptura es **hacia el nivel
contra el que se comprime** (no alejándose de él):

```
squeeze_direction = LONG  si last_price > key_level   (precio arriba, comprimido contra soporte → ruptura hacia abajo... )
```

Ojo con la lectura: el comentario en `signals.py:53` dice *"Expected breakout
direction is INTO the level"* — es decir, si el precio está **por encima**
del nivel (comprimiéndose contra una resistencia desde abajo... o contra un
soporte desde arriba, según cuál nivel sea el más cercano) el bot asume
ruptura **LONG** si `last_price > key_level`. Esto asume que la compresión
contra un nivel señala absorción y continuación en la dirección del lado
donde está el precio respecto al nivel, **no** necesariamente ruptura del
nivel en sí. Quien valide el razonamiento debería confirmar si esta lectura
direccional coincide con la definición real de "Volman squeeze" (compresión
**justo debajo** de resistencia → ruptura **hacia arriba** rompiendo la
resistencia, o compresión **justo encima** de soporte → ruptura **hacia
abajo** rompiéndolo) — en ese caso la lógica de `signals.py:54-56` parecería
**invertida** respecto a la ruptura de nivel clásica, y en cambio modela
"continuación en la dirección del lado donde está parado el precio". Esto es
el punto de mayor riesgo de razonamiento del archivo y vale una segunda
opinión específica.

### Sustento

- **Origen:** patrón de price-action discrecional popularizado por Bob Volman
  (autor de *Forex Price Action Scalping* y *Understanding Price Action*),
  conocido informalmente como "the squeeze": compresión de rango contra un
  nivel clave como señal de absorción antes de una expansión.
- **Tipo de evidencia:** es una heurística de trading manual, documentada en
  literatura de scalping retail/prop, **no** un hallazgo de un estudio
  cuantitativo peer-reviewed. Tiene cierta consistencia con fenómenos
  estadísticamente documentados de mercados financieros (clustering de
  volatilidad: períodos de baja volatilidad tienden a preceder expansiones —
  esto sí está bien establecido en literatura de series de tiempo financieras,
  p. ej. modelos GARCH), pero el patrón específico de "comprimirse contra un
  nivel y romper en una dirección predecible" no está validado
  estadísticamente en este repo.
- **No validado empíricamente acá:** no existe ningún backtest guardado en
  este repo que mida la tasa de éxito de la señal de squeeze aislada (sin los
  demás filtros) contra datos históricos.

---

## 3. Filtro de régimen (`regime.py`)

Clasifica el mercado en `BREAKOUT` / `TIGHT_CHANNEL` / `TRADING_RANGE` /
`UNKNOWN`, con histéresis (`REGIME_CONFIRM_CANDLES = 3` velas consecutivas
para confirmar una transición, `regime.py:89-117`) para evitar flip-flopping.

| Régimen | Condición | Parámetro |
|---|---|---|
| `BREAKOUT` | última vela con `body >= 1.5× ATR` | `BREAKOUT_BODY_ATR_MULT = 1.5` |
| `TIGHT_CHANNEL` / `TRADING_RANGE` | ≥3 de las últimas 5 velas con `range <= 0.8× ATR` | `CHANNEL_RANGE_ATR_MULT = 0.8` |
| `TRADING_RANGE` (vs `TIGHT_CHANNEL`) | además: barrida de liquidez en ambos extremos de los últimos 20 bars (`RANGE_SWEEP_LOOKBACK`) y EMA **no** inclinada (`_ema_is_sloping`, umbral 0.15× ATR vs. 10 velas atrás) | `regime.py:28-48, 51-57` |

**Efecto downstream:** el régimen no solo es un filtro de gating — también
cambia el período de la EMA usada (`indicators.py:48-53`:
`EMA_PERIOD_BREAKOUT=8`, `EMA_PERIOD_CHANNEL=13`, `EMA_PERIOD_RANGE=20`), y en
`BREAKOUT` exige que la última vela confirme la dirección de la squeeze
(`signals.py:112-120`).

**Sustento:** heurística estándar de TA — usar ATR (volatilidad reciente)
como vara de medir para clasificar "vela grande" vs "vela chica" es una
práctica común y razonable. La parte de "barrida de ambos extremos" para
confirmar rango (en vez de usarlo como fallback por defecto, según el
comentario en `regime.py:32-33`) es una decisión de diseño sensata para
evitar falsos positivos, pero sigue siendo una heurística sin validación
estadística propia en este repo.

---

## 4. Filtro de tendencia multi-timeframe (`regime.py:122-139`)

```
trend_15m = LONG  si price > ema_15m * 1.0005
trend_15m = SHORT si price < ema_15m * 0.9995
trend_5m  = LONG  si price > ema_5m  * 1.0003
trend_5m  = SHORT si price < ema_5m  * 0.9997
```
(banda muerta del 0.05%/0.03% para evitar flip-flop en el cruce exacto de la
EMA). `TREND_EMA_5M = 12`, `TREND_EMA_15M = 20` (`config.py:53-54`).

Aplicado como **bloqueo duro**: si `trend_15m` está definido y es distinto a
la dirección de la squeeze, se rechaza la señal sin excepción
(`signals.py:99-101`). `trend_5m` se calcula pero **no se usa actualmente**
en `check_entry_signal` — queda en el estado pero no filtra nada hoy
(`grep` confirma que `state.trend_5m` no aparece en `signals.py`).

**Sustento:** "no operar contra la tendencia del timeframe mayor" es uno de
los principios más repetidos en TA clásico y trading discrecional. No es una
ley estadística demostrada acá, pero es de los componentes con más consenso
informal en la práctica de trading.

**Nota para quien audite:** `trend_5m` calculado pero sin uso es código
muerto funcionalmente — vale confirmar si es intencional (reservado para un
filtro futuro) o un descarte que se quedó a medias.

---

## 5. Filtros de order flow (`order_flow.py`)

### 5.1 Divergencia de CVD (Cumulative Volume Delta)

```
bearish_divergence: price_highs[-1] > price_highs[-2]  AND  cvd[-1] < cvd[-2]
bullish_divergence: price_lows[-1]  < price_lows[-2]   AND  cvd[-1] > cvd[-2]
```
Comparación vela a vela (no de extremos en una ventana), sobre las últimas
`CVD_DIVERGENCE_LOOKBACK = 5` velas (`order_flow.py:20-46`). Si hay
divergencia bajista, se rechaza un LONG; si hay divergencia alcista, se
rechaza un SHORT (`signals.py:123-129`).

**Sustento:** concepto de order-flow/microestructura razonablemente aceptado
entre traders que operan flujo de órdenes — la idea es que un nuevo máximo de
precio sin participación de volumen neto comprador sugiere absorción/venta
oculta (y viceversa). Es una heurística más fundamentada en mecánica de
mercado real (quién está absorbiendo el flujo) que en patrones puramente
visuales, pero **sigue siendo discrecional**: no hay backtest aislado que
mida su tasa de acierto como filtro independiente.

**Limitación de datos:** el CVD se reconstruye con el signo real del agresor
del trade (`backtest_feed`, según `docs/superpowers/specs/2026-06-18-backtesting-design.md`
sección 4.3) — en backtest es exacto, no aproximado. En vivo viene de
`aggTrade` de Binance vía WebSocket.

### 5.2 Imbalance del order book

```
ratio = avg_bid_vol / avg_ask_vol   (promedio sobre OB_SNAPSHOTS=5 snapshots, depth=10 niveles)
"bid" si ratio >= OB_IMBALANCE_RATIO (2.0)
"ask" si ratio <= 1/2.0
```
(`order_flow.py:69-92`). Un imbalance "ask" fuerte rechaza LONG; un imbalance
"bid" fuerte rechaza SHORT (`signals.py:132-138`).

**Sustento:** el order book es una de las fuentes de información más
directas sobre presión de compra/venta inminente, pero también la más fácil
de manipular (spoofing: colocar y cancelar órdenes grandes sin intención de
ejecutarlas). El promedio sobre 5 snapshots (`_averaged_bid_ask_volume`,
`order_flow.py:51-66`) es un intento razonable de mitigar spoofing efímero,
pero no elimina spoofing sostenido durante >5 snapshots. **No** se modela en
backtest (queda en `(1.0, "neutral")` todo el tiempo — ver
`docs/superpowers/specs/2026-06-18-backtesting-design.md` sección 5), así que
este filtro nunca ha sido evaluado contra datos históricos en este repo.

---

## 6. Filtro macro: correlación BTC-SPY (`context.py:31-129`)

- Descarga velas de 15m de SPY vía `yfinance` (gratis, delay ~15 min) cada
  `MACRO_UPDATE_SECONDS = 300`.
- Calcula correlación de Pearson rodante (`_pearson`, `context.py:118-128`)
  entre retornos de BTC (15m) y SPY (15m), sobre una ventana de hasta 20
  barras.
- Si `|corr| >= CORRELATION_BLOCK_THRESHOLD (0.8)` y SPY está en tendencia
  bajista (comparando el cierre actual contra el de 4 barras atrás) →
  bloquea LONGS. Si SPY sube → bloquea SHORTS.

**Sustento:** la correlación entre BTC y activos de riesgo tradicionales
(equities, especialmente en regímenes "risk-on/risk-off") es un fenómeno
documentado empíricamente en ciertos períodos (sobre todo 2020-2023), pero
**no es estable** — hay tramos donde la correlación BTC-SPY se diluye o se
invierte. El propio código reconoce que esta fuente de datos **no es
apropiada para uso HFT real** (comentario en `context.py:37`: *"For live
HFT-quality correlation, replace yfinance with a real-time data feed"*).
Es, en el mejor caso, un filtro de sesgo direccional grueso, no una señal de
microestructura.

**No se backtestea:** Yahoo Finance solo da velas de 15m de los últimos ~60
días, así que no se puede reconstruir la correlación para un rango histórico
arbitrario. El backtest harness lo desactiva por completo (`macro_blocks_longs`/
`macro_blocks_shorts` quedan en `False` toda la corrida — ver
`docs/superpowers/specs/2026-06-18-backtesting-design.md` sección 5). Esto
significa que **ningún resultado de backtest hasta ahora refleja el
comportamiento real de este filtro.**

---

## 7. Filtro de spread (`signals.py:91-96`)

```
rechazar si state.spread > SPREAD_FILTER_ATR_PCT (0.05) * state.atr
```

**Sustento:** control de calidad de ejecución, no una señal de TA. Evitar
entrar cuando el book está anormalmente ancho (baja liquidez, alta
volatilidad puntual, posible mal funcionamiento del feed) es una práctica
operacional sólida y difícilmente discutible — es el filtro con menos
controversia de todo el pipeline.

---

## 8. Gestión de riesgo (`risk.py`)

| Mecanismo | Parámetro | Ubicación |
|---|---|---|
| Sizing fraccional fijo | 0.5% del balance diario inicial arriesgado por trade | `ACCOUNT_RISK_PCT=0.005`, `risk.py:27-33` |
| Stop loss inicial | 1.5× ATR desde entrada | `INITIAL_SL_ATR=1.5`, `risk.py:38-44` |
| TP1 | 2R, cierra 50% de la posición | `TP1_RR=2.0`, `TP1_CLOSE_PCT=0.5`, `risk.py:194-210` |
| Breakeven | mueve SL a entrada tras 0.8× ATR de profit | `BREAKEVEN_ATR_TRIGGER=0.8`, `risk.py:120-142` |
| Breathing stop | expande (nunca contrae) el SL si el ATR en vivo crece ≥20% vs. el ATR de entrada | `ATR_BREATHING_THRESHOLD=1.2`, `risk.py:145-165` |
| Trailing estructural | sigue el swing low/high más reciente a favor del trade, sin cruzar el SL original | `risk.py:168-191` |
| Salida por tiempo | cierra a los 15 min si no se resolvió | `TIME_EXIT_MINUTES=15`, `risk.py:269-270` |
| Abort por momentum | cierra si, tras 3 min, la velocidad de volumen cae a <30% de la de entrada | `MOMENTUM_ABORT_MINUTES=3`, `_VELOCITY_COLLAPSE_RATIO=0.30`, `momentum.py:25-51` |
| Fees | 0.05% por lado (taker, Binance Futures USDT-M, sin descuento BNB) aplicados en cada apertura/cierre/parcial | `TAKER_FEE_RATE=0.0005`, `risk.py:64,98,225` |

**Sustento:** este es el bloque con mejor fundamento estadístico de todo el
proyecto. Usar el ATR como proxy de volatilidad reciente para definir
distancia de stop y sizing es una práctica ampliamente validada en gestión de
riesgo cuantitativa — independiza el riesgo monetario por trade de cuán
volátil esté el activo en ese momento, en vez de usar un stop fijo en
dólares o en porcentaje de precio. El riesgo fijo del 0.5% por trade es
conservador y estándar. Esto es válido **con independencia de si la señal de
entrada tiene edge o no** — buena gestión de riesgo no genera edge, solo
controla la varianza y evita la ruina.

---

## 9. Kill switch / seguridad operacional (`safety.py`)

- **Kill switch diario:** se activa si `pnl_today <= -2%` del balance inicial
  del día (`KILL_SWITCH_DAILY_LOSS_PCT=0.02`) o tras 3 pérdidas consecutivas
  (`KILL_SWITCH_CONSECUTIVE_LOSSES=3`), y bloquea nuevas entradas hasta el
  reset del día UTC siguiente (`safety.py:61-83`).
- **Reconciliación al iniciar:** compara la posición persistida en disco
  contra la que reporta realmente el exchange; si no coinciden, el proceso
  termina (`sys.exit(1)`) en vez de asumir un estado (`safety.py:163-193`).
- **Balance diario real en modo live:** se resuelve contra el balance real
  del exchange al inicio de cada día UTC, no contra un valor hardcodeado
  (`safety.py:38-53`, `fetch_real_balance`).

**Sustento:** son controles operacionales de seguridad, no reglas de
trading. Su objetivo es limitar el daño cuando la estrategia (cualquiera que
sea su edge real) atraviesa una mala racha o el proceso se reinicia en un
estado inconsistente. Están bien fundamentados como práctica de gestión de
riesgo operacional — no afectan si la estrategia "funciona", solo limitan
cuánto se puede perder mientras se descubre si funciona o no.

---

## 10. ¿Qué tan validado está esto realmente?

- El `README.md` describe el bot explícitamente como **"discretionary-style
  price-action scalping strategy"** — no como una estrategia derivada de
  optimización cuantitativa.
- El diseño del backtest harness (`docs/superpowers/specs/2026-06-18-backtesting-design.md`,
  sección 1) declara su objetivo como: *"una herramienta rápida de validación
  de lógica — detectar regresiones (...) y tener una señal direccional de si
  la estrategia tiene edge (...). No es una herramienta de evaluación
  rigurosa de rentabilidad para poner capital real"*.
- Limitaciones explícitas del backtest (sección 5 del mismo doc): no modela
  order book real (el filtro de imbalance queda inerte), no modela el filtro
  macro (queda inerte), no hace grid search ni walk-forward.
- No hay ningún `backtest_trades.csv` ni reporte de resultados guardado en
  el repo — es decir, **no existe evidencia numérica dentro de este proyecto
  de que la estrategia tenga edge neto de fees** sobre datos históricos
  reales. Hay datos cacheados en `backtest_cache/` (klines/trades de
  noviembre 2025) pero ninguna corrida con resultados persistida.

### Puntos que más justifican una segunda opinión de otra IA

1. **Dirección de la squeeze** (`signals.py:53-56`) — confirmar si la lectura
   "precio arriba del nivel → LONG" coincide con la definición estándar de
   compresión-contra-nivel de Volman, o si está invertida respecto a una
   ruptura clásica del nivel (ver sección 2).
2. **`trend_5m` calculado pero no usado como filtro** (`regime.py:135-139`
   vs. ausencia en `signals.py`) — ¿intencional o descuido?
3. **Filtros que quedan completamente inertes en backtest** (order book
   imbalance, macro) — cualquier métrica de "edge" que salga de una corrida
   de backtest hoy **no** refleja el comportamiento real en vivo, porque dos
   de los 10 gates del pipeline nunca bloquean nada en esa simulación.
4. **Ausencia total de resultados numéricos guardados** — antes de confiar en
   esta estrategia con capital real, falta correr el backtest sobre un rango
   amplio y persistir/auditar los resultados (win rate, profit factor,
   drawdown, rachas) — algo que el propio diseño deja como tarea pendiente,
   no como algo ya hecho.
