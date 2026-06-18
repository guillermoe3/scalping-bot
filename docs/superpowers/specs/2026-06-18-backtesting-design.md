# Backtesting harness — diseño

Fecha: 2026-06-18

## 1. Resumen y objetivo

Este ciclo de diseño quedó explícitamente diferido en
`2026-06-16-operational-safety-design.md` y en
`2026-06-17-strategy-core-unit-tests-design.md` ("ciclo de diseño aparte,
que arranca después de que este se complete"). Con ambos completos (120
tests pasando, kill switch + fees + reconciliación en producción), este es
ese ciclo.

**Objetivo:** una herramienta rápida de validación de lógica — detectar
regresiones al tocar parámetros de régimen/squeeze/risk, y tener una señal
direccional de si la estrategia tiene edge sobre historia real de
BTC/USDT. No es una herramienta de evaluación rigurosa de rentabilidad
para poner capital real (eso requeriría datos de profundidad de order
book reales, que no están disponibles gratis — ver sección 5).

**Arquitectura:** se reusa el núcleo event-driven del bot tal cual está
(`risk.py`, `signals.py`, `regime.py`, `execution.py` en modo paper, etc.)
sin duplicar ninguna lógica de estrategia. Un feed histórico nuevo
(`BacktestFeed`) reproduce datos reales de Binance (klines + trades, vía
`ccxt`, ya dependencia del proyecto) disparando los mismos handlers que
`main.py` registra hoy contra el feed en vivo.

### No-goals (fuera de alcance de este diseño)

- Modelar profundidad real de order book — no hay datos históricos
  gratuitos de L2 para Binance. Se aproxima (sección 5).
- Backtestear el filtro macro (`context.py`) — Yahoo Finance solo da
  velas de 15m de los últimos ~60 días, no se puede reconstruir la
  correlación BTC/SPY para cualquier rango histórico. Se desactiva en
  backtest (sección 5).
- Optimización de parámetros (grid search, walk-forward, etc.) — esta
  herramienta corre un rango con un set de parámetros fijo por vez.
- Gráficos (equity curve, etc.) — el reporte es consola + CSV (sección 7).
- Soportar otro símbolo que no sea BTC/USDT — el resto del bot
  (`execution.py`, `config.SYMBOL`) ya está hardcodeado a ese par.

## 2. El reloj simulado (`clock.py`)

El bot usa `time.time()`/`datetime.now()` directamente en 5 lugares para
lógica que depende de cuánto tiempo transcurrió:

- `risk.py:66` — `Position.entry_time`.
- `risk.py:251` — `held_min` del gate de `time_exit`.
- `momentum.py:20` — elapsed de `update_volume_velocity`.
- `momentum.py:36` — `held_seconds` de `should_abort_for_momentum`.
- `safety.py:21` (`_today_utc`) — fecha del reset diario del kill switch.

Un backtest reproduce meses de historia en segundos de reloj real, así
que si estas funciones siguen leyendo el reloj de la máquina, el
`time_exit` nunca dispara, el momentum-abort queda roto, y el kill switch
nunca rota de día (si se activa una vez, queda activado el resto del
backtest entero).

Módulo nuevo, `clock.py`:

```python
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

_override: Optional[float] = None


def now() -> float:
    """Segundos unix. Devuelve time.time() salvo que el backtest haya
    fijado un tiempo simulado con set_now()."""
    return _override if _override is not None else time.time()


def today_utc() -> str:
    return datetime.fromtimestamp(now(), tz=timezone.utc).date().isoformat()


def set_now(ts: float) -> None:
    """Solo lo llama el backtest, antes de procesar cada evento histórico."""
    global _override
    _override = ts


def reset() -> None:
    global _override
    _override = None
```

`risk.py` y `momentum.py` cambian sus `import time` / usos de
`time.time()` por `import clock` / `clock.now()`. `safety.py` cambia el
cuerpo de `_today_utc()` para delegar en `clock.today_utc()` (la función
sigue existiendo con el mismo nombre — los tests existentes la llaman
directamente). Por defecto (`_override is None`), el comportamiento es
idéntico al actual: **los 120 tests existentes no cambian**. Ninguna
firma pública cambia.

## 3. Obtención y caché de datos históricos (`backtest_feed.py`)

`BacktestFeed` trae, para un rango `[start, end)`:

- **Velas 1m** vía `ccxt.binance().fetch_ohlcv("BTC/USDT", "1m", since=..., limit=...)`,
  paginado hasta cubrir todo el rango.
- **Velas 5m y 15m**: no se piden por separado. Se **resamplean
  localmente** a partir de las velas 1m ya traídas (agrupando de 5 y de
  15 en 5/15: open=open de la primera, high/low=max/min del grupo,
  close=close de la última, volume=suma). Es matemáticamente idéntico a
  lo que devolvería Binance, evita 2 llamadas/cachés adicionales, y
  garantiza alineación perfecta con los límites de cada vela 1m.
- **Trades reales** vía `fetch_trades("BTC/USDT", since=..., limit=...)`,
  paginado por todo el rango. Cada trade normalizado por ccxt ya trae
  `side` ("buy"/"sell" del agresor) — el CVD se reconstruye **exacto**,
  no aproximado.

### Caché local (`backtest_cache/`, gitignored)

Las velas 1m y los trades de un rango ya descargado se guardan en
`backtest_cache/{symbol}_klines1m_{start}_{end}.json` y
`backtest_cache/{symbol}_trades_{start}_{end}.json`. Antes de pedir datos
a la red, `BacktestFeed` chequea si el archivo existe; si existe, lo lee
en vez de llamar a `ccxt`. Necesario porque `fetch_trades` sobre BTC/USDT
es pesado (miles de trades por minuto) y el objetivo explícito es poder
re-correr el backtest varias veces mientras se ajustan parámetros.

Escritura atómica: se escribe a `<nombre>.tmp` y se hace `os.replace()` al
nombre final solo al terminar. Si el proceso se corta a mitad de una
descarga larga, nunca queda un archivo de caché a medio completar que se
reuse como si estuviera entero.

`--no-cache` (sección 8) fuerza a ignorar la caché existente y
redescargar.

## 4. Reproducción de eventos (`BacktestFeed.replay`)

Se mezclan cronológicamente dos tipos de eventos y se disparan los mismos
handlers que en vivo:

**Por cada trade** (orden de `timestamp`):
1. `state.last_price = trade.price`.
2. Sintetiza el book: `spread = last_price * spread_pct`,
   `last_bid = last_price - spread/2`, `last_ask = last_price + spread/2`
   (`spread_pct` configurable, sección 8).
3. Actualiza el CVD con el `side` real del trade — equivalencia exacta
   con el signo que usa `data_feed._handle_trade` hoy:
   `trade.side == "sell"` (el agresor vendió) equivale a
   `is_buyer_maker == True` → `state.cvd -= trade.amount`;
   `trade.side == "buy"` (el agresor compró) equivale a
   `is_buyer_maker == False` → `state.cvd += trade.amount`.
4. Actualiza las velas en formación (`live_1m/5m/15m`) reusando
   `_update_live_candles`, extraída de `data_feed.py` a una función libre
   (la misma que usa `DataFeed` en vivo — sin duplicar lógica).
5. `clock.set_now(trade.timestamp)`.
6. Dispara `on_trade` — la misma secuencia que `main.py` registra hoy
   (`update_volume_velocity(state)` + `await engine.monitor_and_exit()`).

**Por cada cierre de vela** (1m/5m/15m, al cruzar su límite):
1. Usa el OHLCV ya cerrado (real de Binance para 1m, resampleado para
   5m/15m) — no uno reconstruido a mano desde los trades.
2. Hace `append` a `state.candles_Xm`, vacía `state.live_Xm`.
3. `clock.set_now(close_ts)`.
4. Dispara `on_candle_Xm` — la misma secuencia que hoy en `main.py`.

Para que `backtest.py` no duplique la secuencia de `main.py`
(indicadores → régimen → MTF trend → swing points → squeeze → entry
signal), se extrae esa secuencia de `main.py: run()` a una función
exportable:

```python
def wire_strategy(state: MarketState, feed, engine: ExecutionEngine) -> None:
    """Registra los handlers on_trade/on_candle_1m/5m/15m contra feed.
    feed puede ser DataFeed (en vivo) o BacktestFeed (backtest) — solo
    necesita exponer la misma interfaz de registro (duck typing)."""
```

`main.py: run()` pasa a llamar `wire_strategy(state, feed, engine)` en
vez de definir los closures inline. `backtest.py` llama exactamente a la
misma función con su `BacktestFeed`.

## 5. Aproximaciones (recapitulación explícita)

- **Order book real:** no se modela. `state.ob_snapshots` queda vacío
  todo el backtest → `order_flow.get_book_imbalance` siempre devuelve
  `(1.0, "neutral")` (ya es su comportamiento documentado por debajo del
  mínimo de snapshots — cero código nuevo en `order_flow.py`). El precio
  de fill y el filtro de spread sí funcionan, contra el spread sintético
  de la sección 4.
- **Filtro macro:** `MacroFilter` no se instancia en el backtest.
  `state.macro_blocks_longs`/`macro_blocks_shorts` quedan en su default
  (`False`) toda la corrida — ese gate nunca bloquea en backtest.
- **Kill switch diario:** sí se modela, fielmente. Como `safety._today_utc()`
  delega en `clock.today_utc()` (sección 2), y el backtest fija
  `clock.set_now(...)` antes de cada evento, `maybe_reset_daily` rota de
  día usando la fecha *simulada* de los datos, no la fecha real de
  ejecución — sin cambiar la firma de ninguna función de `safety.py`.
- **Persistencia de estado:** antes de correr, el backtest fija
  `safety.STATE_FILE_PATH` a un archivo temporal (mismo patrón que ya usa
  `tests/test_safety.py` con `monkeypatch`). Nunca toca el
  `safety_state.json` real del bot en vivo.

## 6. Captura de trades (`execution.py`)

`ExecutionEngine.__init__` gana un parámetro opcional, sin romper
compatibilidad con el uso en vivo:

```python
def __init__(self, state: MarketState, on_trade_closed: Optional[Callable[[dict], None]] = None) -> None:
    self.state = state
    self._exchange = None
    self._on_trade_closed = on_trade_closed
    ...
```

`exit()` y `partial_exit()` lo invocan justo después de aplicar el cierre
real/parcial (después de `close_position`/`apply_partial_close`
respectivamente), con el mismo dict de campos en ambos casos — pero
**el campo `"size"` se captura distinto en cada uno**, porque
`apply_partial_close` ya reduce `pos.size` al remanente antes de que se
pueda leer:

- En `exit()`: `"size": pos.size` — `close_position` no muta `pos.size`
  (la posición se descarta entera), así que sigue siendo el tamaño que
  se cerró.
- En `partial_exit()`: `"size": close_size` — el parámetro recibido por
  la función, capturado **antes** de llamar a `apply_partial_close`
  (que sí reduce `pos.size` al remanente). Usar `pos.size` ahí sería un
  bug — reportaría lo que queda abierto, no lo que se cerró.

```python
{
    "side": pos.side, "entry_price": pos.entry_price, "exit_price": fill_price,
    "size": ...,  # pos.size en exit(), close_size en partial_exit() — ver arriba
    "reason": reason, "leg_net": net,
    "total_trade_net": pos.realized_pnl if not is_partial else None,
    "fees_paid": pos.fees_paid, "entry_time": pos.entry_time,
    "exit_time": clock.now(), "is_partial": is_partial,
}
```

Si `on_trade_closed` es `None` (default, uso en vivo actual), no pasa
nada — cero cambio de comportamiento fuera del backtest.

## 7. Reporte (`backtest.py`)

`backtest.py` pasa un callback que junta estos dicts en una lista durante
el replay. Al terminar:

- **CSV** (ruta de `--out`, default `backtest_trades.csv`): una fila por
  dict — incluye los legs parciales de TP1 y el cierre final de cada
  trade.
- **Resumen en consola**, calculado solo sobre los legs con
  `is_partial=False` (cada uno es un trade completo, con su
  `total_trade_net` ya agregando entrada + parciales + cierre final):
  - Cantidad de trades, win rate.
  - P&L neto total.
  - Profit factor (`sum(ganadores) / abs(sum(perdedores))`).
  - Max drawdown sobre la curva de equity (suma acumulada de
    `total_trade_net` en orden cronológico).
  - Racha máxima de pérdidas consecutivas.

## 8. Interfaz de línea de comandos (`backtest.py`)

```
.venv/bin/python backtest.py --start 2024-01-01 --end 2024-03-01 \
    [--balance 10000] [--spread-pct 0.0001] [--out backtest_trades.csv] [--no-cache]
```

- `--start YYYY-MM-DD` (requerido), `--end YYYY-MM-DD` (requerido,
  exclusivo) — valida `start < end` y que ninguno sea futuro; si no,
  termina con un mensaje claro antes de pedir ningún dato.
- `--balance` (default `risk.PAPER_BALANCE_USDT`) — balance inicial para
  sizing y umbral del kill switch.
- `--spread-pct` (default `config.BACKTEST_SYNTHETIC_SPREAD_PCT = 0.0001`,
  es decir 0.01% del precio por lado) — para probar sensibilidad al
  spread sintético sin tocar código.
- `--out` (default `backtest_trades.csv`).
- `--no-cache` — ignora la caché existente y vuelve a descargar.

Símbolo fijo en `BTC/USDT`.

## 9. Manejo de errores

- **Caché atómica** (sección 3): nunca queda un archivo a medio escribir
  que se lea como completo.
- **Rango vacío o sin datos** (ej. fecha anterior al listing del par):
  termina con un mensaje explícito en vez de generar un reporte vacío en
  silencio.
- **Errores de red/rate-limit de ccxt**: se deja que `enableRateLimit=True`
  maneje el throttling normal de la API; un error de red puntual no se
  reintenta automáticamente en v1 — el error de `ccxt` queda visible
  (herramienta de desarrollo, no servicio en producción).
- **Validación de fechas de CLI** (sección 8): falla antes de tocar la
  red.

## 10. Testing

Mismo patrón que el resto del proyecto: pytest, sin mockear la función
bajo prueba, solo la I/O real (red).

- `tests/test_clock.py`: `now()` por defecto ronda `time.time()`;
  `set_now()`/`reset()` fijan y liberan el override; `today_utc()`
  deriva correctamente de un `set_now()` fijo, incluyendo un caso al
  borde de un cambio de día UTC.
- `tests/test_risk.py` / `tests/test_momentum.py` / `tests/test_safety.py`:
  los tests existentes no se tocan (el comportamiento default de
  `clock` es idéntico al `time.time()` actual). Se agregan 1-2 tests
  nuevos por archivo que fijan `clock.set_now(...)` y confirman que
  `entry_time`, el gate de `time_exit`, el momentum-abort, y el reset
  diario del kill switch usan el tiempo simulado en vez del real.
- `tests/test_execution.py`: se extiende con tests para `on_trade_closed`
  — se llama con el dict correcto en cierre total y en cierre parcial; si
  es `None` (default), no rompe nada.
- `tests/test_backtest_feed.py`: se inyecta un exchange fake (mismo
  patrón que `_FakeExchange` en `test_safety.py`) con klines/trades
  sintéticos fijos — se testea el orden de eventos (trades y cierres de
  vela intercalados correctamente), la reconstrucción de velas en
  formación, el spread sintético, el resampleo de 5m/15m desde 1m, y que
  dispara los handlers correctos en el orden correcto. Cero llamadas
  reales a la red.
- Caché: test con exchange fake + `tmp_path` (mismo patrón que
  `_isolate_state_file` en `test_safety.py`) — la segunda corrida sobre
  el mismo rango no vuelve a llamar al fake (se verifica con contador de
  llamadas); `--no-cache` sí vuelve a llamarlo.
- `tests/test_backtest.py`: test de integración liviano para
  `backtest.py` — exchange fake con un puñado de velas/trades sintéticos
  cubriendo un par de horas, corre `main()` end-to-end, y verifica que
  produce el CSV y el resumen esperado sin tirar excepciones.

No se agrega ninguna dependencia nueva (`ccxt` ya está en
`requirements.txt`; testing sigue usando solo `pytest` + `monkeypatch`).
