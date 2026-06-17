from __future__ import annotations

import asyncio
import logging

from config import CORRELATION_BLOCK_THRESHOLD, MACRO_UPDATE_SECONDS
from state import MarketState, Side

logger = logging.getLogger(__name__)


def update_mtf_trends(state: MarketState) -> None:
    """Derive 5m and 15m trend bias from EMA vs price relationship."""
    p = state.last_price
    if p <= 0:
        return

    if state.ema_15m > 0:
        if p > state.ema_15m * 1.0005:
            state.trend_15m = Side.LONG
        elif p < state.ema_15m * 0.9995:
            state.trend_15m = Side.SHORT

    if state.ema_5m > 0:
        if p > state.ema_5m * 1.0003:
            state.trend_5m = Side.LONG
        elif p < state.ema_5m * 0.9997:
            state.trend_5m = Side.SHORT


class MacroFilter:
    """
    Fetches SPY data via yfinance (free, ~15min delayed) and computes BTC-SPY
    rolling correlation. Blocks longs when correlation is high and SPY is falling.

    For live HFT-quality correlation, replace yfinance with a real-time data feed
    (e.g., Polygon.io, Alpaca, or direct CME WebSocket).
    """

    def __init__(self, state: MarketState) -> None:
        self.state = state
        self._yfinance_available = True

    async def run(self) -> None:
        while True:
            try:
                await self._update()
            except Exception:
                logger.exception("MacroFilter update failed")
            await asyncio.sleep(MACRO_UPDATE_SECONDS)

    async def _update(self) -> None:
        if not self._yfinance_available:
            return

        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed — macro correlation filter disabled")
            self._yfinance_available = False
            return

        loop = asyncio.get_event_loop()
        spy_data = await loop.run_in_executor(
            None,
            lambda: yf.download("SPY", period="1d", interval="15m", progress=False, auto_adjust=True),
        )

        if spy_data is None or spy_data.empty:
            return

        spy_closes = spy_data["Close"].dropna().tolist()
        if len(spy_closes) < 6:
            return

        btc_candles = list(state.candles_15m) if hasattr(self, '_use_state_attr') else list(self.state.candles_15m)
        if len(btc_candles) < 6:
            return

        n = min(len(spy_closes) - 1, len(btc_candles) - 1, 20)
        spy_ret = [
            (spy_closes[-(n - i)] - spy_closes[-(n - i) - 1]) / spy_closes[-(n - i) - 1]
            for i in range(n)
        ]
        btc_closes = [c.close for c in btc_candles[-(n + 1):]]
        btc_ret = [
            (btc_closes[i + 1] - btc_closes[i]) / btc_closes[i]
            for i in range(len(btc_closes) - 1)
        ]
        btc_ret = btc_ret[-n:]

        if len(spy_ret) != len(btc_ret) or len(spy_ret) < 4:
            return

        corr = _pearson(spy_ret, btc_ret)

        # SPY short-term trend: compare last close to close 4 bars ago
        spy_trend = "up" if spy_closes[-1] > spy_closes[-5] else "down"

        if abs(corr) >= CORRELATION_BLOCK_THRESHOLD and spy_trend == "down":
            if not self.state.macro_blocks_longs:
                logger.info("MACRO FILTER: blocking LONGS (corr=%.2f, SPY=%s)", corr, spy_trend)
            self.state.macro_blocks_longs = True
        else:
            self.state.macro_blocks_longs = False

        if abs(corr) >= CORRELATION_BLOCK_THRESHOLD and spy_trend == "up":
            if not self.state.macro_blocks_shorts:
                logger.info("MACRO FILTER: blocking SHORTS (corr=%.2f, SPY=%s)", corr, spy_trend)
            self.state.macro_blocks_shorts = True
        else:
            self.state.macro_blocks_shorts = False


def _pearson(xs: list, ys: list) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    denom = (var_x * var_y) ** 0.5
    return cov / denom if denom > 0 else 0.0
