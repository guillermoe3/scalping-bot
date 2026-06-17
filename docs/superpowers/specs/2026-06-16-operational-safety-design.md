# Endurecimiento de seguridad operativa — diseño

Fecha: 2026-06-16

## 1. Resumen y objetivo

El bot de scalping (BTCUSDT, Binance) hoy no tiene ninguna salvaguarda de
sesión: puede perder dinero sin límite en un día, puede arrancar a ciegas
después de un crash en modo LIVE sin saber si ya tiene una posición abierta
en el exchange, y su PnL no refleja el costo real de operar (fees, spread).
Este diseño agrega cuatro piezas que se apoyan entre sí:

1. Kill switch diario (pérdida % o pérdidas consecutivas).
2. Persistencia de estado mínimo + reconciliación contra el exchange al
   reiniciar en modo LIVE.
3. Fees y slippage realistas en el cálculo de PnL (incluye un fix a un bug
   existente en el manejo de TP1).
4. Filtro de entrada por spread anormal.

Todo el código nuevo vive en un módulo `safety.py`, siguiendo el patrón
existente de un archivo por responsabilidad (`regime.py`, `risk.py`,
`signals.py`, etc.).

### No-goals (fuera de alcance de este diseño)

- Backtesting o tests de la lógica de señales/régimen (`regime.py`,
  `signals.py`) — quedó para una sesión de "validación de estrategia"
  separada.
- Observabilidad/journal de trades en CSV o DB, métricas, dashboard —
  sesión separada.
- Limpieza de la duplicación `update_mtf_trend`/`update_mtf_trends` ni el
  branch muerto en `context.py:76` — sesión separada de calidad de código.
- Obtener el balance real de la cuenta en modo LIVE. `risk.py` ya usa hoy
  `PAPER_BALANCE_USDT` (constante hardcodeada) tanto para el sizing de
  posición como, con este diseño, para el umbral del kill switch diario,
  en ambos modos. Es una limitación preexistente, no introducida por este
  diseño — pero significa que en LIVE el kill switch dispara contra un
  balance asumido de $10,000, no el balance real de la cuenta. Fetchear
  el balance real del exchange queda para un diseño aparte.

## 2. Bug existente que este diseño corrige

`risk.py:175-188` (`_handle_tp1`): cuando se toca TP1, el código reduce
`pos.size` al 50% pero:
- nunca acredita el PnL de la porción cerrada a `state.pnl_today`,
- en modo LIVE nunca envía la orden de cierre parcial al exchange.

Resultado: el estado interno cree que cerró la mitad de la posición, pero
en el exchange real seguiría abierta al 100%. Esto se corrige como parte
de la pieza de fees/slippage (sección 5), porque ambas requieren la misma
separación entre "detectar que TP1 se cumplió" (puro) y "ejecutar el
cierre parcial" (con I/O hacia el exchange).

## 3. Modelo de datos (`state.py`)

En `MarketState`, agregar:

```python
consecutive_losses: int = 0
kill_switch_active: bool = False
last_reset_date: Optional[str] = None   # fecha UTC "YYYY-MM-DD" del último reset diario
```

En `Position`, agregar:

```python
fees_paid: float = 0.0      # acumulado de fees pagados por esta posición (informativo/logging)
realized_pnl: float = 0.0   # neto ya contabilizado de esta posición: fee de entrada + cierres parciales + cierre final
```

`realized_pnl` es la pieza clave que conecta fees con el kill switch: al
cierre final de una posición, su valor es la verdad de si el trade en
conjunto fue ganador o perdedor (no solo la última pierna).

## 4. Kill switch diario (`safety.py`)

Constantes nuevas en `config.py`:

```python
KILL_SWITCH_DAILY_LOSS_PCT = 0.02       # -2% del balance en el día
KILL_SWITCH_CONSECUTIVE_LOSSES = 3      # 3 trades perdedores seguidos
```

Funciones en `safety.py`:

- `maybe_reset_daily(state: MarketState) -> None`
  Compara `state.last_reset_date` contra la fecha UTC actual
  (`datetime.now(timezone.utc).date().isoformat()`). Si cambió: resetea
  `pnl_today = 0.0`, `trades_today = 0`, `consecutive_losses = 0`,
  `kill_switch_active = False`, actualiza `last_reset_date`, persiste.

- `can_open_new_position(state: MarketState) -> bool`
  Llama primero a `maybe_reset_daily(state)`, luego devuelve
  `not state.kill_switch_active`.
  Se consulta en `main.py` antes de evaluar `check_entry_signal` — el
  switch **solo bloquea entradas nuevas**; una posición ya abierta sigue
  gestionada con normalidad por `manage_position` hasta su salida natural
  (SL/TP/tiempo/momentum).

- `after_trade_closed(state: MarketState, total_trade_net: float,
  balance: float = PAPER_BALANCE_USDT) -> None`
  Se llama desde `close_position` (risk.py) en el cierre final de una
  posición, con `total_trade_net = pos.realized_pnl` (después de sumarle
  la pierna final).
  - Si `total_trade_net < 0`: `consecutive_losses += 1`.
  - Si no: `consecutive_losses = 0`.
  - Si `state.pnl_today <= -KILL_SWITCH_DAILY_LOSS_PCT * balance` o
    `consecutive_losses >= KILL_SWITCH_CONSECUTIVE_LOSSES`: activa
    `kill_switch_active = True` y loguea con `logger.warning` cuál de los
    dos triggers (o ambos) lo disparó.
  - Llama a `save_state(state)` al final.

## 5. Fees y slippage realistas (`execution.py` + `risk.py`)

Constante nueva en `config.py`:

```python
TAKER_FEE_RATE = 0.0005   # 0.05% por lado, Binance Futures USDT-M sin descuento BNB
```

### Fill price realista

`execution.py` deja de usar `state.last_price` como precio de fill.
En su lugar cruza el spread (como lo haría una orden market real):

- LONG entra al `ask` (`state.last_ask`), sale al `bid` (`state.last_bid`).
- SHORT entra al `bid`, sale al `ask`.

`enter()` rechaza la entrada (`return False`) si `last_bid <= 0` o
`last_ask <= 0` (libro todavía no recibido).

### Entrada (`open_position`, risk.py)

```python
entry_fee = size * price * TAKER_FEE_RATE
state.pnl_today -= entry_fee
# Position se crea con fees_paid=entry_fee, realized_pnl=-entry_fee
```

### Fix de TP1 — separar detección de ejecución

`risk.py` expone una función pura nueva, reemplazando `_handle_tp1`:

```python
def check_tp1(state: MarketState) -> Optional[float]:
    """Si TP1 se cumple por primera vez, marca pos.tp1_hit y devuelve
    el tamaño (BTC) a cerrar. Si no, devuelve None. No muta PnL ni size:
    eso lo hace execution.apply_partial_close vía la orden real."""
```

`execution.py` gana:

```python
async def partial_exit(self, close_size: float, reason: str) -> float:
    """Calcula el fill cruzando el spread, en LIVE manda una orden
    reduceOnly real por close_size, y delega en risk.apply_partial_close
    para descontar fee y acreditar el PnL neto de esa porción."""
```

`risk.py` gana:

```python
def apply_partial_close(state: MarketState, close_size: float, fill_price: float) -> float:
    """Calcula PnL bruto de close_size, descuenta fee, acredita neto a
    pnl_today y a pos.realized_pnl, reduce pos.size, devuelve el neto."""
```

`manage_position` (risk.py) cambia su firma de retorno:

```python
def manage_position(state: MarketState) -> tuple[Optional[float], Optional[str]]:
    """Devuelve (tp1_close_size, exit_reason). Cualquiera de los dos
    puede ser None."""
```

`execution.py: monitor_and_exit` pasa a:

```python
async def monitor_and_exit(self) -> None:
    if self.state.position is None:
        return
    tp1_close_size, reason = manage_position(self.state)
    if tp1_close_size:
        await self.partial_exit(tp1_close_size, "tp1")
    if reason:
        await self.exit(reason)
```

### Cierre final (`close_position`, risk.py)

Aplica el mismo descuento de fee sobre `pos.size` remanente, acumula en
`pos.realized_pnl`, y al final llama a
`safety.after_trade_closed(state, pos.realized_pnl)` antes de poner
`state.position = None`.

## 6. Persistencia y reconciliación (`safety.py`)

Constante nueva en `config.py`:

```python
STATE_FILE_PATH = "safety_state.json"
```

### Formato del archivo

```json
{
  "date_utc": "2026-06-16",
  "pnl_today": -120.5,
  "trades_today": 4,
  "consecutive_losses": 2,
  "kill_switch_active": false,
  "position": null
}
```

Cuando hay posición abierta, `"position"` lleva todos los campos de
`Position` (side, entry_price, size, entry_time, stop_loss, tp1,
initial_atr, initial_sl_distance, tp1_hit, breakeven_moved, fees_paid,
realized_pnl).

### Cuándo se escribe

`save_state(state)` se llama después de cada evento financiero:
apertura (`open_position`), cierre parcial (`apply_partial_close`), cierre
final (`close_position`), y dentro de `after_trade_closed`.

### Carga al arrancar

`load_into_state(state: MarketState) -> None`, llamada desde `main.py`
antes de conectar el feed:
- Si el archivo no existe: arranca en cero, sin warning (caso normal del
  primer arranque).
- Si existe pero no parsea como JSON válido: `logger.warning` explícito y
  arranca en cero (no levanta excepción).
- Si parsea: carga los campos a `state` (incluida la posición, si había).

### Reconciliación contra el exchange (solo si `PAPER_MODE=false`)

`reconcile_with_exchange(state: MarketState, exchange) -> None`, llamada
desde `main.py` justo después de `load_into_state`, antes de
`asyncio.gather(...)`:

1. Llama a `exchange.fetch_positions(["BTC/USDT"])` (ccxt).
2. Si la consulta falla (red, auth, etc.): trata como mismatch (paso 4).
3. Compara la posición persistida (`state.position`, ya cargada por
   `load_into_state`) contra la posición real reportada:
   - Ninguna de las dos tiene posición → arranca normal.
   - Ambas tienen la misma posición (mismo side, tamaño dentro de 0.1% de
     tolerancia) → no hace nada más, `state.position` ya está cargada
     correctamente, arranca normal.
4. Cualquier otra combinación (una tiene posición y la otra no, sides
   distintos, tamaños fuera de tolerancia, o falla la consulta): loguea
   con `logger.error` el detalle completo de ambos estados y termina el
   proceso (`sys.exit(1)`) sin conectar el feed ni operar. Requiere
   intervención manual.

En modo PAPER, `reconcile_with_exchange` no se llama — el JSON es la
única fuente de verdad.

## 7. Filtro de entrada por spread (`signals.py`)

Constante nueva en `config.py`:

```python
SPREAD_FILTER_ATR_PCT = 0.05   # bloquea si spread > 5% del ATR de 1m
```

Nueva condición dentro de `check_entry_signal` (después de las
existentes): si `state.atr > 0` y
`state.spread > SPREAD_FILTER_ATR_PCT * state.atr`, rechaza la entrada
con un `logger.debug` igual de explícito que los demás rechazos.

## 8. Cambios en `main.py`

```python
import safety
from execution import ExecutionEngine, PAPER_MODE
...
async def run() -> None:
    state = MarketState()
    safety.load_into_state(state)

    feed = DataFeed(state)
    engine = ExecutionEngine(state)
    macro = MacroFilter(state)

    if not PAPER_MODE:
        safety.reconcile_with_exchange(state, engine.exchange)

    ...
    async def on_candle_1m(candle):
        ...
        if state.position is None and safety.can_open_new_position(state):
            signal = check_entry_signal(state)
            if signal is not None:
                await engine.enter(signal)
```

`ExecutionEngine` expone `self._exchange` como propiedad pública
`exchange` para que `safety.py` pueda usarlo sin acceder a un atributo
privado.

## 9. Manejo de errores

- Escritura de `safety_state.json` fallida (permisos, disco lleno): se
  loguea con `logger.exception`, no interrumpe la sesión — la verdad
  operativa durante la sesión sigue siendo el estado en memoria + el
  exchange real.
- Lectura corrupta: warning explícito, arranque en cero, nunca una
  excepción no manejada que tire abajo el proceso.
- Falla de red al reconciliar contra el exchange en modo LIVE: se trata
  como mismatch — el bot no arranca a operar a ciegas.

## 10. Testing

El proyecto no tiene tests hoy. Dado que esta es lógica financiera nueva
(fees, kill switch, reconciliación), se agrega **pytest** con alcance
acotado solo al código nuevo/modificado de este diseño (no a
`regime.py`/`signals.py` en general, eso queda para la sesión de
validación de estrategia):

- `tests/test_safety.py`:
  - rollover de día UTC en `maybe_reset_daily` (resetea los 4 campos).
  - `after_trade_closed` dispara el kill switch por `-2%` diario.
  - `after_trade_closed` dispara el kill switch por 3 pérdidas seguidas.
  - `after_trade_closed` resetea `consecutive_losses` tras un trade
    ganador.
  - `reconcile_with_exchange`: caso match (no posición), caso match
    (misma posición), caso mismatch (tamaños distintos) → `sys.exit(1)`,
    caso falla de red → `sys.exit(1)`.
- `tests/test_risk.py`:
  - `open_position` descuenta el fee de entrada de `pnl_today`.
  - `apply_partial_close` calcula PnL bruto, descuenta fee, acredita neto
    a `pnl_today` y a `pos.realized_pnl`, reduce `pos.size` correctamente.
  - `close_position` acumula `pos.realized_pnl` (entrada + parcial +
    final) y ese es el valor que llega a `after_trade_closed`.
  - Caso TP1 + luego stop a breakeven en la porción remanente → la
    clasificación ganador/perdedor para `consecutive_losses` usa el signo
    de `pos.realized_pnl` total (entrada + parcial + final), no el signo
    de la última pierna por sí sola.

Se agrega `pytest>=8.0.0` a un nuevo `requirements-dev.txt` (no se mezcla
con `requirements.txt` de runtime).
