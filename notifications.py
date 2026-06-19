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
