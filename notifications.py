from __future__ import annotations

import asyncio
import logging
import urllib.parse
import urllib.request
from typing import Callable, Optional, Tuple

from config import KILL_SWITCH_DAILY_LOSS_PCT, PAPER_BALANCE_USDT
from state import MarketState

logger = logging.getLogger(__name__)

_API_URL_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"


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
        self._send_fn = send_fn or self._send_via_http
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

    def notify_rebalance(self, event: dict) -> None:
        text = (
            f"⚖️ Rebalanceo {event['side'].upper()} BTC/USDT\n"
            f"Monto: {event['btc_amount']:.6f} BTC @ ${event['price']:,.2f}\n"
            f"Fee: ${event['fee']:,.2f}  |  exposición nueva: {event['new_exposure']*100:.1f}%"
        )
        self._enqueue(text)

    def notify_circuit_breaker(self, drawdown_pct: float, equity_usdt: float) -> None:
        text = (
            "🛑 CIRCUIT BREAKER ACTIVADO (TSMOM)\n"
            f"Drawdown desde el pico: {drawdown_pct*100:.1f}%  |  equity: ${equity_usdt:,.2f}\n"
            "Posición forzada a flat. No se abren nuevas posiciones hasta reset manual."
        )
        self._enqueue(text)

    def notify_daily_heartbeat(self, event: dict) -> None:
        breaker_text = "activo" if event["breaker_active"] else "no activo"
        text = (
            "📊 Cierre diario TSMOM\n"
            f"Precio: ${event['close']:,.2f}\n"
            f"Exposición objetivo: {event['target_exposure']*100:.1f}%  |  "
            f"actual: {event['current_exposure']*100:.1f}%\n"
            f"Circuit breaker: {breaker_text}"
        )
        self._enqueue(text)

    def _enqueue(self, text: str) -> None:
        if not self._enabled:
            return
        self._queue.put_nowait(text)

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


def _kill_switch_reason(state: MarketState) -> str:
    """Re-derives why the kill switch tripped from already-available state —
    safety.after_trade_closed computes the same daily-loss/streak booleans
    internally but doesn't persist them, so this recomputes the daily-loss
    side of that check, mirroring its PAPER_BALANCE_USDT fallback exactly;
    consecutive_losses is shown either way in the body."""
    balance = state.daily_starting_balance if state.daily_starting_balance is not None else PAPER_BALANCE_USDT
    if state.pnl_today <= -KILL_SWITCH_DAILY_LOSS_PCT * balance:
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
