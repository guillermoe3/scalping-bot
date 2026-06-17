from config import SPREAD_FILTER_ATR_PCT, SQUEEZE_MIN_BARS
from signals import check_entry_signal, update_squeeze
from state import BookSnapshot, Candle, MarketState, OrderBookLevel, Position, Regime, Side


def _valid_long_setup_state(atr: float = 10.0, spread: float = 0.1) -> MarketState:
    state = MarketState()
    state.regime = Regime.TIGHT_CHANNEL
    state.atr = atr
    state.spread = spread
    state.last_price = 100.0
    state.in_squeeze = True
    state.squeeze_direction = Side.LONG
    state.squeeze_reference_level = 95.0
    state.trend_15m = None
    state.macro_blocks_longs = False
    state.macro_blocks_shorts = False
    return state


def test_entry_signal_allowed_when_spread_within_atr_threshold():
    state = _valid_long_setup_state(atr=10.0, spread=0.1)

    assert check_entry_signal(state) == Side.LONG


def test_entry_signal_rejected_when_spread_exceeds_atr_threshold():
    state = _valid_long_setup_state(atr=10.0, spread=SPREAD_FILTER_ATR_PCT * 10.0 + 0.01)

    assert check_entry_signal(state) is None


def _candle(o, h, l, cl, index=0):
    return Candle(open=o, high=h, low=l, close=cl, volume=0.0, timestamp=index * 60_000)


def _base_state(direction: Side = Side.LONG, regime: Regime = Regime.TIGHT_CHANNEL) -> MarketState:
    state = MarketState()
    state.regime = regime
    state.atr = 10.0
    state.spread = 0.1
    state.last_price = 100.0
    state.in_squeeze = True
    state.squeeze_direction = direction
    state.squeeze_reference_level = 95.0 if direction == Side.LONG else 105.0
    state.trend_15m = None
    state.macro_blocks_longs = False
    state.macro_blocks_shorts = False
    return state


def test_update_squeeze_not_active_before_min_bars():
    state = MarketState()
    state.atr = 10.0
    state.swing_highs.append(110.0)
    state.last_price = 108.0

    for i in range(SQUEEZE_MIN_BARS - 1):
        state.candles_1m.append(_candle(108, 109, 107, 108, i))
        update_squeeze(state)

    assert state.in_squeeze is False
    assert state.squeeze_bar_count == SQUEEZE_MIN_BARS - 1


def test_update_squeeze_activates_with_short_direction_when_price_below_level():
    state = MarketState()
    state.atr = 10.0
    state.swing_highs.append(110.0)
    state.last_price = 108.0

    for i in range(SQUEEZE_MIN_BARS):
        state.candles_1m.append(_candle(108, 109, 107, 108, i))
        update_squeeze(state)

    assert state.in_squeeze is True
    assert state.squeeze_direction == Side.SHORT


def test_update_squeeze_activates_with_long_direction_when_price_above_level():
    state = MarketState()
    state.atr = 10.0
    state.swing_lows.append(90.0)
    state.last_price = 92.0

    for i in range(SQUEEZE_MIN_BARS):
        state.candles_1m.append(_candle(92, 93, 91, 92, i))
        update_squeeze(state)

    assert state.in_squeeze is True
    assert state.squeeze_direction == Side.LONG


def test_update_squeeze_resets_when_compression_breaks():
    state = MarketState()
    state.atr = 10.0
    state.swing_highs.append(110.0)
    state.last_price = 108.0
    for i in range(SQUEEZE_MIN_BARS):
        state.candles_1m.append(_candle(108, 109, 107, 108, i))
        update_squeeze(state)
    assert state.in_squeeze is True

    state.candles_1m.append(_candle(108, 120, 107, 119, 99))  # range breaks compression
    update_squeeze(state)

    assert state.in_squeeze is False
    assert state.squeeze_bar_count == 0
    assert state.squeeze_reference_level == 0.0
    assert state.squeeze_direction is None


def test_update_squeeze_resets_when_price_leaves_level_proximity():
    state = MarketState()
    state.atr = 10.0
    state.swing_highs.append(110.0)
    state.last_price = 108.0
    for i in range(SQUEEZE_MIN_BARS):
        state.candles_1m.append(_candle(108, 109, 107, 108, i))
        update_squeeze(state)
    assert state.in_squeeze is True

    state.last_price = 50.0  # still compressed range, but far from the level
    state.candles_1m.append(_candle(50, 51, 49, 50, 99))
    update_squeeze(state)

    assert state.in_squeeze is False
    assert state.squeeze_bar_count == 0


def test_entry_signal_rejected_when_regime_unknown():
    state = _base_state(regime=Regime.UNKNOWN)
    assert check_entry_signal(state) is None


def test_entry_signal_rejected_when_not_in_squeeze():
    state = _base_state()
    state.in_squeeze = False
    assert check_entry_signal(state) is None


def test_entry_signal_rejected_when_position_already_open():
    state = _base_state()
    state.position = Position(
        side=Side.LONG, entry_price=100.0, size=1.0, entry_time=0.0,
        stop_loss=95.0, tp1=110.0, initial_atr=2.0, initial_sl_distance=5.0,
    )
    assert check_entry_signal(state) is None


def test_entry_signal_rejected_when_squeeze_direction_is_none():
    state = _base_state()
    state.squeeze_direction = None
    assert check_entry_signal(state) is None


def test_entry_signal_rejected_when_15m_trend_opposes_direction():
    state = _base_state(direction=Side.LONG)
    state.trend_15m = Side.SHORT
    assert check_entry_signal(state) is None


def test_entry_signal_rejected_when_macro_blocks_longs():
    state = _base_state(direction=Side.LONG)
    state.macro_blocks_longs = True
    assert check_entry_signal(state) is None


def test_entry_signal_rejected_when_macro_blocks_shorts():
    state = _base_state(direction=Side.SHORT)
    state.macro_blocks_shorts = True
    assert check_entry_signal(state) is None


def test_entry_signal_rejected_when_breakout_candle_opposes_squeeze_direction():
    state = _base_state(direction=Side.LONG, regime=Regime.BREAKOUT)
    state.candles_1m.append(_candle(110, 111, 99, 100, 0))  # bearish candle

    assert check_entry_signal(state) is None


def test_entry_signal_allowed_when_breakout_candle_aligns_with_squeeze_direction():
    state = _base_state(direction=Side.LONG, regime=Regime.BREAKOUT)
    state.candles_1m.append(_candle(100, 111, 99, 110, 0))  # bullish candle

    assert check_entry_signal(state) == Side.LONG


def test_entry_signal_rejected_when_cvd_diverges_against_long():
    state = _base_state(direction=Side.LONG)
    for h, l in [(10.0, 8.0), (11.0, 9.0), (13.0, 9.0)]:
        state.candles_1m.append(_candle(l, h, l, h))
    for v in [5.0, 4.0, 2.0]:
        state.cvd_per_candle.append(v)

    assert check_entry_signal(state) is None


def test_entry_signal_rejected_when_book_imbalance_opposes_long():
    state = _base_state(direction=Side.LONG)
    snapshots = [
        BookSnapshot(bids=[OrderBookLevel(100.0, 1.0)], asks=[OrderBookLevel(101.0, 5.0)], timestamp=0.0),
        BookSnapshot(bids=[OrderBookLevel(100.0, 1.0)], asks=[OrderBookLevel(101.0, 5.0)], timestamp=1.0),
    ]
    for snap in snapshots:
        state.ob_snapshots.append(snap)

    assert check_entry_signal(state) is None


def test_entry_signal_returns_direction_when_all_gates_pass():
    state = _base_state(direction=Side.LONG)
    assert check_entry_signal(state) == Side.LONG
