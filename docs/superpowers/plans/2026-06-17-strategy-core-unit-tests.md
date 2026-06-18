# Strategy-Core Unit Test Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Bring the strategy core (`indicators.py`, `momentum.py`, `order_flow.py`, `regime.py`, `context.py`, and the rest of `signals.py`) from zero test coverage to full coverage, fixing two bugs in `context.py` that block writing a correct test for it.

**Architecture:** Pure unit tests against hand-built synthetic state — real `MarketState`/`Candle`/`BookSnapshot`/`Position` instances with deques populated directly, no mocking of the logic under test. The only mock is for the real network I/O in `MacroFilter._update` (the `yfinance` call), which is replaced with a fake `yf.download` via `monkeypatch`.

**Tech Stack:** Python 3.12, pytest 9.x, project venv at `.venv/`. No new dependencies.

## Global Constraints

- Run tests with `.venv/bin/pytest` from the repo root (`/home/guille/dev/scalping-bot`) — this is the project's existing venv, already has `pytest`, `pandas`, `yfinance` installed.
- Test files live at `tests/test_<module>.py`, no `__init__.py`, resolved via the existing blank root `conftest.py`. Follow this exactly for new files.
- Never mock the function under test. Only mock real external I/O (the `yfinance` network call in Task 6).
- Do not add new dependencies (no `pytest-asyncio`, no `hypothesis`). `MacroFilter._update` is `async def`; test it by calling `asyncio.run(mf._update())` from an ordinary `def test_...():` function.
- Out of scope (do not implement): a Binance backtesting harness, deduplicating `update_mtf_trend` (`regime.py`) vs `update_mtf_trends` (`context.py`), property-based tests, or testing `MacroFilter.run()`'s infinite polling loop (only `_update()` is tested).
- Baseline before this plan: 36 tests passing (`.venv/bin/pytest -q`). Each task below adds tests on top of that baseline without touching existing passing tests (except Task 5, which extends — never edits — the two existing tests in `tests/test_signals.py`).

---

### Task 1: `tests/test_indicators.py`

**Files:**
- Create: `tests/test_indicators.py`

**Interfaces:**
- Consumes: `compute_atr(candles: deque, period: int = ATR_PERIOD) -> float`, `compute_ema(values: List[float], period: int) -> float`, `ema_period_for_regime(regime: Regime) -> int`, `detect_swing_points(candles: deque, lookback: int = 5) -> Tuple[List[float], List[float]]`, `update_indicators(state: MarketState) -> None` — all from `indicators.py`. `Candle`, `MarketState`, `Regime` from `state.py`. `EMA_PERIOD_BREAKOUT`, `EMA_PERIOD_CHANNEL`, `EMA_PERIOD_RANGE` from `config.py`.
- Produces: nothing consumed by later tasks — this file is self-contained.

- [x] **Step 1: Write the full test file**

```python
from collections import deque

import pytest

from config import EMA_PERIOD_BREAKOUT, EMA_PERIOD_CHANNEL, EMA_PERIOD_RANGE
from indicators import compute_atr, compute_ema, detect_swing_points, ema_period_for_regime, update_indicators
from state import Candle, MarketState, Regime


def _candle(high: float, low: float, close: float = None, index: int = 0) -> Candle:
    close = high if close is None else close
    return Candle(open=low, high=high, low=low, close=close, volume=0.0, timestamp=index * 60_000)


def _candles_with_closes(closes):
    out = []
    for i, close in enumerate(closes):
        out.append(Candle(open=close, high=close + 1, low=close - 1, close=close, volume=0.0, timestamp=i * 60_000))
    return out


def test_compute_atr_returns_zero_with_fewer_than_two_candles():
    assert compute_atr(deque([_candle(10.0, 8.0)])) == 0.0
    assert compute_atr(deque([])) == 0.0


def test_compute_atr_matches_hand_calculated_wilder_value():
    candles = deque([
        Candle(open=9.0, high=10.0, low=8.0, close=9.0, volume=0.0, timestamp=0),
        Candle(open=10.0, high=11.0, low=9.0, close=10.0, volume=0.0, timestamp=1),
        Candle(open=12.0, high=13.0, low=10.0, close=12.0, volume=0.0, timestamp=2),
        Candle(open=11.5, high=12.0, low=11.0, close=11.5, volume=0.0, timestamp=3),
        Candle(open=13.0, high=14.0, low=11.0, close=13.0, volume=0.0, timestamp=4),
    ])

    assert compute_atr(candles, period=3) == pytest.approx(7 / 3)


def test_compute_ema_returns_zero_for_empty_list():
    assert compute_ema([], period=3) == 0.0


def test_compute_ema_matches_hand_calculated_value():
    assert compute_ema([1.0, 2.0, 3.0, 4.0, 5.0], period=3) == pytest.approx(4.0)


def test_ema_period_for_regime_maps_each_regime_to_its_configured_period():
    assert ema_period_for_regime(Regime.BREAKOUT) == EMA_PERIOD_BREAKOUT
    assert ema_period_for_regime(Regime.TIGHT_CHANNEL) == EMA_PERIOD_CHANNEL
    assert ema_period_for_regime(Regime.TRADING_RANGE) == EMA_PERIOD_RANGE
    assert ema_period_for_regime(Regime.UNKNOWN) == EMA_PERIOD_RANGE


def test_detect_swing_points_returns_empty_below_minimum_candle_count():
    candles = deque([_candle(10.0, 5.0) for _ in range(4)])

    assert detect_swing_points(candles, lookback=2) == ([], [])


def test_detect_swing_points_finds_known_peak_and_valley():
    highs_lows = [(10.0, 5.0), (12.0, 6.0), (20.0, 7.0), (15.0, 3.0), (8.0, 2.0), (9.0, 4.0), (11.0, 6.0)]
    candles = deque(_candle(h, l, index=i) for i, (h, l) in enumerate(highs_lows))

    swing_highs, swing_lows = detect_swing_points(candles, lookback=2)

    assert swing_highs == [20.0]
    assert swing_lows == [2.0]


def test_update_indicators_sets_atr_and_all_ema_fields():
    state = MarketState()
    state.regime = Regime.TIGHT_CHANNEL
    for c in _candles_with_closes([100.0 + i for i in range(25)]):
        state.candles_1m.append(c)
    for c in _candles_with_closes([100.0 + i for i in range(3)]):
        state.candles_5m.append(c)
        state.candles_15m.append(c)

    update_indicators(state)

    assert state.atr > 0.0
    assert state.ema > 0.0
    assert state.ema_5m > 0.0
    assert state.ema_15m > 0.0


def test_update_indicators_uses_regime_adaptive_period_for_1m_ema():
    closes = [100.0 + i for i in range(25)]

    breakout_state = MarketState()
    breakout_state.regime = Regime.BREAKOUT
    for c in _candles_with_closes(closes):
        breakout_state.candles_1m.append(c)
    update_indicators(breakout_state)

    unknown_state = MarketState()
    unknown_state.regime = Regime.UNKNOWN
    for c in _candles_with_closes(closes):
        unknown_state.candles_1m.append(c)
    update_indicators(unknown_state)

    assert breakout_state.ema != pytest.approx(unknown_state.ema)
```

- [x] **Step 2: Run the new tests**

Run: `.venv/bin/pytest tests/test_indicators.py -v`
Expected: `9 passed` — all of `test_compute_atr_returns_zero_with_fewer_than_two_candles`, `test_compute_atr_matches_hand_calculated_wilder_value`, `test_compute_ema_returns_zero_for_empty_list`, `test_compute_ema_matches_hand_calculated_value`, `test_ema_period_for_regime_maps_each_regime_to_its_configured_period`, `test_detect_swing_points_returns_empty_below_minimum_candle_count`, `test_detect_swing_points_finds_known_peak_and_valley`, `test_update_indicators_sets_atr_and_all_ema_fields`, `test_update_indicators_uses_regime_adaptive_period_for_1m_ema` PASSED.

- [x] **Step 3: Commit**

```bash
git add tests/test_indicators.py
git commit -m "Add unit tests for indicators.py"
```

---

### Task 2: `tests/test_momentum.py`

**Files:**
- Create: `tests/test_momentum.py`

**Interfaces:**
- Consumes: `update_volume_velocity(state: MarketState) -> None`, `should_abort_for_momentum(state: MarketState) -> bool` from `momentum.py`. `Candle`, `MarketState`, `Position`, `Side` from `state.py`. `MOMENTUM_ABORT_MINUTES` from `config.py`.
- Produces: nothing consumed by later tasks.

- [x] **Step 1: Write the full test file**

```python
import time

import pytest

from config import MOMENTUM_ABORT_MINUTES
from momentum import should_abort_for_momentum, update_volume_velocity
from state import Candle, MarketState, Position, Side


def _position(entry_time: float) -> Position:
    return Position(
        side=Side.LONG, entry_price=100.0, size=1.0, entry_time=entry_time,
        stop_loss=95.0, tp1=110.0, initial_atr=2.0, initial_sl_distance=5.0,
    )


def test_update_volume_velocity_noop_when_no_live_candle():
    state = MarketState()
    state.volume_velocity = 99.0

    update_volume_velocity(state)

    assert state.volume_velocity == 99.0


def test_update_volume_velocity_matches_volume_over_elapsed_seconds():
    state = MarketState()
    state.live_1m = Candle(
        open=1.0, high=1.0, low=1.0, close=1.0, volume=10.0,
        timestamp=(time.time() - 5.0) * 1000.0,
    )

    update_volume_velocity(state)

    assert state.volume_velocity == pytest.approx(2.0, abs=0.01)


def test_should_abort_for_momentum_false_without_position():
    state = MarketState()

    assert should_abort_for_momentum(state) is False


def test_should_abort_for_momentum_false_before_abort_window():
    state = MarketState()
    state.position = _position(entry_time=time.time())

    assert should_abort_for_momentum(state) is False


def test_should_abort_for_momentum_false_when_no_prior_velocity():
    state = MarketState()
    state.position = _position(entry_time=time.time() - MOMENTUM_ABORT_MINUTES * 60 - 10)
    state.prior_volume_velocity = 0.0

    assert should_abort_for_momentum(state) is False


def test_should_abort_for_momentum_true_when_velocity_collapses():
    state = MarketState()
    state.position = _position(entry_time=time.time() - MOMENTUM_ABORT_MINUTES * 60 - 10)
    state.prior_volume_velocity = 10.0
    state.volume_velocity = 2.0  # ratio 0.2 < 0.30 collapse threshold

    assert should_abort_for_momentum(state) is True


def test_should_abort_for_momentum_false_when_velocity_holds():
    state = MarketState()
    state.position = _position(entry_time=time.time() - MOMENTUM_ABORT_MINUTES * 60 - 10)
    state.prior_volume_velocity = 10.0
    state.volume_velocity = 5.0  # ratio 0.5 >= 0.30 collapse threshold

    assert should_abort_for_momentum(state) is False
```

- [x] **Step 2: Run the new tests**

Run: `.venv/bin/pytest tests/test_momentum.py -v`
Expected: `7 passed`.

- [x] **Step 3: Commit**

```bash
git add tests/test_momentum.py
git commit -m "Add unit tests for momentum.py"
```

---

### Task 3: `tests/test_order_flow.py`

**Files:**
- Create: `tests/test_order_flow.py`

**Interfaces:**
- Consumes: `snapshot_cvd_on_close(state: MarketState) -> None`, `detect_cvd_divergence(state: MarketState) -> Optional[str]`, `_averaged_bid_ask_volume(snapshots: List[BookSnapshot], depth: int = 10) -> Tuple[float, float]`, `get_book_imbalance(state: MarketState) -> Tuple[float, str]` from `order_flow.py`. `BookSnapshot`, `Candle`, `MarketState`, `OrderBookLevel` from `state.py`.
- Produces: nothing consumed by later tasks.

- [x] **Step 1: Write the full test file**

```python
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
```

- [x] **Step 2: Run the new tests**

Run: `.venv/bin/pytest tests/test_order_flow.py -v`
Expected: `11 passed`.

- [x] **Step 3: Commit**

```bash
git add tests/test_order_flow.py
git commit -m "Add unit tests for order_flow.py"
```

---

### Task 4: `tests/test_regime.py`

**Files:**
- Create: `tests/test_regime.py`

**Interfaces:**
- Consumes: `_is_breakout_candle(c: Candle, atr: float) -> bool`, `_is_tight_candle(c: Candle, atr: float) -> bool`, `_has_liquidity_sweeps_at_both_extremes(candles: deque, lookback: int = RANGE_SWEEP_LOOKBACK) -> bool`, `_ema_is_sloping(state: MarketState, atr: float) -> bool`, `_infer_candidate(state: MarketState) -> Regime`, `update_regime(state: MarketState) -> None`, `update_mtf_trend(state: MarketState) -> None` — all from `regime.py`. `Candle`, `MarketState`, `Regime`, `Side` from `state.py`. `REGIME_CONFIRM_CANDLES` from `config.py`.
- Produces: nothing consumed by later tasks.

- [x] **Step 1: Write the full test file**

```python
from collections import deque

from config import REGIME_CONFIRM_CANDLES
from regime import (
    _ema_is_sloping,
    _has_liquidity_sweeps_at_both_extremes,
    _infer_candidate,
    _is_breakout_candle,
    _is_tight_candle,
    update_mtf_trend,
    update_regime,
)
from state import Candle, MarketState, Regime, Side


def _candle(o: float, h: float, l: float, cl: float, index: int = 0) -> Candle:
    return Candle(open=o, high=h, low=l, close=cl, volume=0.0, timestamp=index * 60_000)


def _boring(index: int) -> Candle:
    return _candle(105.0, 106.0, 104.0, 105.0, index)


def _boring_state(atr: float = 10.0) -> MarketState:
    """20 identical low-range candles. Their own high/low ARE the 20-bar
    window's extremes, so _infer_candidate always reads this as
    tight + swept + not sloping -> Regime.TRADING_RANGE."""
    state = MarketState()
    state.atr = atr
    for i in range(20):
        state.candles_1m.append(_boring(i))
    return state


def _tight_unswept_candles():
    """One wide outlier candle sets the 20-bar window's high/low, but none
    of the most recent 5 candles touch them -> tight + NOT swept ->
    Regime.TIGHT_CHANNEL."""
    return [_candle(100.0, 130.0, 70.0, 100.0, 0)] + [_boring(i) for i in range(1, 20)]


def _tight_swept_candles():
    """15 boring candles, then two candles that tag the window's high and
    low within the last 5 -> tight + swept -> Regime.TRADING_RANGE
    (when not sloping)."""
    return [_boring(i) for i in range(15)] + [
        _candle(105.0, 110.0, 104.0, 109.0, 15),
        _candle(105.0, 106.0, 100.0, 101.0, 16),
    ] + [_boring(i) for i in range(17, 20)]


def test_is_breakout_candle_true_above_body_atr_threshold():
    candle = _candle(100.0, 116.0, 99.0, 116.0)  # body=16 >= 1.5*10
    assert _is_breakout_candle(candle, atr=10.0) is True


def test_is_breakout_candle_false_below_body_atr_threshold():
    candle = _candle(100.0, 108.0, 99.0, 101.0)  # body=1 < 1.5*10
    assert _is_breakout_candle(candle, atr=10.0) is False


def test_is_tight_candle_true_below_range_atr_threshold():
    candle = _candle(100.0, 104.0, 100.0, 102.0)  # range=4 <= 0.8*10
    assert _is_tight_candle(candle, atr=10.0) is True


def test_is_tight_candle_false_above_range_atr_threshold():
    candle = _candle(100.0, 110.0, 95.0, 102.0)  # range=15 > 0.8*10
    assert _is_tight_candle(candle, atr=10.0) is False


def test_has_liquidity_sweeps_true_when_both_extremes_touched_recently():
    candles = deque(_tight_swept_candles())
    assert _has_liquidity_sweeps_at_both_extremes(candles, lookback=20) is True


def test_has_liquidity_sweeps_false_when_recent_candles_miss_extremes():
    candles = deque(_tight_unswept_candles())
    assert _has_liquidity_sweeps_at_both_extremes(candles, lookback=20) is False


def test_has_liquidity_sweeps_false_below_minimum_lookback():
    candles = deque(_tight_swept_candles()[:10])
    assert _has_liquidity_sweeps_at_both_extremes(candles, lookback=20) is False


def test_ema_is_sloping_true_when_drift_exceeds_threshold():
    state = MarketState()
    state.atr = 10.0
    state.ema = 110.0  # close 10 bars ago is 105.0 -> drift 5.0 > 0.15*10=1.5
    for i in range(10):
        state.candles_1m.append(_boring(i))

    assert _ema_is_sloping(state, state.atr) is True


def test_ema_is_sloping_false_when_drift_within_threshold():
    state = MarketState()
    state.atr = 10.0
    state.ema = 105.5  # drift 0.5 <= 1.5
    for i in range(10):
        state.candles_1m.append(_boring(i))

    assert _ema_is_sloping(state, state.atr) is False


def test_ema_is_sloping_false_below_minimum_candle_count():
    state = MarketState()
    state.atr = 10.0
    state.ema = 110.0
    for i in range(9):
        state.candles_1m.append(_boring(i))

    assert _ema_is_sloping(state, state.atr) is False


def test_infer_candidate_unknown_below_minimum_candle_count():
    state = MarketState()
    state.atr = 10.0
    for i in range(3):
        state.candles_1m.append(_boring(i))

    assert _infer_candidate(state) == Regime.UNKNOWN


def test_infer_candidate_breakout_on_large_body_candle():
    state = MarketState()
    state.atr = 10.0
    for i in range(5):
        state.candles_1m.append(_boring(i))
    state.candles_1m.append(_candle(100.0, 120.0, 99.0, 120.0, 5))

    assert _infer_candidate(state) == Regime.BREAKOUT


def test_infer_candidate_tight_channel_when_tight_but_not_swept():
    state = MarketState()
    state.atr = 10.0
    for c in _tight_unswept_candles():
        state.candles_1m.append(c)

    assert _infer_candidate(state) == Regime.TIGHT_CHANNEL


def test_infer_candidate_trading_range_when_tight_swept_and_not_sloping():
    state = MarketState()
    state.atr = 10.0
    for c in _tight_swept_candles():
        state.candles_1m.append(c)
    state.ema = list(state.candles_1m)[-10].close  # keep EMA flat -> not sloping

    assert _infer_candidate(state) == Regime.TRADING_RANGE


def test_update_regime_single_confirmation_does_not_transition():
    state = _boring_state()  # candidate == TRADING_RANGE every call

    update_regime(state)

    assert state.regime == Regime.UNKNOWN
    assert state.pending_regime == Regime.TRADING_RANGE
    assert state.regime_confirm_count == 1


def test_update_regime_transitions_after_confirm_candles():
    state = _boring_state()

    for _ in range(REGIME_CONFIRM_CANDLES):
        update_regime(state)

    assert state.regime == Regime.TRADING_RANGE
    assert state.pending_regime is None
    assert state.regime_confirm_count == 0


def test_update_regime_interrupted_streak_resets_to_new_candidate():
    state = _boring_state()
    update_regime(state)
    update_regime(state)
    assert state.regime_confirm_count == 2
    assert state.pending_regime == Regime.TRADING_RANGE

    state.candles_1m.clear()
    for c in _tight_unswept_candles():
        state.candles_1m.append(c)
    update_regime(state)  # candidate is now TIGHT_CHANNEL, not TRADING_RANGE

    assert state.regime == Regime.UNKNOWN
    assert state.pending_regime == Regime.TIGHT_CHANNEL
    assert state.regime_confirm_count == 1


def test_update_regime_unknown_candidate_never_mutates_state():
    state = _boring_state()
    state.atr = 0.0  # forces _infer_candidate -> UNKNOWN
    state.regime = Regime.TRADING_RANGE
    state.pending_regime = Regime.BREAKOUT
    state.regime_confirm_count = 2

    update_regime(state)

    assert state.regime == Regime.TRADING_RANGE
    assert state.pending_regime == Regime.BREAKOUT
    assert state.regime_confirm_count == 2


def test_update_mtf_trend_15m_goes_long_above_dead_zone():
    state = MarketState()
    state.ema_15m = 100.0
    state.trend_15m = None
    state.last_price = 100.06

    update_mtf_trend(state)

    assert state.trend_15m == Side.LONG


def test_update_mtf_trend_15m_unchanged_inside_dead_zone():
    state = MarketState()
    state.ema_15m = 100.0
    state.trend_15m = Side.LONG
    state.last_price = 100.0

    update_mtf_trend(state)

    assert state.trend_15m == Side.LONG


def test_update_mtf_trend_15m_goes_short_below_dead_zone():
    state = MarketState()
    state.ema_15m = 100.0
    state.trend_15m = None
    state.last_price = 99.9

    update_mtf_trend(state)

    assert state.trend_15m == Side.SHORT


def test_update_mtf_trend_5m_goes_long_above_dead_zone():
    state = MarketState()
    state.ema_5m = 100.0
    state.trend_5m = None
    state.last_price = 100.04

    update_mtf_trend(state)

    assert state.trend_5m == Side.LONG


def test_update_mtf_trend_5m_unchanged_inside_dead_zone():
    state = MarketState()
    state.ema_5m = 100.0
    state.trend_5m = Side.SHORT
    state.last_price = 100.0

    update_mtf_trend(state)

    assert state.trend_5m == Side.SHORT


def test_update_mtf_trend_5m_goes_short_below_dead_zone():
    state = MarketState()
    state.ema_5m = 100.0
    state.trend_5m = None
    state.last_price = 99.96

    update_mtf_trend(state)

    assert state.trend_5m == Side.SHORT
```

- [x] **Step 2: Run the new tests**

Run: `.venv/bin/pytest tests/test_regime.py -v`
Expected: `24 passed`.

- [x] **Step 3: Commit**

```bash
git add tests/test_regime.py
git commit -m "Add unit tests for regime.py"
```

---

### Task 5: Extend `tests/test_signals.py`

**Files:**
- Modify: `tests/test_signals.py` (currently 31 lines — 1 helper + 2 tests for the spread filter, added in a prior session; this task adds the remaining `update_squeeze` and `check_entry_signal` coverage without touching the existing helper or tests)

**Interfaces:**
- Consumes: `update_squeeze(state: MarketState) -> None`, `check_entry_signal(state: MarketState) -> Optional[Side]` from `signals.py` (already imported in the file — `check_entry_signal` is, `update_squeeze` needs adding). `BookSnapshot`, `Candle`, `MarketState`, `OrderBookLevel`, `Position`, `Regime`, `Side` from `state.py`. `SQUEEZE_MIN_BARS` from `config.py`.
- Produces: nothing consumed by later tasks.

- [x] **Step 1: Update the imports at the top of the file**

In `tests/test_signals.py`, replace:

```python
from config import SPREAD_FILTER_ATR_PCT
from signals import check_entry_signal
from state import MarketState, Regime, Side
```

with:

```python
from config import SPREAD_FILTER_ATR_PCT, SQUEEZE_MIN_BARS
from signals import check_entry_signal, update_squeeze
from state import BookSnapshot, Candle, MarketState, OrderBookLevel, Position, Regime, Side
```

- [x] **Step 2: Append the new helper and test functions at the end of the file**

Add this after the existing `test_entry_signal_rejected_when_spread_exceeds_atr_threshold` function (keep the existing `_valid_long_setup_state` helper and its two tests untouched above this point):

```python


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
```

- [x] **Step 3: Run the full file**

Run: `.venv/bin/pytest tests/test_signals.py -v`
Expected: `19 passed` (2 pre-existing spread-filter tests + 17 new).

- [x] **Step 4: Commit**

```bash
git add tests/test_signals.py
git commit -m "Add unit tests for update_squeeze and the remaining check_entry_signal gates"
```

---

### Task 6: Fix `context.py` bugs, then write `tests/test_context.py`

**Files:**
- Modify: `context.py:76` (dead branch) and `context.py:64-67` (`MacroFilter._update`'s `yf.download` call — missing `multi_level_index=False`)
- Create: `tests/test_context.py`

**Interfaces:**
- Consumes: `update_mtf_trends(state: MarketState) -> None`, `MacroFilter(state: MarketState)` with `async def _update(self) -> None` and instance attribute `_yfinance_available: bool`, `_pearson(xs: list, ys: list) -> float` — all from `context.py`. `Candle`, `MarketState`, `Side` from `state.py`. `CORRELATION_BLOCK_THRESHOLD` from `config.py`.
- Produces: nothing consumed by later tasks.

**Why fix first:** `context.py:76`'s `hasattr(self, '_use_state_attr')` is always `False` (that attribute is never set anywhere), so the `if` branch is dead and the `else` branch — `list(self.state.candles_15m)` — always runs. Replacing the whole expression with the `else` branch alone is a no-op for behavior, but removes a confusing line that shadows the module-level `state` import. `context.py:64-67`'s call to `yf.download(...)` is missing `multi_level_index=False`; with the installed `yfinance==1.4.1` + `pandas==3.0.3`, `yf.download` returns MultiIndex columns even for a single ticker, so `spy_data["Close"]` is a DataFrame (not a Series) and `.dropna().tolist()` raises `AttributeError: 'DataFrame' object has no attribute 'tolist'` — this was seen directly in this environment in a prior session (see `docs/superpowers/specs/2026-06-17-strategy-core-unit-tests-design.md` section 2.2). The unit tests in this task replace `yf.download` with a fake that already returns flat columns, so they exercise the function's logic correctly regardless of this kwarg — the fix matters for the real (unmocked) runtime call, not for these tests' pass/fail.

- [x] **Step 1: Fix the dead branch**

In `context.py`, replace:

```python
        btc_candles = list(state.candles_15m) if hasattr(self, '_use_state_attr') else list(self.state.candles_15m)
```

with:

```python
        btc_candles = list(self.state.candles_15m)
```

- [x] **Step 2: Fix the yfinance MultiIndex bug**

In `context.py`, replace:

```python
        loop = asyncio.get_event_loop()
        spy_data = await loop.run_in_executor(
            None,
            lambda: yf.download("SPY", period="1d", interval="15m", progress=False, auto_adjust=True),
        )
```

with:

```python
        loop = asyncio.get_event_loop()
        spy_data = await loop.run_in_executor(
            None,
            lambda: yf.download(
                "SPY", period="1d", interval="15m", progress=False,
                auto_adjust=True, multi_level_index=False,
            ),
        )
```

- [x] **Step 3: Run the full existing suite to confirm no regression**

Run: `.venv/bin/pytest -q`
Expected: `36 passed` (unchanged baseline — these two fixes don't change any existing test's behavior).

- [x] **Step 4: Commit the fixes**

```bash
git add context.py
git commit -m "Fix dead branch and yfinance MultiIndex bug in context.py"
```

- [x] **Step 5: Write the full test file**

```python
import asyncio
import sys

import pandas as pd
import pytest
import yfinance as yf

from config import CORRELATION_BLOCK_THRESHOLD
from context import MacroFilter, _pearson, update_mtf_trends
from state import Candle, MarketState, Side


def _candle(close: float, index: int = 0) -> Candle:
    return Candle(open=close, high=close, low=close, close=close, volume=0.0, timestamp=index * 900_000)


def _fake_download(closes):
    def fake(*args, **kwargs):
        return pd.DataFrame({"Close": closes})
    return fake


def test_update_mtf_trends_15m_goes_long_above_dead_zone():
    state = MarketState()
    state.ema_15m = 100.0
    state.trend_15m = None
    state.last_price = 100.06

    update_mtf_trends(state)

    assert state.trend_15m == Side.LONG


def test_update_mtf_trends_15m_unchanged_inside_dead_zone():
    state = MarketState()
    state.ema_15m = 100.0
    state.trend_15m = Side.LONG
    state.last_price = 100.0

    update_mtf_trends(state)

    assert state.trend_15m == Side.LONG


def test_update_mtf_trends_15m_goes_short_below_dead_zone():
    state = MarketState()
    state.ema_15m = 100.0
    state.trend_15m = None
    state.last_price = 99.9

    update_mtf_trends(state)

    assert state.trend_15m == Side.SHORT


def test_update_mtf_trends_5m_goes_long_above_dead_zone():
    state = MarketState()
    state.ema_5m = 100.0
    state.trend_5m = None
    state.last_price = 100.04

    update_mtf_trends(state)

    assert state.trend_5m == Side.LONG


def test_update_mtf_trends_5m_unchanged_inside_dead_zone():
    state = MarketState()
    state.ema_5m = 100.0
    state.trend_5m = Side.SHORT
    state.last_price = 100.0

    update_mtf_trends(state)

    assert state.trend_5m == Side.SHORT


def test_update_mtf_trends_5m_goes_short_below_dead_zone():
    state = MarketState()
    state.ema_5m = 100.0
    state.trend_5m = None
    state.last_price = 99.96

    update_mtf_trends(state)

    assert state.trend_5m == Side.SHORT


def test_pearson_perfectly_correlated_series_returns_one():
    assert _pearson([1.0, 2.0, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0]) == pytest.approx(1.0)


def test_pearson_perfectly_anticorrelated_series_returns_minus_one():
    assert _pearson([1.0, 2.0, 3.0, 4.0], [8.0, 6.0, 4.0, 2.0]) == pytest.approx(-1.0)


def test_pearson_zero_variance_series_returns_zero():
    assert _pearson([1.0, 2.0, 3.0, 4.0], [5.0, 5.0, 5.0, 5.0]) == 0.0


def test_pearson_below_minimum_sample_size_returns_zero():
    assert _pearson([1.0], [2.0]) == 0.0


def test_macro_filter_blocks_longs_on_high_correlation_and_spy_down(monkeypatch):
    spy_closes = [100.0, 100.0, 99.0, 98.0, 97.0, 96.0]
    btc_closes = [50000.0, 50000.0, 49000.0, 48010.10101010101, 47030.30303030303, 46060.606060606064]
    state = MarketState()
    for i, close in enumerate(btc_closes):
        state.candles_15m.append(_candle(close, i))
    monkeypatch.setattr(yf, "download", _fake_download(spy_closes))

    asyncio.run(MacroFilter(state)._update())

    assert state.macro_blocks_longs is True
    assert state.macro_blocks_shorts is False


def test_macro_filter_blocks_shorts_on_high_correlation_and_spy_up(monkeypatch):
    spy_closes = [100.0, 100.0, 101.0, 102.0, 103.0, 104.0]
    btc_closes = [50000.0, 50000.0, 51000.0, 52009.90099009901, 53029.70297029703, 54059.405940594064]
    state = MarketState()
    for i, close in enumerate(btc_closes):
        state.candles_15m.append(_candle(close, i))
    monkeypatch.setattr(yf, "download", _fake_download(spy_closes))

    asyncio.run(MacroFilter(state)._update())

    assert state.macro_blocks_shorts is True
    assert state.macro_blocks_longs is False


def test_macro_filter_no_flags_on_low_correlation(monkeypatch):
    spy_closes = [100.0, 100.0, 99.0, 98.0, 97.0, 96.0]
    btc_closes = [50000.0] * 6  # flat closes -> zero variance -> _pearson returns 0.0
    state = MarketState()
    for i, close in enumerate(btc_closes):
        state.candles_15m.append(_candle(close, i))
    monkeypatch.setattr(yf, "download", _fake_download(spy_closes))

    asyncio.run(MacroFilter(state)._update())

    assert state.macro_blocks_longs is False
    assert state.macro_blocks_shorts is False


def test_macro_filter_returns_early_without_touching_flags_when_too_few_spy_closes(monkeypatch):
    state = MarketState()
    state.macro_blocks_longs = True
    state.macro_blocks_shorts = True
    for i in range(6):
        state.candles_15m.append(_candle(50000.0, i))
    monkeypatch.setattr(yf, "download", _fake_download([100.0] * 5))  # only 5 closes

    asyncio.run(MacroFilter(state)._update())

    assert state.macro_blocks_longs is True
    assert state.macro_blocks_shorts is True


def test_macro_filter_returns_early_without_touching_flags_when_too_few_btc_candles(monkeypatch):
    state = MarketState()
    state.macro_blocks_longs = True
    state.macro_blocks_shorts = True
    for i in range(5):  # fewer than 6 closed 15m candles
        state.candles_15m.append(_candle(50000.0, i))
    monkeypatch.setattr(yf, "download", _fake_download([100.0] * 6))

    asyncio.run(MacroFilter(state)._update())

    assert state.macro_blocks_longs is True
    assert state.macro_blocks_shorts is True


def test_macro_filter_yfinance_unavailable_skips_without_raising_and_does_not_retry(monkeypatch):
    state = MarketState()
    mf = MacroFilter(state)
    monkeypatch.setitem(sys.modules, "yfinance", None)

    asyncio.run(mf._update())  # must not raise

    assert mf._yfinance_available is False

    monkeypatch.setitem(sys.modules, "yfinance", yf)
    called = {"hit": False}

    def fake_download(*args, **kwargs):
        called["hit"] = True
        return pd.DataFrame({"Close": [1.0] * 6})

    monkeypatch.setattr(yf, "download", fake_download)
    for i in range(6):
        state.candles_15m.append(_candle(1.0, i))

    asyncio.run(mf._update())  # should short-circuit on _yfinance_available, not reattempt import

    assert called["hit"] is False
```

- [x] **Step 6: Run the new tests**

Run: `.venv/bin/pytest tests/test_context.py -v`
Expected: `16 passed`.

- [x] **Step 7: Commit**

```bash
git add tests/test_context.py
git commit -m "Add unit tests for context.py"
```

---

### Task 7: Full-suite verification

**Files:** none (verification only)

- [x] **Step 1: Run the entire test suite**

Run: `.venv/bin/pytest -q`
Expected: `120 passed` (36 baseline + 9 indicators + 7 momentum + 11 order_flow + 24 regime + 17 new signals + 16 context = 120).

- [x] **Step 2: If the count doesn't match, investigate before moving on**

Diff the actual `pytest -v` output against the expected test names listed in Tasks 1–6's "Step 2/6" blocks above to find which test is missing, duplicated, or unexpectedly failing — do not just re-run and hope.
