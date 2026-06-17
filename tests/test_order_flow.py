import pytest

from order_flow import _averaged_bid_ask_volume, detect_cvd_divergence, get_book_imbalance, snapshot_cvd_on_close
from state import BookSnapshot, Candle, MarketState, OrderBookLevel


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
        state.candles_1m.append(_candle(h, l, i))
    for v in [2.0, 3.0]:
        state.cvd_per_candle.append(v)

    assert detect_cvd_divergence(state) is None


def test_detect_cvd_divergence_detects_bearish_divergence():
    state = MarketState()
    for i, (h, l) in enumerate([(10.0, 8.0), (11.0, 9.0), (13.0, 9.0)]):
        state.candles_1m.append(_candle(h, l, i))
    for v in [5.0, 4.0, 2.0]:
        state.cvd_per_candle.append(v)

    assert detect_cvd_divergence(state) == "bearish_divergence"


def test_detect_cvd_divergence_detects_bullish_divergence():
    state = MarketState()
    for i, (h, l) in enumerate([(10.0, 8.0), (9.0, 7.0), (9.0, 5.0)]):
        state.candles_1m.append(_candle(h, l, i))
    for v in [2.0, 3.0, 5.0]:
        state.cvd_per_candle.append(v)

    assert detect_cvd_divergence(state) == "bullish_divergence"


def test_detect_cvd_divergence_none_without_either_pattern():
    state = MarketState()
    for i, (h, l) in enumerate([(10.0, 8.0), (11.0, 9.0), (12.0, 9.5)]):
        state.candles_1m.append(_candle(h, l, i))
    for v in [2.0, 3.0, 4.0]:
        state.cvd_per_candle.append(v)

    assert detect_cvd_divergence(state) is None


def test_averaged_bid_ask_volume_empty_snapshots_returns_zero():
    assert _averaged_bid_ask_volume([]) == (0.0, 0.0)


def test_averaged_bid_ask_volume_matches_hand_calculated_average():
    snapshots = [
        BookSnapshot(bids=[OrderBookLevel(100.0, 1.0), OrderBookLevel(99.0, 2.0)], asks=[OrderBookLevel(101.0, 1.0)], timestamp=0.0),
        BookSnapshot(bids=[OrderBookLevel(100.0, 3.0)], asks=[OrderBookLevel(101.0, 1.0)], timestamp=1.0),
    ]

    assert _averaged_bid_ask_volume(snapshots, depth=10) == (3.0, 1.0)


def test_get_book_imbalance_neutral_below_minimum_snapshots():
    state = MarketState()

    assert get_book_imbalance(state) == (1.0, "neutral")


def test_get_book_imbalance_detects_strong_bid_pressure():
    state = MarketState()
    snapshots = [
        BookSnapshot(bids=[OrderBookLevel(100.0, 1.0), OrderBookLevel(99.0, 2.0)], asks=[OrderBookLevel(101.0, 1.0)], timestamp=0.0),
        BookSnapshot(bids=[OrderBookLevel(100.0, 3.0)], asks=[OrderBookLevel(101.0, 1.0)], timestamp=1.0),
    ]
    for snap in snapshots:
        state.ob_snapshots.append(snap)

    ratio, direction = get_book_imbalance(state)
    assert ratio == pytest.approx(3.0)
    assert direction == "bid"


def test_get_book_imbalance_detects_strong_ask_pressure():
    state = MarketState()
    snapshots = [
        BookSnapshot(bids=[OrderBookLevel(100.0, 1.0)], asks=[OrderBookLevel(101.0, 3.0)], timestamp=0.0),
        BookSnapshot(bids=[OrderBookLevel(100.0, 1.0)], asks=[OrderBookLevel(101.0, 3.0)], timestamp=1.0),
    ]
    for snap in snapshots:
        state.ob_snapshots.append(snap)

    ratio, direction = get_book_imbalance(state)
    assert ratio == pytest.approx(3.0)
    assert direction == "ask"


def test_get_book_imbalance_neutral_on_intermediate_ratio():
    state = MarketState()
    snapshots = [
        BookSnapshot(bids=[OrderBookLevel(100.0, 1.2)], asks=[OrderBookLevel(101.0, 1.0)], timestamp=0.0),
        BookSnapshot(bids=[OrderBookLevel(100.0, 1.2)], asks=[OrderBookLevel(101.0, 1.0)], timestamp=1.0),
    ]
    for snap in snapshots:
        state.ob_snapshots.append(snap)

    ratio, direction = get_book_imbalance(state)
    assert ratio == pytest.approx(1.2)
    assert direction == "neutral"
