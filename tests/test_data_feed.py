from data_feed import update_live_candles
from state import Candle, MarketState


def _live_candle(price: float = 100.0, volume: float = 0.0) -> Candle:
    return Candle(open=price, high=price, low=price, close=price, volume=volume, timestamp=0)


def test_update_live_candles_updates_high_low_close_volume():
    state = MarketState()
    state.live_1m = _live_candle(100.0)

    update_live_candles(state, price=105.0, qty=2.0)

    assert state.live_1m.high == 105.0
    assert state.live_1m.low == 100.0
    assert state.live_1m.close == 105.0
    assert state.live_1m.volume == 2.0


def test_update_live_candles_tracks_low_on_price_drop():
    state = MarketState()
    state.live_1m = _live_candle(100.0)

    update_live_candles(state, price=95.0, qty=1.0)

    assert state.live_1m.low == 95.0
    assert state.live_1m.high == 100.0


def test_update_live_candles_skips_timeframes_with_no_live_candle():
    state = MarketState()
    state.live_1m = _live_candle(100.0)

    update_live_candles(state, price=101.0, qty=1.0)  # must not raise

    assert state.live_5m is None
    assert state.live_15m is None


def test_update_live_candles_updates_all_three_timeframes_at_once():
    state = MarketState()
    state.live_1m = _live_candle(100.0)
    state.live_5m = _live_candle(100.0)
    state.live_15m = _live_candle(100.0)

    update_live_candles(state, price=110.0, qty=3.0)

    assert state.live_1m.volume == 3.0
    assert state.live_5m.volume == 3.0
    assert state.live_15m.volume == 3.0
