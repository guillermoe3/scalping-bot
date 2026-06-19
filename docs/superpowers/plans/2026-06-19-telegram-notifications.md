# Telegram Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send Telegram messages for trade opens, full trade closes, kill-switch activation, and an end-of-day summary, without ever blocking or risking the live trading loop.

**Architecture:** Per `docs/superpowers/specs/2026-06-19-telegram-notifications-design.md`. A new `notifications.py` module owns a `TelegramNotifier` class that formats messages and pushes them onto an internal `asyncio.Queue`; a single background worker (`TelegramNotifier.run()`, gathered alongside `feed.connect()`/`macro.run()` in `main.py`) drains the queue and sends to the Telegram Bot API via stdlib `urllib` in a thread, so a slow/down Telegram never blocks the bot. `ExecutionEngine` gains an optional `on_trade_opened` hook (mirroring the existing `on_trade_closed`); `safety.maybe_reset_daily` gains an optional `on_day_rolled_over` hook. A small `make_notification_handlers` factory in `notifications.py` decides *when* to fire (full closes only, one-shot kill-switch alert per day) so that decision logic is unit-testable without touching `main.py`'s untested async entrypoint.

**Tech Stack:** Python 3.12, stdlib `asyncio`/`urllib`, pytest. No new dependencies.

**Manual precondition (not a coding task):** the user creates a Telegram bot via `@BotFather` and gets a chat ID, then sets `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` in their own `.env` — steps are in the design spec §6. Task 1 below only adds the (valueless) example entries to `.env.example`.

## Global Constraints

- Run tests with `.venv/bin/pytest` from the repo root (`/home/guille/dev/scalping-bot`).
- Test files live at `tests/test_<module>.py`, no `__init__.py`.
- Never mock the function under test. The only I/O boundary faked is the actual Telegram HTTP call — via an injectable `send_fn` constructor param on `TelegramNotifier` (same pattern as `_FakeExchange` in `tests/test_safety.py`) or by monkeypatching `urllib.request.urlopen` directly for the one test that checks the real HTTP-building code.
- Do not add new dependencies — use stdlib `urllib` for the Telegram HTTP call.
- Do not run `python -c "..."` inline scripts — this sandbox blocks them (Falco rule, "encoded payload execution"). Use `pytest` for all verification, including `--collect-only` when you only need to confirm a module imports cleanly.
- Baseline before this plan: confirmed in Task 0 at **189** passing tests. Every later task's "run full suite" step expects 189 plus that task's own new tests, cumulative — never fewer.
- Commit after every task.

---

### Task 0: Confirm the baseline

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite and confirm the baseline count**

Run: `.venv/bin/pytest -q`
Expected: `189 passed`.

---

### Task 1: `TelegramNotifier` — message formatting, disabled mode, queue

**Files:**
- Create: `notifications.py`
- Create: `tests/test_notifications.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `TelegramNotifier(bot_token: Optional[str], chat_id: Optional[str], send_fn: Optional[Callable[[str], None]] = None)`, with methods `.notify_trade_opened(trade: dict)`, `.notify_trade_closed(trade: dict)`, `.notify_kill_switch(reason: str, pnl_today: float, consecutive_losses: int)`, `.notify_daily_summary(summary: dict)`, and an internal `._queue: asyncio.Queue[str]`. Tasks 2, 3, 6 depend on this exact signature.

- [ ] **Step 1: Write the failing test file**

Create `tests/test_notifications.py`:

```python
from notifications import TelegramNotifier
from state import Side


def test_disabled_when_token_missing():
    notifier = TelegramNotifier(None, "chat123")

    notifier.notify_trade_opened({
        "side": Side.LONG, "entry_price": 61903.5, "size": 0.0123,
        "stop_loss": 61822.0, "tp1": 62066.0,
    })

    assert notifier._queue.empty()


def test_disabled_when_chat_id_missing():
    notifier = TelegramNotifier("token123", None)

    notifier.notify_trade_opened({
        "side": Side.LONG, "entry_price": 61903.5, "size": 0.0123,
        "stop_loss": 61822.0, "tp1": 62066.0,
    })

    assert notifier._queue.empty()


def test_notify_trade_opened_formats_side_price_size_and_levels():
    notifier = TelegramNotifier("token123", "chat123")

    notifier.notify_trade_opened({
        "side": Side.LONG, "entry_price": 61903.5, "size": 0.0123,
        "stop_loss": 61822.0, "tp1": 62066.0,
    })

    text = notifier._queue.get_nowait()
    assert text == (
        "🟢 Abrió LONG BTC/USDT\n"
        "Entrada: $61,903.50\n"
        "Tamaño: 0.01230 BTC\n"
        "Stop: $61,822.00  |  TP1: $62,066.00"
    )


def test_notify_trade_closed_formats_exit_reason_and_net_pnl():
    notifier = TelegramNotifier("token123", "chat123")

    notifier.notify_trade_closed({
        "side": Side.SHORT, "exit_price": 62010.0, "reason": "time_exit",
        "total_trade_net": 48.2, "fees_paid": 1.1,
    })

    text = notifier._queue.get_nowait()
    assert text == (
        "🔴 Cerró SHORT BTC/USDT\n"
        "Salida: $62,010.00  |  motivo: time_exit\n"
        "P&L neto: +$48.20  |  fees: $1.10"
    )


def test_notify_trade_closed_formats_negative_pnl_with_minus_sign():
    notifier = TelegramNotifier("token123", "chat123")

    notifier.notify_trade_closed({
        "side": Side.LONG, "exit_price": 61700.0, "reason": "stop_loss",
        "total_trade_net": -32.5, "fees_paid": 0.9,
    })

    text = notifier._queue.get_nowait()
    assert "P&L neto: -$32.50" in text


def test_notify_kill_switch_formats_reason_pnl_and_streak():
    notifier = TelegramNotifier("token123", "chat123")

    notifier.notify_kill_switch(
        reason="pérdida diaria (-2.1%)", pnl_today=-210.0, consecutive_losses=3,
    )

    text = notifier._queue.get_nowait()
    assert text == (
        "⚠️ KILL SWITCH ACTIVADO\n"
        "Motivo: pérdida diaria (-2.1%)\n"
        "P&L hoy: -$210.00  |  racha: 3 pérdidas seguidas\n"
        "No se abren posiciones nuevas hasta el próximo día UTC."
    )


def test_notify_daily_summary_formats_stats_when_kill_switch_did_not_fire():
    notifier = TelegramNotifier("token123", "chat123")

    notifier.notify_daily_summary({
        "date": "2026-06-19", "trades_today": 4, "pnl_today": 112.3,
        "consecutive_losses": 0, "kill_switch_active": False,
    })

    text = notifier._queue.get_nowait()
    assert text == (
        "📊 Resumen del día 2026-06-19\n"
        "Trades: 4  |  P&L neto: +$112.30\n"
        "Racha de pérdidas: 0  |  Kill switch: no se activó"
    )


def test_notify_daily_summary_reports_kill_switch_activated():
    notifier = TelegramNotifier("token123", "chat123")

    notifier.notify_daily_summary({
        "date": "2026-06-19", "trades_today": 2, "pnl_today": -210.0,
        "consecutive_losses": 3, "kill_switch_active": True,
    })

    text = notifier._queue.get_nowait()
    assert "Kill switch: sí" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_notifications.py -v`
Expected: `ModuleNotFoundError: No module named 'notifications'` (collection error — `notifications.py` doesn't exist yet).

- [ ] **Step 3: Write the minimal implementation**

Create `notifications.py`:

```python
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def _fmt_signed(amount: float) -> str:
    sign = "+" if amount >= 0 else "-"
    return f"{sign}${abs(amount):,.2f}"


class TelegramNotifier:
    """Formats and queues Telegram messages for trade/kill-switch/daily-summary
    events. Disabled (silent no-op) when bot_token or chat_id is missing —
    the live bot runs identically with or without Telegram configured."""

    def __init__(
        self,
        bot_token: Optional[str],
        chat_id: Optional[str],
        send_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._enabled = bool(bot_token) and bool(chat_id)
        self._send_fn = send_fn
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        if not self._enabled:
            logger.info(
                "Telegram notifications disabled — set TELEGRAM_BOT_TOKEN/"
                "TELEGRAM_CHAT_ID to enable"
            )

    def notify_trade_opened(self, trade: dict) -> None:
        text = (
            f"🟢 Abrió {trade['side'].value.upper()} BTC/USDT\n"
            f"Entrada: ${trade['entry_price']:,.2f}\n"
            f"Tamaño: {trade['size']:.5f} BTC\n"
            f"Stop: ${trade['stop_loss']:,.2f}  |  TP1: ${trade['tp1']:,.2f}"
        )
        self._enqueue(text)

    def notify_trade_closed(self, trade: dict) -> None:
        text = (
            f"🔴 Cerró {trade['side'].value.upper()} BTC/USDT\n"
            f"Salida: ${trade['exit_price']:,.2f}  |  motivo: {trade['reason']}\n"
            f"P&L neto: {_fmt_signed(trade['total_trade_net'])}  |  "
            f"fees: ${trade['fees_paid']:,.2f}"
        )
        self._enqueue(text)

    def notify_kill_switch(self, reason: str, pnl_today: float, consecutive_losses: int) -> None:
        text = (
            "⚠️ KILL SWITCH ACTIVADO\n"
            f"Motivo: {reason}\n"
            f"P&L hoy: {_fmt_signed(pnl_today)}  |  "
            f"racha: {consecutive_losses} pérdidas seguidas\n"
            "No se abren posiciones nuevas hasta el próximo día UTC."
        )
        self._enqueue(text)

    def notify_daily_summary(self, summary: dict) -> None:
        kill_switch_text = "sí" if summary["kill_switch_active"] else "no se activó"
        text = (
            f"📊 Resumen del día {summary['date']}\n"
            f"Trades: {summary['trades_today']}  |  "
            f"P&L neto: {_fmt_signed(summary['pnl_today'])}\n"
            f"Racha de pérdidas: {summary['consecutive_losses']}  |  "
            f"Kill switch: {kill_switch_text}"
        )
        self._enqueue(text)

    def _enqueue(self, text: str) -> None:
        if not self._enabled:
            return
        self._queue.put_nowait(text)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_notifications.py -v`
Expected: 8 passed.

- [ ] **Step 5: Add the env vars to `.env.example`**

Modify `.env.example`, append at the end:

```
# Optional — enables Telegram notifications for trade open/close, kill
# switch activation, and the end-of-day summary. Leave unset to disable;
# the bot runs identically either way. See docs/superpowers/specs/
# 2026-06-19-telegram-notifications-design.md section 6 for setup steps.
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: `197 passed` (189 baseline + 8 new).

- [ ] **Step 7: Commit**

```bash
git add notifications.py tests/test_notifications.py .env.example
git commit -m "Add TelegramNotifier message formatting and disabled mode"
```

---

### Task 2: Background worker — `run()`, real send, error handling

**Files:**
- Modify: `notifications.py`
- Modify: `tests/test_notifications.py`

**Interfaces:**
- Consumes: `TelegramNotifier` from Task 1 (same file, same class).
- Produces: `TelegramNotifier.run() -> None` (async, runs forever — gathered as a task), `TelegramNotifier._send_via_http(text: str) -> None`. Task 6 depends on `run()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_notifications.py`:

```python
import asyncio
import contextlib


def test_run_sends_queued_messages_in_fifo_order():
    sent = []
    notifier = TelegramNotifier("token", "chat", send_fn=sent.append)
    notifier.notify_kill_switch(reason="racha de pérdidas", pnl_today=-10.0, consecutive_losses=1)
    notifier.notify_daily_summary({
        "date": "2026-06-19", "trades_today": 1, "pnl_today": -10.0,
        "consecutive_losses": 1, "kill_switch_active": True,
    })

    async def _run_and_wait():
        task = asyncio.create_task(notifier.run())
        for _ in range(100):
            if len(sent) >= 2:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(_run_and_wait())

    assert len(sent) == 2
    assert sent[0].startswith("⚠️ KILL SWITCH")
    assert sent[1].startswith("📊 Resumen")


def test_run_continues_after_a_failed_send():
    attempts = []

    def _flaky_send(text):
        attempts.append(text)
        if len(attempts) == 1:
            raise RuntimeError("network down")

    notifier = TelegramNotifier("token", "chat", send_fn=_flaky_send)
    notifier.notify_kill_switch(reason="racha de pérdidas", pnl_today=-10.0, consecutive_losses=1)
    notifier.notify_kill_switch(reason="racha de pérdidas", pnl_today=-20.0, consecutive_losses=2)

    async def _run_and_wait():
        task = asyncio.create_task(notifier.run())
        for _ in range(100):
            if len(attempts) >= 2:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(_run_and_wait())

    assert len(attempts) == 2  # the failed first send did not block the second


def test_send_via_http_posts_chat_id_and_text(monkeypatch):
    import notifications as notifications_module

    captured = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"{}"

    def _fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["data"] = request.data
        return _FakeResponse()

    monkeypatch.setattr(notifications_module.urllib.request, "urlopen", _fake_urlopen)
    notifier = TelegramNotifier("tok123", "chat456")

    notifier._send_via_http("hola")

    assert captured["url"] == "https://api.telegram.org/bottok123/sendMessage"
    assert b"chat_id=chat456" in captured["data"]
    assert b"text=hola" in captured["data"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_notifications.py -v`
Expected: the 3 new tests fail — `run()`/`_send_via_http` don't exist yet (`AttributeError`).

- [ ] **Step 3: Write the minimal implementation**

In `notifications.py`, add imports at the top (after `from typing import Callable, Optional`):

```python
import urllib.parse
import urllib.request
```

Add a module-level constant right after `logger = logging.getLogger(__name__)`:

```python
_API_URL_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"
```

In `TelegramNotifier.__init__`, change:

```python
        self._send_fn = send_fn
```

to:

```python
        self._send_fn = send_fn or self._send_via_http
```

Add these two methods at the end of the class (after `_enqueue`):

```python
    async def run(self) -> None:
        """Background worker: drains the queue and sends messages one at a
        time, in FIFO order. A failed send is logged and skipped — never
        raises, never blocks the next queued message."""
        while True:
            text = await self._queue.get()
            try:
                await asyncio.to_thread(self._send_fn, text)
            except Exception:
                logger.warning("Failed to send Telegram notification", exc_info=True)

    def _send_via_http(self, text: str) -> None:
        url = _API_URL_TEMPLATE.format(token=self._bot_token)
        data = urllib.parse.urlencode({"chat_id": self._chat_id, "text": text}).encode()
        request = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_notifications.py -v`
Expected: 11 passed.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: `200 passed` (197 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add notifications.py tests/test_notifications.py
git commit -m "Add TelegramNotifier background worker and real HTTP send"
```

---

### Task 3: `make_notification_handlers` — when to fire, kill-switch debounce

**Files:**
- Modify: `notifications.py`
- Modify: `tests/test_notifications.py`

**Interfaces:**
- Consumes: `TelegramNotifier` from Tasks 1–2.
- Produces: `make_notification_handlers(notifier: TelegramNotifier, state: MarketState) -> Tuple[Callable[[dict], None], Callable[[dict], None]]`, returning `(on_trade_closed, on_day_rolled_over)`. Task 6 depends on this exact name and return shape.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_notifications.py`:

```python
from state import MarketState
from notifications import make_notification_handlers


def _full_close_trade(net: float) -> dict:
    return {
        "is_partial": False, "side": Side.LONG, "exit_price": 100.0,
        "reason": "time_exit", "total_trade_net": net, "fees_paid": 0.1,
    }


def _partial_close_trade() -> dict:
    return {
        "is_partial": True, "side": Side.LONG, "exit_price": 100.0,
        "reason": "tp1", "total_trade_net": None, "fees_paid": 0.1,
    }


def test_on_trade_closed_ignores_partial_closes():
    state = MarketState()
    notifier = TelegramNotifier("token", "chat")
    on_trade_closed, _ = make_notification_handlers(notifier, state)

    on_trade_closed(_partial_close_trade())

    assert notifier._queue.empty()


def test_on_trade_closed_notifies_full_closes():
    state = MarketState()
    notifier = TelegramNotifier("token", "chat")
    on_trade_closed, _ = make_notification_handlers(notifier, state)

    on_trade_closed(_full_close_trade(net=10.0))

    assert notifier._queue.qsize() == 1


def test_on_trade_closed_fires_kill_switch_alert_with_daily_loss_reason():
    state = MarketState()
    state.daily_starting_balance = 10_000.0
    state.pnl_today = -250.0  # -2.5%, breaches the -2% daily-loss threshold
    notifier = TelegramNotifier("token", "chat")
    on_trade_closed, _ = make_notification_handlers(notifier, state)
    state.kill_switch_active = True

    on_trade_closed(_full_close_trade(net=-10.0))

    assert notifier._queue.qsize() == 2  # trade-closed + kill-switch
    notifier._queue.get_nowait()
    second = notifier._queue.get_nowait()
    assert second.startswith("⚠️ KILL SWITCH")
    assert "Motivo: pérdida diaria (-2.5%)" in second


def test_on_trade_closed_fires_kill_switch_alert_with_streak_reason_when_balance_unset():
    state = MarketState()  # daily_starting_balance stays None — not a balance-driven trip
    notifier = TelegramNotifier("token", "chat")
    on_trade_closed, _ = make_notification_handlers(notifier, state)
    state.kill_switch_active = True
    state.consecutive_losses = 3

    on_trade_closed(_full_close_trade(net=-10.0))

    notifier._queue.get_nowait()
    second = notifier._queue.get_nowait()
    assert "Motivo: racha de pérdidas" in second


def test_on_trade_closed_only_fires_kill_switch_alert_once_on_transition():
    state = MarketState()
    notifier = TelegramNotifier("token", "chat")
    on_trade_closed, _ = make_notification_handlers(notifier, state)
    state.kill_switch_active = True

    on_trade_closed(_full_close_trade(net=-10.0))
    assert notifier._queue.qsize() == 2  # trade-closed + kill-switch

    notifier._queue.get_nowait()
    notifier._queue.get_nowait()
    on_trade_closed(_full_close_trade(net=-5.0))  # still active, already notified
    assert notifier._queue.qsize() == 1  # only the trade-closed message this time


def test_on_day_rolled_over_sends_summary_and_rearms_kill_switch_alert():
    state = MarketState()
    notifier = TelegramNotifier("token", "chat")
    on_trade_closed, on_day_rolled_over = make_notification_handlers(notifier, state)
    state.kill_switch_active = True
    on_trade_closed(_full_close_trade(net=-10.0))  # fires the kill-switch alert once
    while not notifier._queue.empty():
        notifier._queue.get_nowait()

    on_day_rolled_over({
        "date": "2026-06-18", "trades_today": 1, "pnl_today": -10.0,
        "consecutive_losses": 1, "kill_switch_active": True,
    })
    summary_msg = notifier._queue.get_nowait()
    assert summary_msg.startswith("📊 Resumen")
    assert notifier._queue.empty()

    on_trade_closed(_full_close_trade(net=-5.0))  # kill switch still active next day
    assert notifier._queue.qsize() == 2  # fires again — was re-armed by the rollover
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_notifications.py -v`
Expected: the 6 new tests fail — `ImportError: cannot import name 'make_notification_handlers'`.

- [ ] **Step 3: Write the minimal implementation**

In `notifications.py`, change the import line:

```python
from typing import Callable, Optional
```

to:

```python
from typing import Callable, Optional, Tuple

from config import KILL_SWITCH_DAILY_LOSS_PCT
from state import MarketState
```

Add this function at the end of the file:

```python
def _kill_switch_reason(state: MarketState) -> str:
    """Re-derives why the kill switch tripped from already-available state —
    safety.after_trade_closed computes the same daily-loss/streak booleans
    internally but doesn't persist them, so this recomputes the daily-loss
    side of that check; consecutive_losses is shown either way in the body."""
    balance = state.daily_starting_balance
    if balance and state.pnl_today <= -KILL_SWITCH_DAILY_LOSS_PCT * balance:
        pct = (state.pnl_today / balance) * 100
        return f"pérdida diaria ({pct:.1f}%)"
    return "racha de pérdidas"


def make_notification_handlers(
    notifier: TelegramNotifier, state: MarketState
) -> Tuple[Callable[[dict], None], Callable[[dict], None]]:
    """Returns (on_trade_closed, on_day_rolled_over) wired for main.py.

    on_trade_closed notifies on full closes only (not TP1 partials) and
    fires a one-shot kill-switch alert the first time it sees the switch
    flip on during the day. on_day_rolled_over sends the daily summary and
    re-arms the kill-switch alert for the new day."""
    kill_switch_notified = [False]

    def on_trade_closed(trade: dict) -> None:
        if not trade["is_partial"]:
            notifier.notify_trade_closed(trade)
        if state.kill_switch_active and not kill_switch_notified[0]:
            notifier.notify_kill_switch(
                _kill_switch_reason(state), state.pnl_today, state.consecutive_losses,
            )
            kill_switch_notified[0] = True

    def on_day_rolled_over(summary: dict) -> None:
        notifier.notify_daily_summary(summary)
        kill_switch_notified[0] = False

    return on_trade_closed, on_day_rolled_over
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_notifications.py -v`
Expected: 17 passed.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: `206 passed` (200 + 6 new).

- [ ] **Step 6: Commit**

```bash
git add notifications.py tests/test_notifications.py
git commit -m "Add make_notification_handlers: full-close filter and kill-switch debounce"
```

---

### Task 4: `ExecutionEngine.on_trade_opened` hook

**Files:**
- Modify: `execution.py:30-35` (constructor), `execution.py:55-63` (`enter()`)
- Modify: `tests/test_execution.py`

**Interfaces:**
- Produces: `ExecutionEngine(state, on_trade_closed=None, on_trade_opened=None)` — `on_trade_opened` called with `{"side": Side, "entry_price": float, "size": float, "stop_loss": float, "tp1": float}` right after a position opens, in both paper and live mode. Task 6 depends on this parameter name.
- Independent of Tasks 1–3 — touches a different file, no shared state.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_execution.py`:

```python
def test_enter_calls_on_trade_opened_hook_with_position_details():
    state = _state_with_book(bid=99.0, ask=101.0)
    captured = []
    engine = ExecutionEngine(state, on_trade_opened=captured.append)

    asyncio.run(engine.enter(Side.LONG))

    assert len(captured) == 1
    record = captured[0]
    assert record["side"] == Side.LONG
    assert record["entry_price"] == pytest.approx(101.0)
    assert record["size"] == pytest.approx(state.position.size)
    assert record["stop_loss"] == pytest.approx(state.position.stop_loss)
    assert record["tp1"] == pytest.approx(state.position.tp1)


def test_on_trade_opened_defaults_to_none_and_does_not_raise():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)  # no on_trade_opened passed

    asyncio.run(engine.enter(Side.LONG))  # must not raise


def test_enter_does_not_call_on_trade_opened_when_book_not_yet_received():
    state = MarketState()  # last_bid/last_ask default to 0.0
    state.last_price = 100.0
    captured = []
    engine = ExecutionEngine(state, on_trade_opened=captured.append)

    asyncio.run(engine.enter(Side.LONG))

    assert captured == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_execution.py -v`
Expected: `TypeError: ExecutionEngine.__init__() got an unexpected keyword argument 'on_trade_opened'`.

- [ ] **Step 3: Write the minimal implementation**

In `execution.py`, change the constructor (currently lines 30–35):

```python
    def __init__(self, state: MarketState, on_trade_closed: Optional[Callable[[dict], None]] = None) -> None:
        self.state = state
        self._exchange = None
        self._on_trade_closed = on_trade_closed
        if not PAPER_MODE:
            self._init_exchange()
```

to:

```python
    def __init__(
        self,
        state: MarketState,
        on_trade_closed: Optional[Callable[[dict], None]] = None,
        on_trade_opened: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.state = state
        self._exchange = None
        self._on_trade_closed = on_trade_closed
        self._on_trade_opened = on_trade_opened
        if not PAPER_MODE:
            self._init_exchange()
```

In `enter()` (currently lines 55–63):

```python
    async def enter(self, side: Side) -> bool:
        if self.state.last_bid <= 0 or self.state.last_ask <= 0:
            return False

        fill_price = self.state.last_ask if side == Side.LONG else self.state.last_bid
        open_position(self.state, side, fill_price)

        if PAPER_MODE or self._exchange is None:
            return True
```

to:

```python
    async def enter(self, side: Side) -> bool:
        if self.state.last_bid <= 0 or self.state.last_ask <= 0:
            return False

        fill_price = self.state.last_ask if side == Side.LONG else self.state.last_bid
        open_position(self.state, side, fill_price)

        opened = self.state.position
        if self._on_trade_opened is not None and opened is not None:
            self._on_trade_opened({
                "side": opened.side, "entry_price": opened.entry_price,
                "size": opened.size, "stop_loss": opened.stop_loss, "tp1": opened.tp1,
            })

        if PAPER_MODE or self._exchange is None:
            return True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_execution.py -v`
Expected: all passed (existing + 3 new).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: `209 passed` (206 + 3 new — runs cumulatively on top of whichever of Tasks 1–3 already landed; if this task is done before them, expect `192` instead and reconcile when the other tasks land).

- [ ] **Step 6: Commit**

```bash
git add execution.py tests/test_execution.py
git commit -m "Add ExecutionEngine.on_trade_opened hook"
```

---

### Task 5: `safety.maybe_reset_daily` — `on_day_rolled_over` hook

**Files:**
- Modify: `safety.py:7` (import), `safety.py:38-53` (`maybe_reset_daily`)
- Modify: `tests/test_safety.py`

**Interfaces:**
- Produces: `safety.maybe_reset_daily(state, exchange=None, on_day_rolled_over=None)` — called with `{"date": str, "trades_today": int, "pnl_today": float, "consecutive_losses": int, "kill_switch_active": bool}` right before the day's counters reset; never called on the bot's first-ever reset. Task 6 depends on this parameter name.
- Independent of Tasks 1–4 — touches a different file, no shared state.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_safety.py`:

```python
def test_maybe_reset_daily_calls_on_day_rolled_over_with_previous_day_stats():
    state = MarketState()
    state.last_reset_date = "2020-01-01"
    state.pnl_today = -50.0
    state.trades_today = 4
    state.consecutive_losses = 2
    state.kill_switch_active = True
    captured = []

    safety.maybe_reset_daily(state, on_day_rolled_over=captured.append)

    assert len(captured) == 1
    summary = captured[0]
    assert summary["date"] == "2020-01-01"
    assert summary["trades_today"] == 4
    assert summary["pnl_today"] == pytest.approx(-50.0)
    assert summary["consecutive_losses"] == 2
    assert summary["kill_switch_active"] is True


def test_maybe_reset_daily_does_not_call_on_day_rolled_over_on_first_ever_reset():
    state = MarketState()  # last_reset_date is None — no previous day to summarize
    captured = []

    safety.maybe_reset_daily(state, on_day_rolled_over=captured.append)

    assert captured == []


def test_maybe_reset_daily_does_not_call_on_day_rolled_over_when_already_reset_today():
    state = MarketState()
    state.last_reset_date = safety._today_utc()
    state.daily_starting_balance = 10_000.0
    captured = []

    safety.maybe_reset_daily(state, on_day_rolled_over=captured.append)

    assert captured == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_safety.py -v`
Expected: `TypeError: maybe_reset_daily() got an unexpected keyword argument 'on_day_rolled_over'`.

- [ ] **Step 3: Write the minimal implementation**

In `safety.py`, change the import (currently line 7):

```python
from typing import Optional
```

to:

```python
from typing import Callable, Optional
```

Change `maybe_reset_daily` (currently lines 38–53):

```python
def maybe_reset_daily(state: MarketState, exchange=None) -> None:
    """Reset daily counters and the kill switch when the UTC date has rolled
    over, and (re)resolve the daily starting balance used for position
    sizing and the kill switch threshold."""
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

to:

```python
def maybe_reset_daily(
    state: MarketState,
    exchange=None,
    on_day_rolled_over: Optional[Callable[[dict], None]] = None,
) -> None:
    """Reset daily counters and the kill switch when the UTC date has rolled
    over, and (re)resolve the daily starting balance used for position
    sizing and the kill switch threshold. on_day_rolled_over, if given, is
    called with the previous day's stats right before they're reset — it is
    never called on the bot's very first-ever reset (no previous day to
    summarize)."""
    today = _today_utc()
    if state.last_reset_date == today and state.daily_starting_balance is not None:
        return

    if (
        on_day_rolled_over is not None
        and state.last_reset_date is not None
        and state.last_reset_date != today
    ):
        on_day_rolled_over({
            "date": state.last_reset_date,
            "trades_today": state.trades_today,
            "pnl_today": state.pnl_today,
            "consecutive_losses": state.consecutive_losses,
            "kill_switch_active": state.kill_switch_active,
        })

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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_safety.py -v`
Expected: all passed (existing + 3 new).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: cumulative count including this task's 3 new tests (see note in Task 4 Step 5 about ordering across Tasks 1–5).

- [ ] **Step 6: Commit**

```bash
git add safety.py tests/test_safety.py
git commit -m "Add safety.maybe_reset_daily on_day_rolled_over hook"
```

---

### Task 6: Wire it all together in `main.py`

**Files:**
- Modify: `main.py:1-19` (imports), `main.py:113-133` (`run()`)

**Interfaces:**
- Consumes: `TelegramNotifier` and `make_notification_handlers` (Tasks 1–3), `ExecutionEngine(..., on_trade_opened=...)` (Task 4), `safety.maybe_reset_daily(..., on_day_rolled_over=...)` (Task 5).
- Produces: nothing new for later tasks — this is the final integration point.
- **No new automated test.** `main.py: run()` is the live entrypoint (real websocket + real Telegram network calls via `feed.connect()`/`macro.run()`/`notifier.run()`) and has never had test coverage — only `wire_strategy` (a separate function) is tested, in `tests/test_main.py`. Verification here is: the full suite stays green, and `pytest --collect-only` proves the new import doesn't break module loading.

- [ ] **Step 1: Add the import**

In `main.py`, after the existing `import safety` line (line 17), add:

```python
from notifications import TelegramNotifier, make_notification_handlers
```

- [ ] **Step 2: Wire the notifier into `run()`**

Replace `run()` (currently lines 113–133):

```python
async def run() -> None:
    state = MarketState()
    safety.load_into_state(state)

    feed = DataFeed(state)
    engine = ExecutionEngine(state)
    macro = MacroFilter(state)

    if not PAPER_MODE:
        safety.reconcile_with_exchange(state, engine.exchange)
    safety.maybe_reset_daily(state, engine.exchange)

    wire_strategy(state, feed, engine)

    mode = "PAPER" if os.getenv("PAPER_MODE", "true").lower() == "true" else "LIVE"
    logger.info("BTC Scalping Bot starting — mode=%s", mode)

    await asyncio.gather(
        feed.connect(),
        macro.run(),
    )
```

with:

```python
async def run() -> None:
    state = MarketState()
    safety.load_into_state(state)

    notifier = TelegramNotifier(os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"))
    on_trade_closed, on_day_rolled_over = make_notification_handlers(notifier, state)

    feed = DataFeed(state)
    engine = ExecutionEngine(
        state, on_trade_closed=on_trade_closed, on_trade_opened=notifier.notify_trade_opened,
    )
    macro = MacroFilter(state)

    if not PAPER_MODE:
        safety.reconcile_with_exchange(state, engine.exchange)
    safety.maybe_reset_daily(state, engine.exchange, on_day_rolled_over=on_day_rolled_over)

    wire_strategy(state, feed, engine)

    mode = "PAPER" if os.getenv("PAPER_MODE", "true").lower() == "true" else "LIVE"
    logger.info("BTC Scalping Bot starting — mode=%s", mode)

    await asyncio.gather(
        feed.connect(),
        macro.run(),
        notifier.run(),
    )
```

- [ ] **Step 3: Verify the module imports cleanly**

Run: `.venv/bin/pytest --collect-only -q`
Expected: collection succeeds, no `ImportError`/`SyntaxError`, ends with `N tests collected` and no errors.

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: `212 passed` (189 baseline + 8 + 3 + 6 + 3 + 3 from Tasks 1–5).

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "Wire TelegramNotifier into the live bot's trade/kill-switch/daily-summary events"
```

---

## Manual verification (not automated, do once after Task 6)

1. Set up a real Telegram bot per the design spec §6, put the token/chat ID in your real `.env`.
2. Run the bot in paper mode (`PAPER_MODE=true`) against live data: `.venv/bin/python main.py`.
3. Confirm a Telegram message arrives the next time the bot opens a paper position, and another when it closes.
4. This is a real-money-adjacent code path only in the sense that it shares wiring with `ExecutionEngine`/`safety.py` — it does not place orders or touch `safety_state.json` differently than before. Still, don't skip this manual check before relying on the notifications during actual live trading.
