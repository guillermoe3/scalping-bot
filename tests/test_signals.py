import signals
from config import SPREAD_FILTER_ATR_PCT, SQUEEZE_MIN_BARS
from signals import _nearest_key_level, check_entry_signal, update_squeeze
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
    state.trend_1h = None
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
    state.trend_1h = None
    state.macro_blocks_longs = False
    state.macro_blocks_shorts = False
    return state


def test_update_squeeze_not_active_before_min_bars():
    state = MarketState()
    state.atr = 10.0
    state.swing_highs.append(110.0)
    state.last_price = 108.0

    for i in range(SQUEEZE_MIN_BARS - 1):
        state.candles_15m.append(_candle(108, 109, 107, 108, i))
        update_squeeze(state)

    assert state.in_squeeze is False
    assert state.squeeze_bar_count == SQUEEZE_MIN_BARS - 1


def test_update_squeeze_activates_with_short_direction_when_price_below_level():
    state = MarketState()
    state.atr = 10.0
    state.swing_highs.append(110.0)
    state.last_price = 108.0

    for i in range(SQUEEZE_MIN_BARS):
        state.candles_15m.append(_candle(108, 109, 107, 108, i))
        update_squeeze(state)

    assert state.in_squeeze is True
    assert state.squeeze_direction == Side.SHORT


def test_update_squeeze_activates_with_long_direction_when_price_above_level():
    state = MarketState()
    state.atr = 10.0
    state.swing_lows.append(90.0)
    state.last_price = 92.0

    for i in range(SQUEEZE_MIN_BARS):
        state.candles_15m.append(_candle(92, 93, 91, 92, i))
        update_squeeze(state)

    assert state.in_squeeze is True
    assert state.squeeze_direction == Side.LONG


def test_update_squeeze_resets_when_compression_breaks():
    state = MarketState()
    state.atr = 10.0
    state.swing_highs.append(110.0)
    state.last_price = 108.0
    for i in range(SQUEEZE_MIN_BARS):
        state.candles_15m.append(_candle(108, 109, 107, 108, i))
        update_squeeze(state)
    assert state.in_squeeze is True

    state.candles_15m.append(_candle(108, 120, 107, 119, 99))  # range breaks compression
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
        state.candles_15m.append(_candle(108, 109, 107, 108, i))
        update_squeeze(state)
    assert state.in_squeeze is True

    state.last_price = 50.0  # still compressed range, but far from the level
    state.candles_15m.append(_candle(50, 51, 49, 50, 99))
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


def test_entry_signal_rejected_when_1h_trend_opposes_direction():
    state = _base_state(direction=Side.LONG)
    state.trend_1h = Side.SHORT
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
    state.candles_15m.append(_candle(110, 111, 99, 100, 0))  # bearish candle

    assert check_entry_signal(state) is None


def test_entry_signal_allowed_when_breakout_candle_aligns_with_squeeze_direction():
    state = _base_state(direction=Side.LONG, regime=Regime.BREAKOUT)
    state.candles_15m.append(_candle(100, 111, 99, 110, 0))  # bullish candle

    assert check_entry_signal(state) == Side.LONG


def test_entry_signal_rejected_when_cvd_diverges_against_long():
    state = _base_state(direction=Side.LONG)
    for h, l in [(10.0, 8.0), (11.0, 9.0), (13.0, 9.0)]:
        state.candles_15m.append(_candle(l, h, l, h))
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


def test_nearest_key_level_reports_support_kind():
    state = MarketState()
    state.swing_lows.append(90.0)
    state.swing_highs.append(120.0)

    level, distance, kind = _nearest_key_level(95.0, state)

    assert (level, distance, kind) == (90.0, 5.0, "support")


def test_nearest_key_level_reports_resistance_kind():
    state = MarketState()
    state.swing_lows.append(50.0)
    state.swing_highs.append(110.0)

    level, distance, kind = _nearest_key_level(108.0, state)

    assert (level, distance, kind) == (110.0, 2.0, "resistance")


def test_nearest_key_level_empty_returns_support_placeholder():
    state = MarketState()

    level, distance, kind = _nearest_key_level(100.0, state)

    assert level == 0.0 and distance == float("inf") and kind == "support"


def test_nearest_key_level_tie_prefers_side_consistent_level():
    state = MarketState()
    state.swing_lows.append(110.0)   # soporte POR ENCIMA del precio: incoherente
    state.swing_highs.append(110.0)  # resistencia por encima: coherente

    level, distance, kind = _nearest_key_level(100.0, state)

    assert (level, kind) == (110.0, "resistance")


def test_nearest_key_level_tie_falls_back_to_support():
    state = MarketState()
    state.swing_lows.append(90.0)    # soporte por debajo: coherente
    state.swing_highs.append(110.0)  # resistencia por encima: coherente, misma distancia
    level, distance, kind = _nearest_key_level(100.0, state)

    assert (level, kind) == (90.0, "support")


def test_update_squeeze_arms_without_direction_when_level_kind_is_incoherent():
    state = MarketState()
    state.atr = 10.0
    state.swing_highs.append(95.0)  # resistencia ya rota, quedó DEBAJO del precio
    state.last_price = 100.0

    for i in range(SQUEEZE_MIN_BARS):
        state.candles_15m.append(_candle(100, 101, 99, 100, i))
        update_squeeze(state)

    assert state.in_squeeze is True
    assert state.squeeze_direction is None


def _armed_squeeze_below_resistance() -> MarketState:
    """Squeeze armada contra resistencia en 110, precio en 108."""
    state = MarketState()
    state.atr = 10.0
    state.swing_highs.append(110.0)
    state.last_price = 108.0
    for i in range(SQUEEZE_MIN_BARS):
        state.candles_15m.append(_candle(108, 109, 107, 108, i))
        update_squeeze(state)
    assert state.in_squeeze is True
    return state


def test_break_above_resistance_sets_broken_state_long():
    state = _armed_squeeze_below_resistance()

    state.candles_15m.append(_candle(108, 120, 107, 115, 99))  # cierra ARRIBA de 110
    update_squeeze(state)

    assert state.squeeze_broken is True
    assert state.squeeze_broken_direction == Side.LONG
    assert state.squeeze_broken_level == 110.0
    assert state.squeeze_broken_ttl == 2
    assert state.in_squeeze is False  # la vela de ruptura sí resetea la squeeze


def test_break_below_support_sets_broken_state_short():
    state = MarketState()
    state.atr = 10.0
    state.swing_lows.append(90.0)
    state.last_price = 92.0
    for i in range(SQUEEZE_MIN_BARS):
        state.candles_15m.append(_candle(92, 93, 91, 92, i))
        update_squeeze(state)
    assert state.in_squeeze is True

    state.candles_15m.append(_candle(92, 93, 80, 85, 99))  # cierra DEBAJO de 90
    update_squeeze(state)

    assert state.squeeze_broken is True
    assert state.squeeze_broken_direction == Side.SHORT


def test_close_exactly_on_level_is_not_a_break():
    state = _armed_squeeze_below_resistance()

    state.candles_15m.append(_candle(108, 120, 107, 110.0, 99))  # cierre exacto en el nivel
    update_squeeze(state)

    assert state.squeeze_broken is False


def test_bounce_away_from_level_is_not_a_break():
    state = _armed_squeeze_below_resistance()

    state.candles_15m.append(_candle(108, 109, 90, 95, 99))  # se aleja SIN cruzar 110
    update_squeeze(state)

    assert state.squeeze_broken is False


def test_broken_state_expires_after_ttl():
    state = _armed_squeeze_below_resistance()
    state.candles_15m.append(_candle(108, 120, 107, 115, 99))
    update_squeeze(state)
    assert state.squeeze_broken is True

    state.candles_15m.append(_candle(115, 130, 114, 128, 100))  # N+1: decrementa a 1
    update_squeeze(state)
    assert state.squeeze_broken is True

    state.candles_15m.append(_candle(128, 140, 127, 138, 101))  # N+2: llega a 0, limpia
    update_squeeze(state)
    assert state.squeeze_broken is False
    assert state.squeeze_broken_direction is None


def _broken_long_setup_state() -> MarketState:
    state = _base_state(direction=Side.LONG)
    state.in_squeeze = False
    state.squeeze_direction = None
    state.squeeze_broken = True
    state.squeeze_broken_direction = Side.LONG
    state.squeeze_broken_level = 95.0
    state.squeeze_broken_ttl = 2
    return state


def test_break_variant_fires_on_broken_state_and_consumes_it():
    state = _broken_long_setup_state()
    signals.ENTRY_VARIANT = "break"

    assert check_entry_signal(state) == Side.LONG
    assert state.squeeze_broken is False  # consumida


def test_break_variant_ignores_plain_armed_squeeze():
    state = _base_state(direction=Side.LONG)  # in_squeeze pero sin break
    signals.ENTRY_VARIANT = "break"

    assert check_entry_signal(state) is None


def test_fade_variant_ignores_broken_state():
    state = _broken_long_setup_state()
    signals.ENTRY_VARIANT = "fade"

    assert check_entry_signal(state) is None
