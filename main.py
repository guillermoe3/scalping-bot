from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Callable, Optional

from dotenv import load_dotenv

import clock
import daily_safety
from data_feed import DataFeed
from daily_execution import DailyExecutionEngine
from daily_feed import DailyDataFeed, backfill
from daily_signal import objetivo_exposicion
from daily_state import DailyState, DailyClose, close_values
from execution import ExecutionEngine, PAPER_MODE
from indicators import detect_swing_points, update_indicators
from momentum import update_volume_velocity
from order_flow import snapshot_cvd_on_close
from regime import update_regime, update_trend_1h
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
    the same on_trade/on_candle_1m/on_candle_15m registration
    interface (duck typing, no shared base class)."""

    # -------------------------------------------------------------------------
    # Tick handler — runs on every trade event (sub-second)
    # -------------------------------------------------------------------------
    async def on_trade(price: float, qty: float, is_buyer_maker: bool, ts: float) -> None:
        update_volume_velocity(state)
        await engine.check_pending_entry()
        await engine.monitor_and_exit()

    # -------------------------------------------------------------------------
    # 1-minute candle close — debug heartbeat only (signal clock is 15m)
    # -------------------------------------------------------------------------
    async def on_candle_1m(candle: Candle) -> None:
        logger.debug("1m | close=%.2f", candle.close)

    # -------------------------------------------------------------------------
    # 15-minute candle close — primary signal evaluation clock
    # -------------------------------------------------------------------------
    async def on_candle_15m(candle: Candle) -> None:
        # 1. Snapshot CVD for this closed candle, reset for next
        snapshot_cvd_on_close(state)

        # 2. Recompute adaptive indicators (ATR, regime-aware EMA)
        update_indicators(state)

        # 3. Update regime state machine (hysteresis protected)
        update_regime(state)

        # 4. Update higher-timeframe trend bias
        update_trend_1h(state)

        # 5. Refresh structural swing points
        highs, lows = detect_swing_points(state.candles_15m)
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

        logger.info(
            "15m | close=%.2f atr=%.2f ema=%.2f regime=%s squeeze=%s",
            candle.close, state.atr, state.ema, state.regime.value, state.in_squeeze,
        )

    feed.on_trade(on_trade)
    feed.on_candle_1m(on_candle_1m)
    feed.on_candle_15m(on_candle_15m)


def wire_daily_strategy(
    state: DailyState,
    feed,
    engine: DailyExecutionEngine,
    on_breaker_tripped: Optional[Callable[[dict], None]] = None,
) -> None:
    """Registers the daily TSMOM strategy's single event handler: one
    signal evaluation + rebalance per closed UTC day. feed can be
    DailyDataFeed (live) — it only needs to expose on_candle_1d
    (duck typing, same convention as wire_strategy)."""

    async def on_candle_1d(candle: DailyClose) -> None:
        daily_safety.update_circuit_breaker(state, candle.close, on_breaker_tripped=on_breaker_tripped)
        target = 0.0 if state.breaker_active else objetivo_exposicion(close_values(state))
        await engine.rebalance(target, candle.close)
        state.last_rebalance_date = clock.today_utc()
        daily_safety.save_state(state)

        logger.info(
            "1d | close=%.2f target_exposure=%.1f%% breaker=%s",
            candle.close, target * 100, state.breaker_active,
        )

    feed.on_candle_1d(on_candle_1d)


async def run() -> None:
    daily_state = DailyState()
    found_persisted = daily_safety.load_into_state(daily_state)

    notifier = TelegramNotifier(os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"))

    engine = DailyExecutionEngine(daily_state, on_rebalanced=notifier.notify_rebalance)
    backfill(daily_state, engine.exchange)

    last_close = close_values(daily_state)[-1] if daily_state.closes else 0.0
    daily_safety.ensure_initialized(daily_state, engine.exchange, found_persisted, last_close)

    feed = DailyDataFeed(daily_state)
    on_breaker_tripped = lambda e: notifier.notify_circuit_breaker(e["drawdown_pct"], e["equity_usdt"])
    wire_daily_strategy(daily_state, feed, engine, on_breaker_tripped=on_breaker_tripped)

    mode = "PAPER" if os.getenv("PAPER_MODE", "true").lower() == "true" else "LIVE"
    logger.info("BTC TSMOM Daily Bot starting — mode=%s", mode)

    await asyncio.gather(
        feed.connect(),
        notifier.run(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
        sys.exit(0)
