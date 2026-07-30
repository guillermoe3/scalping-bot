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


def test_on_trade_closed_fires_kill_switch_alert_with_daily_loss_reason_when_balance_unset():
    state = MarketState()  # daily_starting_balance stays None
    state.pnl_today = -250.0  # -2.5% of the PAPER_BALANCE_USDT (10,000) fallback, breaches -2%
    state.consecutive_losses = 1  # below the streak threshold — isolates the daily-loss path
    notifier = TelegramNotifier("token", "chat")
    on_trade_closed, _ = make_notification_handlers(notifier, state)
    state.kill_switch_active = True

    on_trade_closed(_full_close_trade(net=-10.0))

    notifier._queue.get_nowait()
    second = notifier._queue.get_nowait()
    assert "Motivo: pérdida diaria (-2.5%)" in second


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


def test_notify_rebalance_formats_side_amount_price_fee_and_exposure():
    notifier = TelegramNotifier("token123", "chat123")

    notifier.notify_rebalance({
        "side": "buy", "btc_amount": 0.01, "price": 50000.0,
        "fee": 0.5, "new_exposure": 0.50,
    })

    text = notifier._queue.get_nowait()
    assert text == (
        "⚖️ Rebalanceo BUY BTC/USDT\n"
        "Monto: 0.010000 BTC @ $50,000.00\n"
        "Fee: $0.50  |  exposición nueva: 50.0%"
    )


def test_notify_circuit_breaker_formats_drawdown_and_equity():
    notifier = TelegramNotifier("token123", "chat123")

    notifier.notify_circuit_breaker(drawdown_pct=0.52, equity_usdt=4800.0)

    text = notifier._queue.get_nowait()
    assert text == (
        "🛑 CIRCUIT BREAKER ACTIVADO (TSMOM)\n"
        "Drawdown desde el pico: 52.0%  |  equity: $4,800.00\n"
        "Posición forzada a flat. No se abren nuevas posiciones hasta reset manual."
    )


def test_notify_daily_heartbeat_formats_price_exposures_and_breaker_state():
    notifier = TelegramNotifier("token123", "chat123")

    notifier.notify_daily_heartbeat({
        "close": 67234.50, "target_exposure": 0.452,
        "current_exposure": 0.448, "breaker_active": False,
    })

    text = notifier._queue.get_nowait()
    assert text == (
        "📊 Cierre diario TSMOM\n"
        "Precio: $67,234.50\n"
        "Exposición objetivo: 45.2%  |  actual: 44.8%\n"
        "Circuit breaker: no activo"
    )


def test_notify_daily_heartbeat_formats_breaker_active():
    notifier = TelegramNotifier("token123", "chat123")

    notifier.notify_daily_heartbeat({
        "close": 50000.0, "target_exposure": 0.0,
        "current_exposure": 0.0, "breaker_active": True,
    })

    text = notifier._queue.get_nowait()
    assert "Circuit breaker: activo" in text


def test_notify_daily_heartbeat_disabled_when_no_credentials():
    notifier = TelegramNotifier(None, None)

    notifier.notify_daily_heartbeat({
        "close": 50000.0, "target_exposure": 0.0,
        "current_exposure": 0.0, "breaker_active": False,
    })

    assert notifier._queue.empty()


def test_notify_rebalance_disabled_when_no_credentials():
    notifier = TelegramNotifier(None, None)

    notifier.notify_rebalance({
        "side": "sell", "btc_amount": 0.01, "price": 50000.0,
        "fee": 0.5, "new_exposure": 0.0,
    })

    assert notifier._queue.empty()
