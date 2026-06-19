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
