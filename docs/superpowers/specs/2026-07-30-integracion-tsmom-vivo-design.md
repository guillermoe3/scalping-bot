# Integración operativa de TSMOM k=14 al bot en vivo — diseño

Fecha: 2026-07-30

## 1. Resumen y objetivo

El bot en vivo, tal como está hoy (`main.py`, `signals.py`, `regime.py`,
`order_flow.py`, `indicators.py`, `execution.py`), opera exclusivamente la
estrategia de scalping sobre velas de 15 minutos (squeeze + gates). Esa
señal quedó descartada como no rentable en el ciclo de limpieza y estudios
de tasa base (`docs/mejoras-propuestas.md`, sección "Estado"). En paralelo,
la investigación de base rate (ciclos momentum multi-día e histéresis,
`backtest_runs/estudios/veredicto-momentum-2026-07.md` y
`veredicto-histeresis-2026-07.md`) validó una señal distinta que sí
sobrevivió calibración y verificación selladas de forma independiente:

- **Señal:** TSMOM, lookback 14 días, variante long_flat, BTC.
- **Overlay:** vol targeting con σ_target=0.40 anualizado (M3), que reduce
  drawdown y peor mes calendario a cambio de algo de retorno medio, en
  ambas ventanas.
- **Instrumento:** spot para la pata long (M4: el funding de perp le come
  0.15-0.26 de Sharpe en las dos ventanas; long_flat tampoco necesita ir
  corto nunca).
- **Ritmo:** ~40 cambios de posición por año, holding de días/semanas — muy
  distinto al scalping intradía.

**Objetivo de este ciclo:** llevar esa señal, ya validada, del backtest de
investigación al bot operando en modo **paper trading** contra datos reales
en vivo — no todavía a capital real. Es la brecha que
`docs/mejoras-propuestas.md` sección P3 dejaba pendiente ("paper trading
con el código de producción real").

## 2. Alcance y no-goals

**Alcance:**
- Reemplazar lo que hace `main.py: wire_strategy` hoy: en vez de cablear el
  squeeze de 15m, cablea la estrategia diaria TSMOM k=14 + vol targeting.
- Ejecución real contra Binance **spot** (vía ccxt, `defaultType: "spot"`),
  en paper mode primero.
- Circuit breaker de drawdown (reemplaza el kill switch diario del
  scalping, que no tiene sentido a este ritmo).
- Notificaciones por Telegram para los eventos de esta estrategia
  (rebalanceo, circuit breaker).
- Símbolo: **BTCUSDT únicamente** — es el único que adoptó/vetó en el
  criterio de M1 (ETH fue solo robustez, nunca decisorio).

**No-goals (decisiones explícitas de este ciclo):**
- **No se borra ni se toca el código de scalping.** Queda en el repo, sin
  importarse desde el nuevo `wire_strategy`. Puede revivirse más adelante
  si hay una razón nueva.
- **No se pasa a capital real en este ciclo.** Eso es una decisión aparte,
  posterior, después de validar el comportamiento en paper trading.
- **No se replica el rebalanceo diario exacto del estudio.** Se aproxima
  con una banda de rebalanceo (sección 4) para no pagar fees de ajustes
  diarios que el backtest no modeló — queda documentada como aproximación
  operativa, no como parte de la señal validada (mismo espíritu que M4
  documentó "precio spot + funding de futuros, base ignorada").
- **No hay apalancamiento.** Spot, long_flat: la posición es 0% a 100% de
  la exposición objetivo sobre el equity disponible, nunca corto.
- **No se modela leverage/margen/funding** — no aplica en spot.

## 3. Arquitectura (componentes nuevos)

Todo nuevo, en paralelo a los módulos de scalping existentes:

```
daily_feed.py        # feed de velas diarias (spot) + backfill REST al arrancar
daily_state.py        # estado: historial de cierres, exposición, equity, breaker
daily_execution.py    # traduce exposición objetivo -> órdenes spot
daily_safety.py        # circuit breaker de drawdown + persistencia
```

La señal en sí **no se reimplementa**: `daily_state.py` llama directo a
`estudios.nucleo.senal_tsmom` y a la fórmula de exposición de
`estudios.estudio_vol_overlay` (extraída a una función reutilizable — ver
sección 3.1) sobre el historial de cierres en memoria. Así el código que
corre en vivo es el mismo que se validó, no una reimplementación que se
pueda desalinear con el tiempo (la lección del bug de squeeze/trail:
backtest y vivo divergiendo en silencio).

`notifications.py` se extiende con métodos nuevos (`notify_rebalance`,
`notify_circuit_breaker`) sin tocar los existentes. `main.py: wire_strategy`
pasa a cablear el nuevo feed/estado/ejecución en vez del de scalping;
`run()` arma `daily_safety` en vez de `safety.py` (que sigue existiendo,
sin uso, para cuando/si vuelva el scalping).

### 3.1 Extracción de `exposiciones()` a `estudios/nucleo.py`

Hoy `exposiciones()` vive en `estudios/estudio_vol_overlay.py` y opera
sobre una lista completa de retornos históricos. Se mueve a
`estudios/nucleo.py` (junto a `senal_tsmom`, que ya vive ahí) sin cambiar
su lógica — es un traslado, no una reescritura — para que tanto los
estudios como el bot en vivo importen la misma función desde el mismo
lugar. `estudio_vol_overlay.py` pasa a importarla desde `nucleo` en vez de
definirla.

## 4. Flujo de datos

**Arranque:**
1. `daily_feed.py` hace backfill por REST de ~100 días de velas diarias
   BTCUSDT spot (cubre lookback de 14 días + ventana de vol de 30 días +
   margen).
2. Se carga `daily_safety_state.json` (posición, pico de equity, última
   fecha rebalanceada, estado del breaker).
3. Reconciliación fail-closed: posición persistida vs. balance real de la
   cuenta spot (BTC + USDT). Mismatch → el proceso aborta y pide revisión
   manual (mismo criterio que `safety.reconcile_with_exchange` hoy).
4. Se conecta el websocket `kline_1d`.

**En cada cierre de vela diaria:**
1. Se agrega el cierre nuevo al historial de `daily_state`.
2. Señal: `senal_tsmom(closes, i, 14)` → signo, clampeado a `max(signo, 0)`.
3. Exposición: `exposiciones()` sobre los últimos 30 retornos, σ_target=0.40.
4. Objetivo combinado = señal × exposición (0 a 1).
5. Circuit breaker: equity actual (USDT + BTC×precio) vs. pico histórico;
   drawdown ≥ 50% → objetivo forzado a 0, breaker activo, bloquea
   reentradas hasta reset manual.
6. Si `|objetivo − exposición actual| ≥ 10 puntos porcentuales` (banda de
   rebalanceo, configurable en `config.py`): orden spot market por la
   diferencia. Por debajo de la banda, no se opera ese día.
7. Persistencia + notificación Telegram.

## 5. Manejo de errores

- **Orden spot falla o no confirma:** se loggea, el estado **no** se
  actualiza como si hubiera ejecutado — se reintenta en el próximo cierre
  diario en vez de asumir un fill fantasma.
- **Desconexión del websocket:** reconexión con backoff exponencial (mismo
  patrón que `DataFeed`). Como la señal solo importa al cierre diario, una
  caída de minutos/horas no pierde nada — el backfill REST al reconectar
  cubre el hueco.
- **Balance real vs. persistido no coincide al arrancar:** aborta el
  proceso, no adivina (igual que `safety.reconcile_with_exchange` hoy).

## 6. Config nueva (`config.py`)

```python
TSMOM_LOOKBACK_DAYS = 14
TSMOM_VARIANTE = "long_flat"
VOL_TARGET_ANNUALIZED = 0.40
VOL_TARGET_WINDOW_DAYS = 30
REBALANCE_BAND_PCT = 0.10          # puntos de exposición antes de operar
DRAWDOWN_CIRCUIT_BREAKER_PCT = 0.50  # drawdown desde el pico que fuerza flat
DAILY_STATE_FILE_PATH = "daily_safety_state.json"
SPOT_TAKER_FEE_RATE = 0.0010  # Binance Spot, sin descuento BNB — único tipo de orden usado (sección 4)
```

## 7. Testing

- **Fidelidad señal-vivo vs. estudio (el test más importante):** alimentar
  una serie histórica conocida por `daily_state` y verificar que la
  secuencia de exposiciones objetivo coincide **exactamente** con
  `estudio_momentum.posiciones_tsmom` + `nucleo.exposiciones` corridos
  directo sobre esos mismos cierres. Es el mismo tipo de invariante
  backtest=vivo que el proyecto ya adoptó como práctica permanente después
  del bug de squeeze/trail.
- **Banda de rebalanceo:** Δ por debajo de la banda → no opera; Δ en o por
  encima → opera exactamente la diferencia; objetivo 0 con posición
  abierta → cierra todo.
- **Circuit breaker:** trigger al cruzar 50% de drawdown desde el pico,
  bloqueo de nuevas entradas mientras esté activo, reset manual.
- **Reconciliación y persistencia:** mismatch al arrancar aborta el
  proceso; roundtrip de guardar/cargar `daily_safety_state.json`.
- **Reconexión del feed:** adapta el test existente de `DataFeed` al stream
  `kline_1d`.
- **Notificaciones:** los dos mensajes nuevos, con Telegram deshabilitado
  (no-op) y habilitado (mock del send) — mismo patrón que
  `tests/test_notifications.py`.

## 8. Decisiones tomadas en el brainstorming de este ciclo (trazabilidad)

- Reemplazar el scalping en vez de correr en paralelo o como proceso
  separado — el squeeze ya está descartado como señal, no vale la pena
  mantenerlo corriendo.
- Spot en vez de perp — coincide con el hallazgo de M4 y con que long_flat
  nunca va corto.
- Arranca en paper trading, no en capital real.
- σ_target=0.40 (de los dos valores adoptados por M3, prioriza Sharpe sobre
  el drawdown/peor-mes algo más suave de 0.30).
- Circuit breaker de drawdown al 50% (por encima del peor drawdown visto en
  8+ años de calibración, 43.7%), reemplazando el kill switch diario del
  scalping.
- Código de scalping queda dormido en el repo, no se borra.
- Rebalanceo por banda (10 puntos porcentuales) en vez de rebalanceo diario
  exacto — declarado explícitamente como aproximación operativa no
  validada por el estudio, para no pagar fees de ajustes diarios.
