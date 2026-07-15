from order_flow import detect_cvd_divergence, snapshot_cvd_on_close
from state import Candle, MarketState


def _candle(high: float, low: float, index: int = 0) -> Candle:
    return Candle(open=low, high=high, low=low, close=high, volume=0.0, timestamp=index * 60_000)


def test_snapshot_cvd_on_close_moves_cvd_to_history_and_resets():
    state = MarketState()
    state.cvd = 42.0

    snapshot_cvd_on_close(state)

    assert list(state.cvd_per_candle) == [42.0]
    assert state.cvd == 0.0


def test_detect_cvd_divergence_none_below_minimum_window():
    state = MarketState()
    for i, (h, l) in enumerate([(10.0, 8.0), (11.0, 9.0)]):
        state.candles_15m.append(_candle(h, l, i))
    for v in [2.0, 3.0]:
        state.cvd_per_candle.append(v)

    assert detect_cvd_divergence(state) is None


def test_detect_cvd_divergence_detects_bearish_divergence():
    state = MarketState()
    for i, (h, l) in enumerate([(10.0, 8.0), (11.0, 9.0), (13.0, 9.0)]):
        state.candles_15m.append(_candle(h, l, i))
    for v in [5.0, 4.0, 2.0]:
        state.cvd_per_candle.append(v)

    assert detect_cvd_divergence(state) == "bearish_divergence"


def test_detect_cvd_divergence_detects_bullish_divergence():
    state = MarketState()
    for i, (h, l) in enumerate([(10.0, 8.0), (9.0, 7.0), (9.0, 5.0)]):
        state.candles_15m.append(_candle(h, l, i))
    for v in [2.0, 3.0, 5.0]:
        state.cvd_per_candle.append(v)

    assert detect_cvd_divergence(state) == "bullish_divergence"


def test_detect_cvd_divergence_none_without_either_pattern():
    state = MarketState()
    for i, (h, l) in enumerate([(10.0, 8.0), (11.0, 9.0), (12.0, 9.5)]):
        state.candles_15m.append(_candle(h, l, i))
    for v in [2.0, 3.0, 4.0]:
        state.cvd_per_candle.append(v)

    assert detect_cvd_divergence(state) is None
