# Notificaciones por Telegram — diseño

Fecha: 2026-06-19

## 1. Resumen y objetivo

El bot corre desatendido. Hoy la única forma de saber qué está haciendo es
mirar los logs o `safety_state.json` a mano. Este diseño agrega avisos por
Telegram para los eventos que importan en tiempo real:

- Apertura de posición.
- Cierre final de un trade (no los cierres parciales de TP1).
- Activación del kill switch (pérdida diaria o racha de pérdidas).
- Resumen al cierre de cada día UTC.

**Alcance:** solo el bot en vivo (`main.py: run()`), en cualquiera de los dos
modos (`PAPER_MODE=true` o `false`) — paper mode sigue corriendo contra datos
reales en tiempo real, así que es la forma natural de probar este módulo
antes de ir a producción. `backtest.py` no se toca: reproduce meses de
historia en segundos, mandar un mensaje por cada evento sería spam puro.

**No-goals:**
- Reintentos o persistencia de notificaciones entre reinicios del bot — son
  informativas, no forman parte de la lógica de seguridad (eso ya lo cubre
  `safety_state.json`).
- Otros canales (email, Discord, etc.) — se deja la puerta abierta a nivel de
  diseño (ver sección 2) pero no se implementa nada más que Telegram.
- Comandos entrantes desde Telegram (pausar el bot, pedir estado on-demand,
  etc.) — solo salida, el bot no escucha mensajes.

## 2. Arquitectura (`notifications.py`, nuevo módulo)

```python
class TelegramNotifier:
    def __init__(self, bot_token: Optional[str], chat_id: Optional[str]) -> None:
        """Si falta bot_token o chat_id, queda deshabilitado: loguea un aviso
        una vez y todos los notify_* se vuelven no-op. El resto del bot
        funciona idéntico sin Telegram configurado."""

    def notify_trade_opened(self, trade: dict) -> None: ...
    def notify_trade_closed(self, trade: dict) -> None: ...
    def notify_kill_switch(self, reason: str, pnl_today: float, consecutive_losses: int) -> None: ...
    def notify_daily_summary(self, summary: dict) -> None: ...

    async def run(self) -> None:
        """Worker de fondo: vacía la cola interna y manda cada mensaje a la
        API de Telegram, uno por vez, en el orden en que se encolaron."""
```

Cada `notify_*` formatea el texto del mensaje y lo mete en una
`asyncio.Queue[str]` interna (`_enqueue`). `run()` es la única corutina que
lee de esa cola y manda los mensajes — por eso quedan garantizados en el
orden en que ocurrieron los eventos, aunque la llamada HTTP a Telegram tarde
distinto de una vez a otra (con tareas sueltas tipo `create_task` por
mensaje, eso no estaría garantizado).

El envío real (`_send`) hace un POST a
`https://api.telegram.org/bot<token>/sendMessage` usando `urllib.request` de
la librería estándar, corrido en un hilo aparte vía `asyncio.to_thread` para
no bloquear el event loop del bot mientras espera la respuesta de Telegram.
Cero dependencias nuevas en `requirements.txt`.

`run()` se agrega al `asyncio.gather(...)` que ya arranca `feed.connect()` y
`macro.run()` en `main.py: run()` — mismo patrón de tareas concurrentes que
ya usa el bot.

## 3. Puntos de enganche

Ninguno de los tres hooks nuevos cambia el comportamiento existente cuando
no se pasa un callback (todos son `Optional`, default `None`) — `backtest.py`
y los tests existentes no se modifican.

**a) Apertura — `execution.py`:** nuevo parámetro
`on_trade_opened: Optional[Callable[[dict], None]] = None` en
`ExecutionEngine.__init__`, guardado igual que `on_trade_closed`. En
`enter()`, después de que `open_position(...)` deja `state.position` seteado,
se llama con:

```python
{
    "side": pos.side, "entry_price": pos.entry_price, "size": pos.size,
    "stop_loss": pos.stop_loss, "tp1": pos.tp1,
}
```

**b) Cierre final — `execution.py`:** se reusa el `on_trade_closed` que ya
existe (dispara en `exit()` y `partial_exit()` con el mismo dict de siempre,
incluyendo `is_partial`). No se toca `execution.py` para esto — la decisión
de "solo notificar el cierre final, no los parciales" vive en el wrapper de
`main.py` (sección 3d), filtrando por `trade["is_partial"]`.

**c) Resumen diario — `safety.py`:** nuevo parámetro
`on_day_rolled_over: Optional[Callable[[dict], None]] = None` en
`maybe_reset_daily`. Se llama **antes** de resetear los contadores, y
**solo** si `state.last_reset_date is not None` (o sea: nunca en el primer
arranque del bot, donde no hay "día anterior" que resumir):

```python
{
    "date": state.last_reset_date, "trades_today": state.trades_today,
    "pnl_today": state.pnl_today, "consecutive_losses": state.consecutive_losses,
    "kill_switch_active": state.kill_switch_active,
}
```

**d) Kill switch — sin tocar `safety.py`/`risk.py`:** `after_trade_closed`
(llamado internamente por `risk.close_position`/`apply_partial_close`, antes
de que `execution.py` dispare `on_trade_closed`) ya deja `state.kill_switch_active`
actualizado para el momento en que el `on_trade_closed` de `main.py` se
ejecuta. El wrapper de `main.py` compara contra una variable local
(`_kill_switch_notified`, reseteada a `False` en cada `on_day_rolled_over`)
y manda el aviso la primera vez que ve la transición `False → True` en el
día. Una vez activo, el kill switch se mantiene en `True` hasta que
`maybe_reset_daily` lo resetea al otro día UTC — nunca vuelve a `False`
dentro del mismo día — así que esta comparación simple no duplica avisos.

**Cableado en `main.py: run()`:**

```python
notifier = TelegramNotifier(os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"))
kill_switch_notified = False

def _on_trade_closed(trade: dict) -> None:
    nonlocal kill_switch_notified
    if not trade["is_partial"]:
        notifier.notify_trade_closed(trade)
    if state.kill_switch_active and not kill_switch_notified:
        notifier.notify_kill_switch(...)
        kill_switch_notified = True

def _on_day_rolled_over(summary: dict) -> None:
    nonlocal kill_switch_notified
    notifier.notify_daily_summary(summary)
    kill_switch_notified = False

engine = ExecutionEngine(state, on_trade_closed=_on_trade_closed, on_trade_opened=notifier.notify_trade_opened)
...
safety.maybe_reset_daily(state, engine.exchange, on_day_rolled_over=_on_day_rolled_over)
...
await asyncio.gather(feed.connect(), macro.run(), notifier.run())
```

## 4. Formato de los mensajes

Texto plano con emoji como marca visual rápida, en español:

```
🟢 Abrió LONG BTC/USDT
Entrada: $61,903.50
Tamaño: 0.01230 BTC
Stop: $61,822.00  |  TP1: $62,066.00

🔴 Cerró SHORT BTC/USDT
Salida: $62,010.00  |  motivo: time_exit
P&L neto: +$48.20  |  fees: $1.10

⚠️ KILL SWITCH ACTIVADO
Motivo: pérdida diaria (-2.1%)
P&L hoy: -$210.00  |  racha: 3 pérdidas seguidas
No se abren posiciones nuevas hasta el próximo día UTC.

📊 Resumen del día 2026-06-19
Trades: 4  |  P&L neto: +$112.30
Racha de pérdidas: 0  |  Kill switch: no se activó
```

## 5. Manejo de errores

- **Sin credenciales** (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` vacíos o no
  seteados): `TelegramNotifier` queda deshabilitado. Un log INFO al
  construirse, cero comportamiento adicional — el bot corre exactamente
  igual que hoy.
- **Falla de red o error de la API de Telegram al mandar:** se captura
  dentro de `_send`, se loguea como WARNING con el detalle, y el worker
  sigue con el siguiente mensaje de la cola. Nunca se propaga la excepción —
  un Telegram caído no puede tirar abajo el bot ni bloquear otra tarea del
  `asyncio.gather`.
- **Sin reintentos ni cola persistente:** ver no-goals (sección 1).

## 6. Setup de Telegram (manual, una sola vez, antes de tener el bot configurado)

1. Hablar con `@BotFather` en Telegram → `/newbot` → da un **bot token**.
2. Mandarle cualquier mensaje al bot nuevo (para que tenga con quién hablar).
3. Abrir `https://api.telegram.org/bot<TOKEN>/getUpdates` en el navegador →
   ahí aparece el **chat_id** (`"chat":{"id": ...}`).
4. Agregar `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` a `.env` (y a
   `.env.example`, sin valores reales, mismo patrón que
   `BINANCE_API_KEY`/`BINANCE_SECRET`).

## 7. Testing

Mismo patrón que el resto del proyecto: pytest, sin mockear la función bajo
prueba, solo la I/O real (la llamada HTTP a Telegram).

- `tests/test_notifications.py`: `TelegramNotifier` recibe una función de
  envío inyectable (mismo patrón que `_FakeExchange` en `test_safety.py`)
  para los tests — verifica el formato de cada tipo de mensaje, que el modo
  deshabilitado (sin token/chat_id) no encola nada, que `run()` vacía la cola
  en orden FIFO, y que un envío que tira excepción no frena los mensajes
  siguientes.
- `tests/test_execution.py`: se extiende con tests para `on_trade_opened` —
  se llama con el dict correcto al abrir; si es `None` (default), no rompe
  nada.
- `tests/test_safety.py`: se extiende con tests para `on_day_rolled_over` —
  se llama con las stats del día anterior antes de resetear los contadores;
  NO se llama en el primer arranque del bot (`state.last_reset_date is None`).

No se agrega ninguna dependencia nueva (`urllib` es de la librería estándar).
