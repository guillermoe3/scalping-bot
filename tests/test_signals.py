from config import SPREAD_FILTER_ATR_PCT
from signals import check_entry_signal
from state import MarketState, Regime, Side


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
