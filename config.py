from __future__ import annotations

SYMBOL = "BTCUSDT"

# Binance WebSocket combined stream
WS_STREAM_URL = "wss://stream.binance.com:9443/stream"
STREAMS = [
    "btcusdt@aggTrade",
    "btcusdt@kline_1m",
    "btcusdt@kline_5m",
    "btcusdt@kline_15m",
    "btcusdt@depth20@100ms",
]

# Indicators
ATR_PERIOD = 14
EMA_PERIOD_BREAKOUT = 8       # shorter EMA during spike regime
EMA_PERIOD_CHANNEL = 13
EMA_PERIOD_RANGE = 20

# Regime state machine (hysteresis)
REGIME_CONFIRM_CANDLES = 3    # N consecutive confirming candles to transition
BREAKOUT_BODY_ATR_MULT = 1.5  # body >= 1.5x ATR → breakout candle
CHANNEL_RANGE_ATR_MULT = 0.8  # candle range <= 0.8x ATR → tight candle
RANGE_SWEEP_LOOKBACK = 20     # bars to detect double-sided liquidity sweeps

# Squeeze — Volman compression model
SQUEEZE_COMPRESSION_ATR = 0.4   # bar range < 0.4x ATR = compressed
SQUEEZE_MIN_BARS = 3            # min consecutive compressed bars for squeeze
SQUEEZE_LEVEL_ATR_PROXIMITY = 0.5  # must be within 0.5 ATR of key level

# CVD divergence
CVD_DIVERGENCE_LOOKBACK = 5

# Order book anti-spoofing
OB_SNAPSHOTS = 5              # average this many snapshots
OB_IMBALANCE_RATIO = 2.0      # 2:1 bid/ask volume = imbalance signal

# Risk management
ACCOUNT_RISK_PCT = 0.005      # 0.5% account equity risked per trade
INITIAL_SL_ATR = 1.5          # initial stop = 1.5x ATR from entry
TP1_RR = 2.0                  # first target at 2R
TP1_CLOSE_PCT = 0.5           # close 50% of position at TP1
BREAKEVEN_ATR_TRIGGER = 0.8   # move stop to breakeven after 0.8 ATR profit
ATR_BREATHING_THRESHOLD = 1.2 # expand SL if live ATR grows 20%+ vs entry ATR

# Time-based exits
TIME_EXIT_MINUTES = 15
MOMENTUM_ABORT_MINUTES = 3    # early abort if momentum collapses by minute 3

# MTF EMA periods
TREND_EMA_5M = 12
TREND_EMA_15M = 20

# Macro / context filter
CORRELATION_BLOCK_THRESHOLD = 0.8  # block longs if BTC-SPY correlation > this
MACRO_UPDATE_SECONDS = 300         # refresh macro data every 5 min

# Buffer sizes
CANDLE_BUFFER = 200
SWING_BUFFER = 20
OB_SNAPSHOT_BUFFER = 10
CVD_CANDLE_BUFFER = 20

# Daily kill switch
KILL_SWITCH_DAILY_LOSS_PCT = 0.02       # -2% of balance halts new entries for the rest of the UTC day
KILL_SWITCH_CONSECUTIVE_LOSSES = 3      # 3 losing trades in a row halts new entries

# State persistence
STATE_FILE_PATH = "safety_state.json"

# Fees
TAKER_FEE_RATE = 0.0005   # 0.05% per side, Binance Futures USDT-M, no BNB discount

# Spread filter
SPREAD_FILTER_ATR_PCT = 0.05  # block entries when spread > 5% of 1m ATR

# Backtesting
BACKTEST_SYNTHETIC_SPREAD_PCT = 0.0001  # 0.01% of price per side — no real historical order book data exists
