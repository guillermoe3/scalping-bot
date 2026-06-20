from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from context import MacroFilter, update_mtf_trends
from data_feed import DataFeed
from execution import ExecutionEngine, PAPER_MODE
from indicators import detect_swing_points, update_indicators
from momentum import update_volume_velocity
from order_flow import snapshot_cvd_on_close
from regime import update_mtf_trend, update_regime
import safety
from notifications import TelegramNotifier, make_notification_handlers
from signals import check_entry_signal, update_squeeze
from state import Candle, MarketState

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-8s %(name)-16s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def wire_strategy(state: MarketState, feed, engine: ExecutionEngine) -> None:
    """Registers the strategy's event handlers against feed. feed can be
    DataFeed (live) or BacktestFeed (backtest) — it only needs to expose
    the same on_trade/on_candle_1m/on_candle_5m/on_candle_15m registration
    interface (duck typing, no shared base class)."""

    # -------------------------------------------------------------------------
    # Tick handler — runs on every trade event (sub-second)
    # -------------------------------------------------------------------------
    async def on_trade(price: float, qty: float, is_buyer_maker: bool, ts: float) -> None:
        update_volume_velocity(state)
        await engine.monitor_and_exit()

    # -------------------------------------------------------------------------
    # 1-minute candle close — primary signal evaluation clock
    # -------------------------------------------------------------------------
    async def on_candle_1m(candle: Candle) -> None:
        # 1. Snapshot CVD for this closed candle, reset for next
        snapshot_cvd_on_close(state)

        # 2. Recompute adaptive indicators (ATR, regime-aware EMA)
        update_indicators(state)

        # 3. Update regime state machine (hysteresis protected)
        update_regime(state)

        # 4. Update MTF trend bias from EMA slopes
        update_mtf_trend(state)
        update_mtf_trends(state)

        # 5. Refresh structural swing points
        highs, lows = detect_swing_points(state.candles_1m)
        state.swing_highs.clear()
        state.swing_highs.extend(highs)
        state.swing_lows.clear()
        state.swing_lows.extend(lows)

        # 6. Evaluate squeeze state
        update_squeeze(state)

        # 7. Check for entry signal (only if flat and kill switch is not active)
        if state.position is None and safety.can_open_new_position(state, engine.exchange):
            signal = check_entry_signal(state)
            if signal is not None:
                await engine.enter(signal)

        logger.debug(
            "1m | close=%.2f atr=%.2f ema=%.2f regime=%s trend15=%s squeeze=%s",
            candle.close,
            state.atr,
            state.ema,
            state.regime.value,
            state.trend_15m.value if state.trend_15m else "?",
            state.in_squeeze,
        )

    # -------------------------------------------------------------------------
    # 5m candle close — MTF indicator refresh
    # -------------------------------------------------------------------------
    async def on_candle_5m(candle: Candle) -> None:
        update_indicators(state)
        update_mtf_trend(state)

    # -------------------------------------------------------------------------
    # 15m candle close — highest context update
    # -------------------------------------------------------------------------
    async def on_candle_15m(candle: Candle) -> None:
        update_indicators(state)
        update_mtf_trend(state)
        logger.info(
            "15m | close=%.2f ema15=%.2f trend=%s",
            candle.close,
            state.ema_15m,
            state.trend_15m.value if state.trend_15m else "?",
        )

    feed.on_trade(on_trade)
    feed.on_candle_1m(on_candle_1m)
    feed.on_candle_5m(on_candle_5m)
    feed.on_candle_15m(on_candle_15m)


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


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
        sys.exit(0)
