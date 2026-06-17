from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
from collections import deque

from config import CANDLE_BUFFER, SWING_BUFFER, OB_SNAPSHOT_BUFFER, CVD_CANDLE_BUFFER


class Regime(Enum):
    BREAKOUT = "A"       # Strong directional spike
    TIGHT_CHANNEL = "B"  # Low-volatility trend
    TRADING_RANGE = "C"  # Two-sided auction
    UNKNOWN = "?"


class Side(Enum):
    LONG = "long"
    SHORT = "short"


@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: int  # open time in milliseconds

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def bullish(self) -> bool:
        return self.close >= self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low


@dataclass
class OrderBookLevel:
    price: float
    quantity: float


@dataclass
class BookSnapshot:
    bids: List[OrderBookLevel]  # sorted descending
    asks: List[OrderBookLevel]  # sorted ascending
    timestamp: float


@dataclass
class Position:
    side: Side
    entry_price: float
    size: float              # base asset (BTC)
    entry_time: float        # unix seconds
    stop_loss: float
    tp1: float
    initial_atr: float
    initial_sl_distance: float
    tp1_hit: bool = False
    breakeven_moved: bool = False
    trailing_stop: Optional[float] = None
    fees_paid: float = 0.0
    realized_pnl: float = 0.0


@dataclass
class MarketState:
    # Live price
    last_price: float = 0.0
    last_bid: float = 0.0
    last_ask: float = 0.0
    spread: float = 0.0

    # Closed candle history (most recent last)
    candles_1m: deque = field(default_factory=lambda: deque(maxlen=CANDLE_BUFFER))
    candles_5m: deque = field(default_factory=lambda: deque(maxlen=CANDLE_BUFFER))
    candles_15m: deque = field(default_factory=lambda: deque(maxlen=CANDLE_BUFFER))

    # Forming (live) candles — updated tick by tick
    live_1m: Optional[Candle] = None
    live_5m: Optional[Candle] = None
    live_15m: Optional[Candle] = None

    # Adaptive indicators
    atr: float = 0.0
    ema: float = 0.0       # 1m EMA, period varies by regime
    ema_5m: float = 0.0
    ema_15m: float = 0.0

    # Regime state machine
    regime: Regime = Regime.UNKNOWN
    pending_regime: Optional[Regime] = None
    regime_confirm_count: int = 0

    # Structural context
    swing_highs: deque = field(default_factory=lambda: deque(maxlen=SWING_BUFFER))
    swing_lows: deque = field(default_factory=lambda: deque(maxlen=SWING_BUFFER))

    # Cumulative Volume Delta (CVD)
    cvd: float = 0.0                  # resets each candle open
    cvd_per_candle: deque = field(default_factory=lambda: deque(maxlen=CVD_CANDLE_BUFFER))

    # Order book (rolling snapshots for anti-spoofing)
    ob_snapshots: deque = field(default_factory=lambda: deque(maxlen=OB_SNAPSHOT_BUFFER))

    # Volman squeeze state
    in_squeeze: bool = False
    squeeze_bar_count: int = 0
    squeeze_reference_level: float = 0.0
    squeeze_direction: Optional[Side] = None

    # Momentum
    volume_velocity: float = 0.0        # BTC/sec in current candle
    prior_volume_velocity: float = 0.0  # velocity at position entry

    # Multi-timeframe trend bias
    trend_15m: Optional[Side] = None
    trend_5m: Optional[Side] = None

    # Macro context gates
    macro_blocks_longs: bool = False
    macro_blocks_shorts: bool = False

    # Open position
    position: Optional[Position] = None

    # Session tracking
    trades_today: int = 0
    pnl_today: float = 0.0

    # Daily safety / kill switch
    consecutive_losses: int = 0
    kill_switch_active: bool = False
    last_reset_date: Optional[str] = None
