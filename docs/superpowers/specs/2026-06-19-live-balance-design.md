# Balance real de cuenta — diseño

Fecha: 2026-06-19

## 1. Resumen y objetivo

`risk.py` usa `PAPER_BALANCE_USDT` (constante hardcodeada, $10,000) tanto
para el sizing de posición (`open_position`) como para el denominador del
kill switch diario (`safety.after_trade_closed`) — en los dos casos, sin
importar el modo. Esto fue señalado explícitamente como fuera de alcance
en `2026-06-16-operational-safety-design.md` ("Fetchear el balance real
del exchange queda para un diseño aparte"). Este es ese diseño.

**Objetivo:** en modo LIVE, el bot debe sizing-ear posiciones y calcular
el umbral del kill switch diario contra el balance real de la cuenta de
Binance Futures, no contra un número asumido. El balance se toma como una
foto fija al arrancar el bot y en cada rollover UTC — no se refetchea en
cada trade, para que el 2% del kill switch sea un umbral estable durante
el día y consistente con `pnl_today` (que se acumula desde ese mismo
punto de partida).

### No-goals (fuera de alcance de este diseño)

- Configurar leverage o margin mode en el exchange — se asume que la
  cuenta ya está configurada manualmente antes de operar en LIVE.
- Observabilidad/alertas (Telegram, email, dashboards) — sesión separada.
- Supervisión de proceso (systemd/docker, restart automático tras crash)
  — sesión separada.
- Usar el balance en tiempo real (incluyendo PnL no realizado de una
  posición abierta) como denominador continuo del kill switch — el
  diseño usa una foto fija diaria, no un valor que se mueve con cada
  trade.
- Soportar múltiples monedas de margen — se asume USDT, igual que el
  resto del bot.

## 2. Modelo de datos (`state.py`)

Nuevo campo en `MarketState`:

```python
daily_starting_balance: Optional[float] = None
```

`None` representa "todavía no se resolvió" — pasa eso en el primerísimo
arranque, antes de que `safety.maybe_reset_daily` corra por primera vez,
y también si se carga un `safety_state.json` escrito por una versión
anterior del bot que no tenía este campo.

## 3. Constante movida (`config.py`)

`PAPER_BALANCE_USDT` se muda de `risk.py` a `config.py`. Hoy `risk.py`
importa `safety` (`risk.py` → `safety.py`); si `safety.py` necesita esta
constante para resolver el balance en modo paper, un import en la
dirección opuesta crearía un ciclo. `config.py` no depende de nada, así
que ambos módulos la importan desde ahí sin problema. El valor no cambia
(10,000.0).

## 4. Resolución del balance (`safety.py`)

### `fetch_real_balance(exchange) -> float`

```python
def fetch_real_balance(exchange) -> float:
    try:
        balance = exchange.fetch_balance()
        total = balance["total"]["USDT"]
    except Exception:
        logger.error("No se pudo obtener el balance real de la cuenta", exc_info=True)
        sys.exit(1)
    return float(total)
```

Usa el campo unificado de ccxt `total.USDT` (wallet balance) — no incluye
el PnL no realizado de una posición abierta, la misma simplificación que
ya acepta `reconcile_with_exchange` para el tamaño de la posición
persistida. Cualquier excepción (red, auth, rate limit, exchange caído) o
ausencia de la clave `USDT` termina el proceso — mismo criterio
fail-closed que ya usa `reconcile_with_exchange`.

### `maybe_reset_daily(state, exchange=None)` — firma extendida

Hoy:
```python
def maybe_reset_daily(state: MarketState) -> None:
    today = _today_utc()
    if state.last_reset_date == today:
        return
    ...
```

Nuevo:
```python
def maybe_reset_daily(state: MarketState, exchange=None) -> None:
    today = _today_utc()
    if state.last_reset_date == today and state.daily_starting_balance is not None:
        return
    state.daily_starting_balance = (
        PAPER_BALANCE_USDT if exchange is None else fetch_real_balance(exchange)
    )
    state.pnl_today = 0.0
    state.trades_today = 0
    state.consecutive_losses = 0
    state.kill_switch_active = False
    state.last_reset_date = today
    save_state(state)
```

La condición de skip ahora exige *ambas* cosas: mismo día Y balance ya
resuelto. Esto cubre el caso "arranca por primera vez, mismo día, pero
`daily_starting_balance` es `None`" (primer uso, o JSON viejo sin el
campo) sin necesitar una rama especial.

### `can_open_new_position(state, exchange=None) -> bool`

Threadea `exchange` a `maybe_reset_daily`:

```python
def can_open_new_position(state: MarketState, exchange=None) -> bool:
    maybe_reset_daily(state, exchange)
    return not state.kill_switch_active
```

### `after_trade_closed(state, total_trade_net) -> None` — pierde el parámetro `balance`

Hoy `risk.py` le pasa `PAPER_BALANCE_USDT` hardcodeado en cada llamada.
Nuevo: lee `state.daily_starting_balance` directamente (cae a
`PAPER_BALANCE_USDT` solo de forma defensiva si por algún motivo es
`None` — no debería pasar nunca en producción, porque
`can_open_new_position` ya lo resuelve antes de que exista la chance de
abrir un trade).

```python
def after_trade_closed(state: MarketState, total_trade_net: float) -> None:
    balance = state.daily_starting_balance or PAPER_BALANCE_USDT
    ...  # resto sin cambios, usa `balance` donde antes usaba el parámetro
```

### Persistencia (`save_state` / `load_into_state`)

El JSON persistido agrega una clave:

```json
{
  "date_utc": "2026-06-19",
  "daily_starting_balance": 14230.55,
  "pnl_today": -120.5,
  "trades_today": 4,
  "consecutive_losses": 2,
  "kill_switch_active": false,
  "position": null
}
```

`load_into_state` la lee con `.get("daily_starting_balance")` (default
`None`) — un archivo viejo sin la clave carga `None`, y el próximo
`maybe_reset_daily` dispara un fetch fresco en vez de romper.

## 5. Cambios en `risk.py`

`open_position(state, side, price, balance=None)`:

```python
def open_position(state, side, price, balance=None):
    if balance is None:
        balance = state.daily_starting_balance or PAPER_BALANCE_USDT
    ...  # resto sin cambios
```

Mantiene el parámetro `balance` (con default `None` en vez de
`PAPER_BALANCE_USDT`) para no romper los tests que ya pasan un balance
explícito.

`close_position` deja de pasarle un balance a `safety.after_trade_closed`
— ahora la llamada es `safety.after_trade_closed(state, total_trade_net)`.

## 6. Cambios en `main.py`

En `run()`, junto al `reconcile_with_exchange` existente:

```python
safety.load_into_state(state)
if not PAPER_MODE:
    safety.reconcile_with_exchange(state, engine.exchange)
safety.maybe_reset_daily(state, engine.exchange)  # nuevo — resuelve el balance antes de la primera vela
```

En `wire_strategy`, dentro de `on_candle_1m`:

```python
if state.position is None and safety.can_open_new_position(state, engine.exchange):
```

## 7. Backtest — sin cambios

`backtest.py` construye `ExecutionEngine` sin pasar por la rama LIVE de
`_init_exchange` (porque `PAPER_MODE` es `True` por default cuando no se
cargó `.env`), así que `engine.exchange` ya es `None` ahí. El backtest
sigue usando `PAPER_BALANCE_USDT` sin tocar la red ni requerir cambios en
`backtest_feed.py`/`backtest.py`.

## 8. Manejo de errores

- **Fetch falla al arrancar:** logueado con `logger.error`, `sys.exit(1)`
  antes de conectar el feed — el bot nunca llega a operar con un balance
  asumido.
- **Fetch falla en el rollover UTC, en medio de la operativa LIVE:**
  mismo `sys.exit(1)`, ahora en medio del loop de eventos. Es
  intencional — mismo criterio que la reconciliación de posición al
  arrancar: prefieren parar a seguir con un número adivinado. (Sin
  supervisión de proceso todavía, esto requiere reinicio manual — ítem ya
  señalado como no-goal.)
- **Respuesta del exchange sin la clave `USDT`:** tratado igual que una
  excepción — `sys.exit(1)`.
- **Paper/backtest:** nunca toca la red, no puede fallar por este motivo.
- **JSON persistido sin la clave nueva (formato viejo):** no rompe,
  `daily_starting_balance` carga `None`, dispara un fetch fresco en el
  próximo `maybe_reset_daily`.

## 9. Testing

`tests/test_safety.py`:
- `_FakeExchange` se extiende con `fetch_balance()` configurable (devuelve
  `{"total": {"USDT": <valor>}}`).
- `maybe_reset_daily` sin exchange → `state.daily_starting_balance ==
  config.PAPER_BALANCE_USDT`.
- `maybe_reset_daily` con `_FakeExchange` → `state.daily_starting_balance`
  toma el valor fetcheado.
- Llamado dos veces el mismo día → la segunda no vuelve a invocar
  `fetch_balance` (contador en el fake).
- Rollover a un día nuevo → sí refetchea y actualiza el valor.
- `fetch_balance()` lanza excepción → `pytest.raises(SystemExit)`.
- Respuesta sin la clave `USDT` → `pytest.raises(SystemExit)`.
- Round-trip de persistencia incluye `daily_starting_balance`.
- `load_into_state` con JSON viejo (sin la clave) → carga `None`, no
  rompe.
- Los tests existentes de `after_trade_closed(..., balance=10_000.0)` se
  actualizan: ahora setean `state.daily_starting_balance = 10_000.0`
  antes de llamar, porque el parámetro se elimina de la firma.

`tests/test_risk.py`:
- Los tests de `open_position` que dependían del default hardcodeado
  pasan a setear `state.daily_starting_balance` en el `MarketState` de
  prueba.

`tests/test_main.py`:
- Nuevo test: `wire_strategy`'s `on_candle_1m` llama a
  `safety.can_open_new_position` pasando `engine.exchange` (no solo
  `state`).

`tests/test_backtest*.py`: sin cambios — `engine.exchange` ya es `None`
en ese camino.
