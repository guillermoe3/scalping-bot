# Backtesting Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI backtesting tool (`backtest.py`) that replays real historical BTC/USDT data (Binance, via `ccxt`) through the bot's existing, untouched strategy logic — producing a trade log CSV and a console summary — without duplicating any decision logic from `main.py`/`risk.py`/`signals.py`/etc.

**Architecture:** Per `docs/superpowers/specs/2026-06-18-backtesting-design.md`. A new `clock` module makes the bot's time-dependent logic (entry time, time-exit, momentum-abort, daily kill-switch reset) simulation-aware with zero change to default (live) behavior. A new `BacktestFeed` fetches and caches historical klines (1m, resampled locally to 5m/15m) and real trades via `ccxt`, then replays them chronologically through the same handlers `main.py` wires up today (extracted into a reusable `wire_strategy` function). `ExecutionEngine` gains an optional trade-close hook to capture a trade log. A new `backtest_report.py` computes summary stats and writes the CSV.

**Tech Stack:** Python 3.12, `ccxt` (already a dependency), `asyncio`, pytest. No new dependencies.

## Global Constraints

- Run tests with `.venv/bin/pytest` from the repo root (`/home/guille/dev/scalping-bot`).
- Test files live at `tests/test_<module>.py`, no `__init__.py`.
- Never mock the function under test. The only I/O boundary mocked is `ccxt`'s exchange object (`fetch_ohlcv`/`fetch_trades`), via a fake exchange class passed into `BacktestFeed`/`backtest.main()` — same pattern already used for `safety.reconcile_with_exchange`'s `_FakeExchange` in `tests/test_safety.py`.
- Do not add new dependencies.
- `clock.now()`/`clock.today_utc()` must default to real wall-clock behavior identical to today's `time.time()`/`datetime.now(timezone.utc)` — every test that already passes before this plan must keep passing unmodified throughout every task (the baseline grows as each task adds tests; verify the full suite at the end of every task, not just the new file).
- Baseline before this plan: confirm in Task 0 by running the full suite — call that count `N`. Every later task's "run full suite" step expects `N` plus that task's new tests, never fewer.
- Commit after every task.

---

### Task 0: Confirm the baseline

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite and record the baseline count**

Run: `.venv/bin/pytest -q`
Expected: some number `N` of tests passing, zero failing. Write down `N`.

---

### Task 1: The simulated clock (`clock.py`)

**Files:**
- Create: `clock.py`
- Create: `tests/test_clock.py`

**Interfaces:**
- Produces: `clock.now() -> float`, `clock.today_utc() -> str`, `clock.set_now(ts: float) -> None`, `clock.reset() -> None`. Tasks 2, 5, 8 depend on these.

- [ ] **Step 1: Write the failing test file**

Create `tests/test_clock.py`:

```python
import time

import pytest

import clock


@pytest.fixture(autouse=True)
def _reset_clock():
    yield
    clock.reset()


def test_now_defaults_to_real_wall_clock():
    before = time.time()
    result = clock.now()
    after = time.time()

    assert before <= result <= after


def test_set_now_overrides_now():
    clock.set_now(1700000000.0)

    assert clock.now() == 1700000000.0


def test_reset_clears_the_override():
    clock.set_now(1700000000.0)
    clock.reset()

    before = time.time()
    result = clock.now()
    after = time.time()
    assert before <= result <= after


def test_today_utc_derives_the_date_from_now():
    clock.set_now(1700000000.0)  # 2023-11-14T22:13:20Z

    assert clock.today_utc() == "2023-11-14"


def test_today_utc_respects_the_date_boundary():
    clock.set_now(1700524799.0)  # 2023-11-20T23:59:59Z
    assert clock.today_utc() == "2023-11-20"

    clock.set_now(1700524800.0)  # 2023-11-21T00:00:00Z
    assert clock.today_utc() == "2023-11-21"
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `.venv/bin/pytest tests/test_clock.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clock'`.

- [ ] **Step 3: Implement clock.py**

Create `clock.py`:

```python
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

_override: Optional[float] = None


def now() -> float:
    """Unix seconds. Returns time.time() unless a backtest has pinned a
    simulated time with set_now()."""
    return _override if _override is not None else time.time()


def today_utc() -> str:
    return datetime.fromtimestamp(now(), tz=timezone.utc).date().isoformat()


def set_now(ts: float) -> None:
    """Backtest-only: pins now() to a simulated timestamp."""
    global _override
    _override = ts


def reset() -> None:
    global _override
    _override = None
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `.venv/bin/pytest tests/test_clock.py -v`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add clock.py tests/test_clock.py
git commit -m "Add simulated clock module for backtest time injection"
```

---

### Task 2: Inject the clock into risk.py, momentum.py, safety.py

**Files:**
- Modify: `risk.py:1-19` (imports), `risk.py:66` (`entry_time`), `risk.py:251` (`held_min`)
- Modify: `momentum.py:1-9` (imports), `momentum.py:20`, `momentum.py:36`
- Modify: `safety.py:1-17` (imports), `safety.py:20-21` (`_today_utc`)
- Modify: `tests/test_risk.py`, `tests/test_momentum.py`, `tests/test_safety.py` (append tests)

**Interfaces:**
- Consumes: `clock.now()`, `clock.today_utc()` (Task 1).
- Produces: no public signature changes anywhere. Existing callers (`main.py`, `execution.py`) are unaffected.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_risk.py` (add `import clock` to the top imports, alongside the existing `import safety`):

```python


def test_open_position_uses_clock_for_entry_time(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: 1700000000.0)
    state = MarketState()
    state.atr = 2.0
    state.last_price = 100.0

    open_position(state, Side.LONG, 100.0)

    assert state.position.entry_time == 1700000000.0


def test_manage_position_time_exit_uses_clock_for_held_minutes(monkeypatch):
    from config import TIME_EXIT_MINUTES

    monkeypatch.setattr(clock, "now", lambda: 1700000000.0)
    state = _state_with_long_position(entry=100.0)
    state.position.entry_time = 1700000000.0 - TIME_EXIT_MINUTES * 60 - 1
    state.last_price = state.position.entry_price  # nowhere near SL/TP

    from risk import manage_position
    tp1_close_size, reason = manage_position(state)

    assert reason == "time_exit"
```

Append to `tests/test_momentum.py` (add `import clock` to the top imports):

```python


def test_update_volume_velocity_uses_clock_not_real_time(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: 1000.0)
    state = MarketState()
    state.live_1m = Candle(open=1.0, high=1.0, low=1.0, close=1.0, volume=10.0, timestamp=995_000.0)

    update_volume_velocity(state)

    assert state.volume_velocity == pytest.approx(2.0)


def test_should_abort_for_momentum_uses_clock_for_held_seconds(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: 1000.0)
    state = MarketState()
    state.position = _position(entry_time=1000.0 - MOMENTUM_ABORT_MINUTES * 60 - 10)
    state.prior_volume_velocity = 10.0
    state.volume_velocity = 2.0  # ratio 0.2 < 0.30 collapse threshold

    assert should_abort_for_momentum(state) is True
```

Append to `tests/test_safety.py` (add `import clock` to the top imports):

```python


def test_today_utc_delegates_to_clock(monkeypatch):
    monkeypatch.setattr(clock, "today_utc", lambda: "2030-01-01")

    assert safety._today_utc() == "2030-01-01"
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `.venv/bin/pytest tests/test_risk.py tests/test_momentum.py tests/test_safety.py -v -k "clock or uses_clock"`
Expected: FAIL — `test_open_position_uses_clock_for_entry_time` and `test_manage_position_time_exit_uses_clock_for_held_minutes` fail because `state.position.entry_time`/the time-exit gate still use the real wall clock, not the monkeypatched `clock.now`; same for the momentum tests; `test_today_utc_delegates_to_clock` fails because `safety._today_utc()` still calls `datetime.now()` directly, ignoring the monkeypatched `clock.today_utc`.

- [ ] **Step 3: Modify risk.py**

Replace the imports (currently lines 1-19):

```python
from __future__ import annotations

import logging
from typing import Optional

import clock
import safety
from config import (
    ACCOUNT_RISK_PCT,
    ATR_BREATHING_THRESHOLD,
    BREAKEVEN_ATR_TRIGGER,
    INITIAL_SL_ATR,
    TAKER_FEE_RATE,
    TIME_EXIT_MINUTES,
    TP1_CLOSE_PCT,
    TP1_RR,
)
from indicators import detect_swing_points
from state import MarketState, Position, Side
```

Line 66, replace:
```python
        entry_time=time.time(),
```
with:
```python
        entry_time=clock.now(),
```

Line 251, replace:
```python
    held_min = (time.time() - pos.entry_time) / 60.0
```
with:
```python
    held_min = (clock.now() - pos.entry_time) / 60.0
```

- [ ] **Step 4: Modify momentum.py**

Replace the imports (currently lines 1-9):

```python
from __future__ import annotations

import logging

import clock
from config import MOMENTUM_ABORT_MINUTES
from state import MarketState
```

Line 20, replace:
```python
    elapsed = (time.time() * 1000.0 - live.timestamp) / 1000.0
```
with:
```python
    elapsed = (clock.now() * 1000.0 - live.timestamp) / 1000.0
```

Line 36, replace:
```python
    held_seconds = time.time() - pos.entry_time
```
with:
```python
    held_seconds = clock.now() - pos.entry_time
```

- [ ] **Step 5: Modify safety.py**

Replace the imports (currently lines 1-17):

```python
from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict
from typing import Optional

import clock
from config import (
    KILL_SWITCH_CONSECUTIVE_LOSSES,
    KILL_SWITCH_DAILY_LOSS_PCT,
    STATE_FILE_PATH,
)
from state import MarketState, Position, Side

logger = logging.getLogger(__name__)
```

Replace (currently lines 20-21):
```python
def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()
```
with:
```python
def _today_utc() -> str:
    return clock.today_utc()
```

- [ ] **Step 6: Run the tests, verify they pass**

Run: `.venv/bin/pytest tests/test_risk.py tests/test_momentum.py tests/test_safety.py -v`
Expected: all pass (existing tests in these three files unaffected, plus the 4 new ones).

- [ ] **Step 7: Run the full suite to confirm no regression**

Run: `.venv/bin/pytest -q`
Expected: `N + 9` passed (5 from Task 1's `test_clock.py` + 4 new here), zero failed.

- [ ] **Step 8: Commit**

```bash
git add risk.py momentum.py safety.py tests/test_risk.py tests/test_momentum.py tests/test_safety.py
git commit -m "Inject the simulated clock into risk, momentum, and safety time logic"
```

---

### Task 3: Extract `update_live_candles` from `data_feed.py`

**Files:**
- Modify: `data_feed.py:99-122` (`_handle_trade`, `_update_live_candles`)
- Create: `tests/test_data_feed.py`

**Interfaces:**
- Produces: `update_live_candles(state: MarketState, price: float, qty: float) -> None` (module-level function in `data_feed.py`). Task 8 (`BacktestFeed`) imports and reuses this — the live feed and the backtest feed share the exact same forming-candle update logic, never duplicated.

- [ ] **Step 1: Write the failing test file**

Create `tests/test_data_feed.py`:

```python
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
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `.venv/bin/pytest tests/test_data_feed.py -v`
Expected: FAIL — `ImportError: cannot import name 'update_live_candles' from 'data_feed'`.

- [ ] **Step 3: Modify data_feed.py**

Replace (currently lines 99-122):

```python
    async def _handle_trade(self, d: dict) -> None:
        price = float(d["p"])
        qty = float(d["q"])
        is_buyer_maker: bool = d["m"]  # True → sell aggressor (hit bid)
        ts = d["T"] / 1000.0

        self.state.last_price = price
        self._update_live_candles(price, qty)

        # Running CVD: buy aggressor adds, sell aggressor subtracts
        if is_buyer_maker:
            self.state.cvd -= qty
        else:
            self.state.cvd += qty

        await self._emit(self._trade_handlers, price, qty, is_buyer_maker, ts)

    def _update_live_candles(self, price: float, qty: float) -> None:
        for live in (self.state.live_1m, self.state.live_5m, self.state.live_15m):
            if live is not None:
                live.high = max(live.high, price)
                live.low = min(live.low, price)
                live.close = price
                live.volume += qty
```

with:

```python
    async def _handle_trade(self, d: dict) -> None:
        price = float(d["p"])
        qty = float(d["q"])
        is_buyer_maker: bool = d["m"]  # True → sell aggressor (hit bid)
        ts = d["T"] / 1000.0

        self.state.last_price = price
        update_live_candles(self.state, price, qty)

        # Running CVD: buy aggressor adds, sell aggressor subtracts
        if is_buyer_maker:
            self.state.cvd -= qty
        else:
            self.state.cvd += qty

        await self._emit(self._trade_handlers, price, qty, is_buyer_maker, ts)
```

Add this module-level function near the top of `data_feed.py`, just after the `_Handler` type alias (currently line 17) and before the `class DataFeed:` line:

```python
def update_live_candles(state: MarketState, price: float, qty: float) -> None:
    for live in (state.live_1m, state.live_5m, state.live_15m):
        if live is not None:
            live.high = max(live.high, price)
            live.low = min(live.low, price)
            live.close = price
            live.volume += qty
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `.venv/bin/pytest tests/test_data_feed.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `.venv/bin/pytest -q`
Expected: `N + 13` passed (9 from Task 1+2, 4 new here), zero failed.

- [ ] **Step 6: Commit**

```bash
git add data_feed.py tests/test_data_feed.py
git commit -m "Extract update_live_candles from DataFeed into a reusable function"
```

---

### Task 4: Extract `wire_strategy` from `main.py`

**Files:**
- Modify: `main.py` (whole file)
- Create: `tests/test_main.py`

**Interfaces:**
- Consumes: `ExecutionEngine` (already existed).
- Produces: `wire_strategy(state: MarketState, feed, engine: ExecutionEngine) -> None`. `feed` only needs the registration interface (`on_trade`, `on_candle_1m`, `on_candle_5m`, `on_candle_15m`) — duck-typed, so both `DataFeed` (live) and `BacktestFeed` (Task 8) work. Task 10 (`backtest.py`) imports and calls this directly.

- [ ] **Step 1: Write the failing test file**

Create `tests/test_main.py`:

```python
import asyncio

from execution import ExecutionEngine
from main import wire_strategy
from state import MarketState


class _FakeFeed:
    def __init__(self):
        self.trade_handlers = []
        self.candle_1m_handlers = []
        self.candle_5m_handlers = []
        self.candle_15m_handlers = []

    def on_trade(self, fn):
        self.trade_handlers.append(fn)

    def on_candle_1m(self, fn):
        self.candle_1m_handlers.append(fn)

    def on_candle_5m(self, fn):
        self.candle_5m_handlers.append(fn)

    def on_candle_15m(self, fn):
        self.candle_15m_handlers.append(fn)


def test_wire_strategy_registers_one_handler_per_event_type():
    state = MarketState()
    feed = _FakeFeed()
    engine = ExecutionEngine(state)

    wire_strategy(state, feed, engine)

    assert len(feed.trade_handlers) == 1
    assert len(feed.candle_1m_handlers) == 1
    assert len(feed.candle_5m_handlers) == 1
    assert len(feed.candle_15m_handlers) == 1


def test_wire_strategy_on_trade_handler_runs_without_raising():
    state = MarketState()
    feed = _FakeFeed()
    engine = ExecutionEngine(state)
    wire_strategy(state, feed, engine)

    asyncio.run(feed.trade_handlers[0](100.0, 1.0, False, 0.0))  # must not raise


def test_wire_strategy_on_candle_1m_handler_updates_indicators():
    from state import Candle

    state = MarketState()
    for i in range(25):
        state.candles_1m.append(Candle(open=100.0 + i, high=101.0 + i, low=99.0 + i, close=100.0 + i, volume=1.0, timestamp=i * 60_000))
    feed = _FakeFeed()
    engine = ExecutionEngine(state)
    wire_strategy(state, feed, engine)

    closing_candle = Candle(open=125.0, high=126.0, low=124.0, close=125.0, volume=1.0, timestamp=25 * 60_000)
    asyncio.run(feed.candle_1m_handlers[0](closing_candle))

    assert state.atr > 0.0
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `.venv/bin/pytest tests/test_main.py -v`
Expected: FAIL — `ImportError: cannot import name 'wire_strategy' from 'main'`.

- [ ] **Step 3: Modify main.py**

Replace the entire file with:

```python
from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from context import MacroFilter, update_mtf_trends
from data_feed import DataFeed
from execution import ExecutionEngine, PAPER_MODE
from indicators import detect_swing_points, update_indicators
from momentum import update_volume_velocity
from order_flow import snapshot_cvd_on_close
from regime import update_mtf_trend, update_regime
import safety
from signals import check_entry_signal, update_squeeze
from state import Candle, MarketState

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-8s %(name)-16s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def wire_strategy(state: MarketState, feed, engine: ExecutionEngine) -> None:
    """Registers the strategy's event handlers against feed. feed can be
    DataFeed (live) or BacktestFeed (backtest) — it only needs to expose
    the same on_trade/on_candle_1m/on_candle_5m/on_candle_15m registration
    interface (duck typing, no shared base class)."""

    # -------------------------------------------------------------------------
    # Tick handler — runs on every trade event (sub-second)
    # -------------------------------------------------------------------------
    async def on_trade(price: float, qty: float, is_buyer_maker: bool, ts: float) -> None:
        update_volume_velocity(state)
        await engine.monitor_and_exit()

    # -------------------------------------------------------------------------
    # 1-minute candle close — primary signal evaluation clock
    # -------------------------------------------------------------------------
    async def on_candle_1m(candle: Candle) -> None:
        # 1. Snapshot CVD for this closed candle, reset for next
        snapshot_cvd_on_close(state)

        # 2. Recompute adaptive indicators (ATR, regime-aware EMA)
        update_indicators(state)

        # 3. Update regime state machine (hysteresis protected)
        update_regime(state)

        # 4. Update MTF trend bias from EMA slopes
        update_mtf_trend(state)
        update_mtf_trends(state)

        # 5. Refresh structural swing points
        highs, lows = detect_swing_points(state.candles_1m)
        state.swing_highs.clear()
        state.swing_highs.extend(highs)
        state.swing_lows.clear()
        state.swing_lows.extend(lows)

        # 6. Evaluate squeeze state
        update_squeeze(state)

        # 7. Check for entry signal (only if flat and kill switch is not active)
        if state.position is None and safety.can_open_new_position(state):
            signal = check_entry_signal(state)
            if signal is not None:
                await engine.enter(signal)

        logger.debug(
            "1m | close=%.2f atr=%.2f ema=%.2f regime=%s trend15=%s squeeze=%s",
            candle.close,
            state.atr,
            state.ema,
            state.regime.value,
            state.trend_15m.value if state.trend_15m else "?",
            state.in_squeeze,
        )

    # -------------------------------------------------------------------------
    # 5m candle close — MTF indicator refresh
    # -------------------------------------------------------------------------
    async def on_candle_5m(candle: Candle) -> None:
        update_indicators(state)
        update_mtf_trend(state)

    # -------------------------------------------------------------------------
    # 15m candle close — highest context update
    # -------------------------------------------------------------------------
    async def on_candle_15m(candle: Candle) -> None:
        update_indicators(state)
        update_mtf_trend(state)
        logger.info(
            "15m | close=%.2f ema15=%.2f trend=%s",
            candle.close,
            state.ema_15m,
            state.trend_15m.value if state.trend_15m else "?",
        )

    feed.on_trade(on_trade)
    feed.on_candle_1m(on_candle_1m)
    feed.on_candle_5m(on_candle_5m)
    feed.on_candle_15m(on_candle_15m)


async def run() -> None:
    state = MarketState()
    safety.load_into_state(state)

    feed = DataFeed(state)
    engine = ExecutionEngine(state)
    macro = MacroFilter(state)

    if not PAPER_MODE:
        safety.reconcile_with_exchange(state, engine.exchange)

    wire_strategy(state, feed, engine)

    mode = "PAPER" if os.getenv("PAPER_MODE", "true").lower() == "true" else "LIVE"
    logger.info("BTC Scalping Bot starting — mode=%s", mode)

    await asyncio.gather(
        feed.connect(),
        macro.run(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
        sys.exit(0)
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `.venv/bin/pytest tests/test_main.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Verify main.py still imports and runs cleanly in paper mode**

```bash
.venv/bin/python -c "import main"
```
Expected: no output, exit code 0.

```bash
timeout 10 .venv/bin/python main.py; echo "exit code: $?"
```
Expected: logs show `BTC Scalping Bot starting — mode=PAPER` and `WebSocket connected to Binance`, then killed by `timeout` (exit code 124) — confirms the refactor didn't break the live entry point.

- [ ] **Step 6: Run the full suite to confirm no regression**

Run: `.venv/bin/pytest -q`
Expected: `N + 16` passed (13 from Tasks 1-3, 3 new here), zero failed.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "Extract wire_strategy from main.py for reuse by the backtest harness"
```

---

### Task 5: `on_trade_closed` hook on `ExecutionEngine`

**Files:**
- Modify: `execution.py:1-50` (imports, `__init__`), `execution.py:77-115` (`exit`, `partial_exit`)
- Modify: `tests/test_execution.py` (append tests)

**Interfaces:**
- Consumes: `clock.now()` (Task 1).
- Produces: `ExecutionEngine.__init__(state, on_trade_closed: Optional[Callable[[dict], None]] = None)`. The dict shape: `{"side", "entry_price", "exit_price", "size", "reason", "leg_net", "total_trade_net", "fees_paid", "entry_time", "exit_time", "is_partial"}`. Task 10 (`backtest.py`) passes a list-builder callback here to capture the trade log.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_execution.py`:

```python


def test_exit_calls_on_trade_closed_hook_with_full_trade_details():
    state = _state_with_book(bid=99.0, ask=101.0)
    captured = []
    engine = ExecutionEngine(state, on_trade_closed=captured.append)
    asyncio.run(engine.enter(Side.LONG))
    entry_price = state.position.entry_price
    size = state.position.size

    net = asyncio.run(engine.exit("time_exit"))

    assert len(captured) == 1
    record = captured[0]
    assert record["side"] == Side.LONG
    assert record["entry_price"] == pytest.approx(entry_price)
    assert record["exit_price"] == pytest.approx(99.0)
    assert record["size"] == pytest.approx(size)
    assert record["reason"] == "time_exit"
    assert record["leg_net"] == pytest.approx(net)
    assert record["total_trade_net"] is not None
    assert record["is_partial"] is False


def test_partial_exit_calls_on_trade_closed_hook_with_leg_size_not_remaining_size():
    state = _state_with_book(bid=99.0, ask=101.0)
    captured = []
    engine = ExecutionEngine(state, on_trade_closed=captured.append)
    asyncio.run(engine.enter(Side.LONG))
    close_size = round(state.position.size * 0.5, 6)

    asyncio.run(engine.partial_exit(close_size, "tp1"))

    assert len(captured) == 1
    record = captured[0]
    assert record["size"] == pytest.approx(close_size)  # the closed leg, not the remainder
    assert record["is_partial"] is True
    assert record["total_trade_net"] is None


def test_on_trade_closed_defaults_to_none_and_does_not_raise():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)  # no on_trade_closed passed
    asyncio.run(engine.enter(Side.LONG))

    asyncio.run(engine.exit("time_exit"))  # must not raise
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `.venv/bin/pytest tests/test_execution.py -v -k on_trade_closed`
Expected: FAIL — `TypeError: ExecutionEngine.__init__() got an unexpected keyword argument 'on_trade_closed'`.

- [ ] **Step 3: Modify execution.py**

Replace the imports (currently lines 1-13):

```python
from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, Optional

import clock
from risk import apply_partial_close, close_position, manage_position, open_position
from state import MarketState, Side

logger = logging.getLogger(__name__)

PAPER_MODE: bool = os.getenv("PAPER_MODE", "true").lower() == "true"
```

Replace `__init__` (currently lines 28-32):

```python
    def __init__(self, state: MarketState, on_trade_closed: Optional[Callable[[dict], None]] = None) -> None:
        self.state = state
        self._exchange = None
        self._on_trade_closed = on_trade_closed
        if not PAPER_MODE:
            self._init_exchange()
```

Replace `exit` (currently lines 77-94):

```python
    async def exit(self, reason: str) -> float:
        if self.state.position is None:
            return 0.0

        pos = self.state.position
        fill_price = self.state.last_bid if pos.side == Side.LONG else self.state.last_ask

        if not (PAPER_MODE or self._exchange is None):
            try:
                order_side = "sell" if pos.side == Side.LONG else "buy"
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._exchange.create_market_order("BTC/USDT", order_side, pos.size),
                )
            except Exception:
                logger.exception("Live exit order failed")

        side, entry_price, size, entry_time = pos.side, pos.entry_price, pos.size, pos.entry_time
        net = close_position(self.state, fill_price, reason)

        if self._on_trade_closed is not None:
            self._on_trade_closed({
                "side": side, "entry_price": entry_price, "exit_price": fill_price,
                "size": size, "reason": reason, "leg_net": net,
                "total_trade_net": pos.realized_pnl, "fees_paid": pos.fees_paid,
                "entry_time": entry_time, "exit_time": clock.now(), "is_partial": False,
            })

        return net
```

Replace `partial_exit` (currently lines 96-115):

```python
    async def partial_exit(self, close_size: float, reason: str) -> float:
        pos = self.state.position
        if pos is None:
            return 0.0

        fill_price = self.state.last_bid if pos.side == Side.LONG else self.state.last_ask

        if not (PAPER_MODE or self._exchange is None):
            try:
                order_side = "sell" if pos.side == Side.LONG else "buy"
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._exchange.create_market_order(
                        "BTC/USDT", order_side, close_size, params={"reduceOnly": True},
                    ),
                )
            except Exception:
                logger.exception("Live partial-exit order failed")

        side, entry_price, entry_time = pos.side, pos.entry_price, pos.entry_time
        net = apply_partial_close(self.state, close_size, fill_price)

        if self._on_trade_closed is not None:
            self._on_trade_closed({
                "side": side, "entry_price": entry_price, "exit_price": fill_price,
                "size": close_size, "reason": reason, "leg_net": net,
                "total_trade_net": None, "fees_paid": pos.fees_paid,
                "entry_time": entry_time, "exit_time": clock.now(), "is_partial": True,
            })

        return net
```

Note: in `exit()`, `pos.size` is read **before** `close_position` is called and stored in the local `size` — `close_position` never mutates `pos.size` itself (it discards the whole position), so this is the size that was closed. In `partial_exit()`, the hook reports the `close_size` **parameter**, not `pos.size` — `apply_partial_close` shrinks `pos.size` to the remainder, so reading it after the call would report what's left open, not what was closed.

- [ ] **Step 4: Run the tests, verify they pass**

Run: `.venv/bin/pytest tests/test_execution.py -v`
Expected: all pass (existing 6 + 3 new = 9).

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `.venv/bin/pytest -q`
Expected: `N + 19` passed (16 from Tasks 1-4, 3 new here), zero failed.

- [ ] **Step 6: Commit**

```bash
git add execution.py tests/test_execution.py
git commit -m "Add on_trade_closed hook to ExecutionEngine for trade-log capture"
```

---

### Task 6: Historical data fetch + local cache (`backtest_feed.py`)

**Files:**
- Modify: `config.py` (append `BACKTEST_SYNTHETIC_SPREAD_PCT`)
- Modify: `.gitignore` (append `backtest_cache/`)
- Create: `backtest_feed.py`
- Create: `tests/test_backtest_feed.py`

**Interfaces:**
- Produces: `backtest_feed.CACHE_DIR` (module-level constant, str), `fetch_klines_1m(exchange, symbol: str, start_ms: int, end_ms: int, use_cache: bool = True) -> List[list]`, `fetch_trades(exchange, symbol: str, start_ms: int, end_ms: int, use_cache: bool = True) -> List[dict]`. `exchange` only needs ccxt-shaped `fetch_ohlcv(symbol, timeframe, since=None, limit=None)` and `fetch_trades(symbol, since=None, limit=None)` methods — tests use a fake. Tasks 8 and 10 depend on these.

- [ ] **Step 1: Append the config constant**

In `config.py`, after the `SPREAD_FILTER_ATR_PCT` line at the end of the file, add:

```python

# Backtesting
BACKTEST_SYNTHETIC_SPREAD_PCT = 0.0001  # 0.01% of price per side — no real historical order book data exists
```

- [ ] **Step 2: Add the cache directory to .gitignore**

In `.gitignore`, append:

```
backtest_cache/
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_backtest_feed.py`:

```python
import os

import pytest

import backtest_feed
from backtest_feed import fetch_klines_1m, fetch_trades


class _FakeExchange:
    def __init__(self, klines=None, trades=None, page_size=1000):
        self._klines = klines or []
        self._trades = trades or []
        self._page_size = page_size
        self.fetch_ohlcv_calls = 0
        self.fetch_trades_calls = 0

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.fetch_ohlcv_calls += 1
        batch = [k for k in self._klines if k[0] >= since]
        return batch[: self._page_size]

    def fetch_trades(self, symbol, since=None, limit=None):
        self.fetch_trades_calls += 1
        batch = [t for t in self._trades if t["timestamp"] >= since]
        return batch[: self._page_size]


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(backtest_feed, "CACHE_DIR", str(tmp_path / "cache"))


def test_fetch_klines_1m_returns_klines_within_range():
    klines = [[i * 60_000, 100.0, 101.0, 99.0, 100.5, 1.0] for i in range(5)]
    exchange = _FakeExchange(klines=klines)

    result = fetch_klines_1m(exchange, "BTC/USDT", start_ms=0, end_ms=5 * 60_000)

    assert result == klines


def test_fetch_klines_1m_paginates_across_multiple_calls():
    klines = [[i * 60_000, 100.0, 101.0, 99.0, 100.5, 1.0] for i in range(5)]
    exchange = _FakeExchange(klines=klines, page_size=2)

    result = fetch_klines_1m(exchange, "BTC/USDT", start_ms=0, end_ms=5 * 60_000)

    assert result == klines
    assert exchange.fetch_ohlcv_calls == 3


def test_fetch_klines_1m_caches_to_disk_and_skips_second_fetch():
    klines = [[i * 60_000, 100.0, 101.0, 99.0, 100.5, 1.0] for i in range(5)]
    exchange = _FakeExchange(klines=klines)

    fetch_klines_1m(exchange, "BTC/USDT", start_ms=0, end_ms=5 * 60_000)
    fetch_klines_1m(exchange, "BTC/USDT", start_ms=0, end_ms=5 * 60_000)

    assert exchange.fetch_ohlcv_calls == 1


def test_fetch_klines_1m_no_cache_forces_refetch():
    klines = [[i * 60_000, 100.0, 101.0, 99.0, 100.5, 1.0] for i in range(5)]
    exchange = _FakeExchange(klines=klines)

    fetch_klines_1m(exchange, "BTC/USDT", start_ms=0, end_ms=5 * 60_000)
    fetch_klines_1m(exchange, "BTC/USDT", start_ms=0, end_ms=5 * 60_000, use_cache=False)

    assert exchange.fetch_ohlcv_calls == 2


def test_fetch_trades_returns_trades_within_range():
    trades = [{"timestamp": i * 1000, "price": 100.0 + i, "amount": 1.0, "side": "buy"} for i in range(5)]
    exchange = _FakeExchange(trades=trades)

    result = fetch_trades(exchange, "BTC/USDT", start_ms=0, end_ms=5000)

    assert result == trades


def test_fetch_trades_paginates_across_multiple_calls():
    trades = [{"timestamp": i * 1000, "price": 100.0 + i, "amount": 1.0, "side": "buy"} for i in range(5)]
    exchange = _FakeExchange(trades=trades, page_size=2)

    result = fetch_trades(exchange, "BTC/USDT", start_ms=0, end_ms=5000)

    assert result == trades
    assert exchange.fetch_trades_calls == 3


def test_fetch_trades_caches_to_disk_and_skips_second_fetch():
    trades = [{"timestamp": i * 1000, "price": 100.0 + i, "amount": 1.0, "side": "buy"} for i in range(5)]
    exchange = _FakeExchange(trades=trades)

    fetch_trades(exchange, "BTC/USDT", start_ms=0, end_ms=5000)
    fetch_trades(exchange, "BTC/USDT", start_ms=0, end_ms=5000)

    assert exchange.fetch_trades_calls == 1


def test_write_cache_does_not_leave_a_partial_file_on_interrupted_write(monkeypatch):
    path = backtest_feed._cache_path("BTC/USDT", "klines1m", 0, 1000)

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(backtest_feed.json, "dump", _boom)

    with pytest.raises(OSError):
        backtest_feed._write_cache(path, [1, 2, 3])

    assert not os.path.exists(path)
```

- [ ] **Step 4: Run the tests, verify they fail**

Run: `.venv/bin/pytest tests/test_backtest_feed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backtest_feed'`.

- [ ] **Step 5: Implement the fetch + cache functions**

Create `backtest_feed.py`:

```python
from __future__ import annotations

import json
import os
from typing import List, Optional

CACHE_DIR = "backtest_cache"


def _cache_path(symbol: str, kind: str, start_ms: int, end_ms: int) -> str:
    safe_symbol = symbol.replace("/", "")
    return os.path.join(CACHE_DIR, f"{safe_symbol}_{kind}_{start_ms}_{end_ms}.json")


def _read_cache(path: str) -> Optional[list]:
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def _write_cache(path: str, data: list) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f)
    os.replace(tmp_path, path)


def fetch_klines_1m(exchange, symbol: str, start_ms: int, end_ms: int, use_cache: bool = True) -> List[list]:
    """Returns [timestamp_ms, open, high, low, close, volume] rows covering [start_ms, end_ms)."""
    path = _cache_path(symbol, "klines1m", start_ms, end_ms)
    if use_cache:
        cached = _read_cache(path)
        if cached is not None:
            return cached

    candles: List[list] = []
    since = start_ms
    while since < end_ms:
        batch = exchange.fetch_ohlcv(symbol, "1m", since=since, limit=1000)
        if not batch:
            break
        candles.extend(batch)
        last_ts = batch[-1][0]
        if last_ts <= since:
            break
        since = last_ts + 60_000

    candles = [c for c in candles if start_ms <= c[0] < end_ms]

    if use_cache:
        _write_cache(path, candles)
    return candles


def fetch_trades(exchange, symbol: str, start_ms: int, end_ms: int, use_cache: bool = True) -> List[dict]:
    """Returns ccxt-normalized trade dicts covering [start_ms, end_ms)."""
    path = _cache_path(symbol, "trades", start_ms, end_ms)
    if use_cache:
        cached = _read_cache(path)
        if cached is not None:
            return cached

    trades: List[dict] = []
    since = start_ms
    while since < end_ms:
        batch = exchange.fetch_trades(symbol, since=since, limit=1000)
        if not batch:
            break
        trades.extend(batch)
        last_ts = batch[-1]["timestamp"]
        if last_ts <= since:
            break
        since = last_ts + 1

    trades = [t for t in trades if start_ms <= t["timestamp"] < end_ms]

    if use_cache:
        _write_cache(path, trades)
    return trades
```

- [ ] **Step 6: Run the tests, verify they pass**

Run: `.venv/bin/pytest tests/test_backtest_feed.py -v`
Expected: `9 passed`.

- [ ] **Step 7: Run the full suite to confirm no regression**

Run: `.venv/bin/pytest -q`
Expected: `N + 28` passed (19 from Tasks 1-5, 9 new here), zero failed.

- [ ] **Step 8: Commit**

```bash
git add config.py .gitignore backtest_feed.py tests/test_backtest_feed.py
git commit -m "Add historical kline/trade fetching with local cache for backtesting"
```

---

### Task 7: Resample 1m klines into 5m/15m (`backtest_feed.py`)

**Files:**
- Modify: `backtest_feed.py` (append `resample`)
- Modify: `tests/test_backtest_feed.py` (append tests)

**Interfaces:**
- Produces: `resample(klines_1m: List[list], minutes: int) -> List[list]` (pure function, no I/O). Task 8 depends on this to build the 5m/15m candle history from a single 1m fetch.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backtest_feed.py`:

```python


from backtest_feed import resample


def test_resample_aggregates_five_one_minute_candles_into_one_5m_candle():
    klines_1m = [
        [0,       100.0, 102.0, 99.0,  101.0, 1.0],
        [60_000,  101.0, 103.0, 100.0, 102.0, 2.0],
        [120_000, 102.0, 104.0, 101.0, 103.0, 1.5],
        [180_000, 103.0, 105.0, 102.0, 104.0, 0.5],
        [240_000, 104.0, 106.0, 103.0, 105.0, 1.0],
    ]

    result = resample(klines_1m, minutes=5)

    assert result == [[0, 100.0, 106.0, 99.0, 105.0, 6.0]]


def test_resample_splits_into_separate_buckets_when_crossing_a_boundary():
    klines_1m = [
        [240_000, 104.0, 106.0, 103.0, 105.0, 1.0],  # last candle of bucket [0, 300000)
        [300_000, 105.0, 107.0, 104.0, 106.0, 2.0],  # first candle of the next bucket
    ]

    result = resample(klines_1m, minutes=5)

    assert result == [
        [240_000, 104.0, 106.0, 103.0, 105.0, 1.0],
        [300_000, 105.0, 107.0, 104.0, 106.0, 2.0],
    ]


def test_resample_returns_empty_list_for_empty_input():
    assert resample([], minutes=15) == []
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `.venv/bin/pytest tests/test_backtest_feed.py -v -k resample`
Expected: FAIL — `ImportError: cannot import name 'resample' from 'backtest_feed'`.

- [ ] **Step 3: Implement resample**

Append to `backtest_feed.py`:

```python


def resample(klines_1m: List[list], minutes: int) -> List[list]:
    """Aggregates 1m klines ([ts, o, h, l, c, v]) into `minutes`-minute
    buckets aligned to UTC minute-of-day boundaries — mathematically
    identical to what Binance's own 5m/15m klines would report, since 1m
    boundaries are a superset of every coarser grid."""
    if not klines_1m:
        return []

    bucket_ms = minutes * 60_000
    out: List[list] = []
    current_bucket_start: Optional[int] = None
    current: Optional[list] = None

    for ts, o, h, l, c, v in klines_1m:
        bucket_start = (ts // bucket_ms) * bucket_ms
        if bucket_start != current_bucket_start:
            if current is not None:
                out.append(current)
            current = [bucket_start, o, h, l, c, v]
            current_bucket_start = bucket_start
        else:
            current[2] = max(current[2], h)
            current[3] = min(current[3], l)
            current[4] = c
            current[5] += v

    if current is not None:
        out.append(current)

    return out
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `.venv/bin/pytest tests/test_backtest_feed.py -v`
Expected: `12 passed`.

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `.venv/bin/pytest -q`
Expected: `N + 31` passed (28 from Tasks 1-6, 3 new here), zero failed.

- [ ] **Step 6: Commit**

```bash
git add backtest_feed.py tests/test_backtest_feed.py
git commit -m "Add 1m-to-5m/15m kline resampling for backtesting"
```

---

### Task 8: Chronological replay (`BacktestFeed`)

**Files:**
- Modify: `backtest_feed.py` (top imports, append `BacktestFeed`)
- Modify: `tests/test_backtest_feed.py` (append tests)

**Interfaces:**
- Consumes: `clock.set_now()` (Task 1), `update_live_candles` (Task 3), `fetch_klines_1m`/`fetch_trades`/`resample` (Tasks 6-7), `config.BACKTEST_SYNTHETIC_SPREAD_PCT` (Task 6).
- Produces: `BacktestFeed(state: MarketState, exchange=None, spread_pct: float = BACKTEST_SYNTHETIC_SPREAD_PCT, use_cache: bool = True)` with `on_trade`, `on_candle_1m`, `on_candle_5m`, `on_candle_15m` registration methods (same interface as `DataFeed`) and `async def replay(self, start_ms: int, end_ms: int) -> None`. Task 10 (`backtest.py`) constructs this and calls `replay`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backtest_feed.py`:

```python


import asyncio

import clock
from backtest_feed import BacktestFeed
from state import MarketState


@pytest.fixture(autouse=True)
def _reset_clock():
    yield
    clock.reset()


async def _noop(*args):
    return None


def test_replay_fires_handlers_in_chronological_order():
    klines_1m = [
        [0,      100.0, 102.0, 99.0,  101.0, 2.0],
        [60_000, 101.0, 103.0, 100.0, 102.0, 3.0],
    ]
    trades = [
        {"timestamp": 10_000, "price": 100.5, "amount": 1.0, "side": "buy"},
        {"timestamp": 30_000, "price": 101.0, "amount": 1.0, "side": "sell"},
        {"timestamp": 70_000, "price": 101.5, "amount": 1.0, "side": "buy"},
        {"timestamp": 90_000, "price": 102.0, "amount": 1.0, "side": "buy"},
    ]
    exchange = _FakeExchange(klines=klines_1m, trades=trades)
    state = MarketState()
    feed = BacktestFeed(state, exchange=exchange, use_cache=False)

    fired = []

    async def on_trade(price, qty, is_sell, ts):
        fired.append(("trade", price))

    async def on_candle_1m(candle):
        fired.append(("candle_1m", candle.close))

    feed.on_trade(on_trade)
    feed.on_candle_1m(on_candle_1m)
    feed.on_candle_5m(_noop)
    feed.on_candle_15m(_noop)

    asyncio.run(feed.replay(start_ms=0, end_ms=120_000))

    assert fired == [
        ("trade", 100.5),
        ("trade", 101.0),
        ("candle_1m", 101.0),
        ("trade", 101.5),
        ("trade", 102.0),
        ("candle_1m", 102.0),
    ]


def test_replay_synthesizes_bid_ask_spread_from_price():
    klines_1m = [[0, 100.0, 100.0, 100.0, 100.0, 1.0]]
    trades = [{"timestamp": 10_000, "price": 100.0, "amount": 1.0, "side": "buy"}]
    exchange = _FakeExchange(klines=klines_1m, trades=trades)
    state = MarketState()
    feed = BacktestFeed(state, exchange=exchange, use_cache=False, spread_pct=0.001)

    seen = []

    async def on_trade(price, qty, is_sell, ts):
        seen.append((state.last_bid, state.last_ask, state.spread))

    feed.on_trade(on_trade)
    feed.on_candle_1m(_noop)
    feed.on_candle_5m(_noop)
    feed.on_candle_15m(_noop)

    asyncio.run(feed.replay(start_ms=0, end_ms=60_000))

    bid, ask, spread = seen[0]
    assert spread == pytest.approx(0.1)
    assert bid == pytest.approx(99.95)
    assert ask == pytest.approx(100.05)


def test_replay_updates_cvd_from_the_real_trade_side():
    klines_1m = [[0, 100.0, 100.0, 100.0, 100.0, 1.0]]
    trades = [
        {"timestamp": 10_000, "price": 100.0, "amount": 3.0, "side": "buy"},
        {"timestamp": 20_000, "price": 100.0, "amount": 1.0, "side": "sell"},
    ]
    exchange = _FakeExchange(klines=klines_1m, trades=trades)
    state = MarketState()
    feed = BacktestFeed(state, exchange=exchange, use_cache=False)
    feed.on_trade(_noop)
    feed.on_candle_1m(_noop)
    feed.on_candle_5m(_noop)
    feed.on_candle_15m(_noop)

    asyncio.run(feed.replay(start_ms=0, end_ms=60_000))

    assert state.cvd == pytest.approx(2.0)  # +3.0 (buy) - 1.0 (sell)


def test_replay_sets_the_simulated_clock_before_dispatching_each_event():
    klines_1m = [[0, 100.0, 100.0, 100.0, 100.0, 1.0]]
    trades = [{"timestamp": 10_000, "price": 100.0, "amount": 1.0, "side": "buy"}]
    exchange = _FakeExchange(klines=klines_1m, trades=trades)
    state = MarketState()
    feed = BacktestFeed(state, exchange=exchange, use_cache=False)

    seen = []

    async def on_trade(*args):
        seen.append(clock.now())

    feed.on_trade(on_trade)
    feed.on_candle_1m(_noop)
    feed.on_candle_5m(_noop)
    feed.on_candle_15m(_noop)

    asyncio.run(feed.replay(start_ms=0, end_ms=60_000))

    assert seen == [10.0]


def test_replay_resets_live_1m_after_each_candle_close():
    klines_1m = [
        [0,      100.0, 102.0, 99.0,  101.0, 2.0],
        [60_000, 101.0, 103.0, 100.0, 102.0, 3.0],
    ]
    trades = [
        {"timestamp": 10_000, "price": 100.5, "amount": 1.0, "side": "buy"},
        {"timestamp": 70_000, "price": 101.5, "amount": 1.0, "side": "buy"},
    ]
    exchange = _FakeExchange(klines=klines_1m, trades=trades)
    state = MarketState()
    feed = BacktestFeed(state, exchange=exchange, use_cache=False)

    closes_seen = []

    async def on_trade(*args):
        closes_seen.append(state.live_1m.close if state.live_1m else None)

    feed.on_trade(on_trade)
    feed.on_candle_1m(_noop)
    feed.on_candle_5m(_noop)
    feed.on_candle_15m(_noop)

    asyncio.run(feed.replay(start_ms=0, end_ms=120_000))

    assert closes_seen == [100.5, 101.5]
    assert state.live_1m is None
    assert len(state.candles_1m) == 2


def test_replay_raises_a_clear_error_when_no_klines_are_available():
    exchange = _FakeExchange(klines=[], trades=[])
    state = MarketState()
    feed = BacktestFeed(state, exchange=exchange, use_cache=False)
    feed.on_trade(_noop)
    feed.on_candle_1m(_noop)
    feed.on_candle_5m(_noop)
    feed.on_candle_15m(_noop)

    with pytest.raises(ValueError, match="No historical data available"):
        asyncio.run(feed.replay(start_ms=0, end_ms=60_000))
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `.venv/bin/pytest tests/test_backtest_feed.py -v -k replay`
Expected: FAIL — `ImportError: cannot import name 'BacktestFeed' from 'backtest_feed'`.

- [ ] **Step 3: Implement BacktestFeed**

Replace the top imports of `backtest_feed.py` (currently `from __future__ import annotations` through `CACHE_DIR = "backtest_cache"`) with:

```python
from __future__ import annotations

import json
import os
from typing import Awaitable, Callable, List, Optional

import clock
from config import BACKTEST_SYNTHETIC_SPREAD_PCT
from data_feed import update_live_candles
from state import Candle, MarketState

CACHE_DIR = "backtest_cache"

_Handler = Callable[..., Awaitable[None]]
```

`_cache_path`, `_read_cache`, `_write_cache`, `fetch_klines_1m`, `fetch_trades`, and `resample` all stay exactly as they are below this point.

Append at the end of `backtest_feed.py`:

```python


def _build_event_timeline(trades: List[dict], klines_1m: List[list], klines_5m: List[list], klines_15m: List[list]) -> List[dict]:
    events: List[dict] = []

    for t in trades:
        events.append({"type": "trade", "ts": t["timestamp"], "price": t["price"], "amount": t["amount"], "side": t["side"]})

    for klines, timeframe, period_ms in ((klines_1m, "1m", 60_000), (klines_5m, "5m", 5 * 60_000), (klines_15m, "15m", 15 * 60_000)):
        for ts, o, h, l, c, v in klines:
            events.append({
                "type": "candle_close", "ts": ts + period_ms, "timeframe": timeframe,
                "candle": Candle(open=o, high=h, low=l, close=c, volume=v, timestamp=ts),
            })

    events.sort(key=lambda e: (e["ts"], e["type"] == "candle_close"))
    return events


class BacktestFeed:
    """Replays historical Binance data (klines + real trades, via ccxt)
    through the same on_trade/on_candle_1m/5m/15m registration interface
    DataFeed exposes live, so main.wire_strategy works unchanged against
    either one."""

    def __init__(
        self,
        state: MarketState,
        exchange=None,
        spread_pct: float = BACKTEST_SYNTHETIC_SPREAD_PCT,
        use_cache: bool = True,
    ) -> None:
        self.state = state
        self._exchange = exchange if exchange is not None else _build_exchange()
        self._spread_pct = spread_pct
        self._use_cache = use_cache
        self._trade_handlers: List[_Handler] = []
        self._candle_1m_handlers: List[_Handler] = []
        self._candle_5m_handlers: List[_Handler] = []
        self._candle_15m_handlers: List[_Handler] = []
        self._bucket_1m: Optional[int] = None
        self._bucket_5m: Optional[int] = None
        self._bucket_15m: Optional[int] = None

    def on_trade(self, fn: _Handler) -> None:
        self._trade_handlers.append(fn)

    def on_candle_1m(self, fn: _Handler) -> None:
        self._candle_1m_handlers.append(fn)

    def on_candle_5m(self, fn: _Handler) -> None:
        self._candle_5m_handlers.append(fn)

    def on_candle_15m(self, fn: _Handler) -> None:
        self._candle_15m_handlers.append(fn)

    async def replay(self, start_ms: int, end_ms: int) -> None:
        klines_1m = fetch_klines_1m(self._exchange, "BTC/USDT", start_ms, end_ms, self._use_cache)
        if not klines_1m:
            raise ValueError(f"No historical data available for BTC/USDT between {start_ms} and {end_ms}")
        klines_5m = resample(klines_1m, 5)
        klines_15m = resample(klines_1m, 15)
        trades = fetch_trades(self._exchange, "BTC/USDT", start_ms, end_ms, self._use_cache)

        for event in _build_event_timeline(trades, klines_1m, klines_5m, klines_15m):
            clock.set_now(event["ts"] / 1000.0)
            if event["type"] == "trade":
                await self._handle_trade(event)
            else:
                await self._handle_candle_close(event)

    def _ensure_live_candle(self, live_attr: str, bucket_attr: str, ts_ms: int, bucket_size_ms: int, price: float) -> None:
        bucket_start = (ts_ms // bucket_size_ms) * bucket_size_ms
        if getattr(self, bucket_attr) != bucket_start:
            setattr(self.state, live_attr, Candle(open=price, high=price, low=price, close=price, volume=0.0, timestamp=bucket_start))
            setattr(self, bucket_attr, bucket_start)

    async def _handle_trade(self, event: dict) -> None:
        price = event["price"]
        qty = event["amount"]
        ts_ms = event["ts"]

        self._ensure_live_candle("live_1m", "_bucket_1m", ts_ms, 60_000, price)
        self._ensure_live_candle("live_5m", "_bucket_5m", ts_ms, 5 * 60_000, price)
        self._ensure_live_candle("live_15m", "_bucket_15m", ts_ms, 15 * 60_000, price)

        self.state.last_price = price
        spread = price * self._spread_pct
        self.state.last_bid = price - spread / 2
        self.state.last_ask = price + spread / 2
        self.state.spread = spread

        is_sell_aggressor = event["side"] == "sell"
        if is_sell_aggressor:
            self.state.cvd -= qty
        else:
            self.state.cvd += qty

        update_live_candles(self.state, price, qty)

        await self._emit(self._trade_handlers, price, qty, is_sell_aggressor, ts_ms / 1000.0)

    async def _handle_candle_close(self, event: dict) -> None:
        candle = event["candle"]
        tf = event["timeframe"]
        if tf == "1m":
            self.state.candles_1m.append(candle)
            self.state.live_1m = None
            await self._emit(self._candle_1m_handlers, candle)
        elif tf == "5m":
            self.state.candles_5m.append(candle)
            self.state.live_5m = None
            await self._emit(self._candle_5m_handlers, candle)
        else:
            self.state.candles_15m.append(candle)
            self.state.live_15m = None
            await self._emit(self._candle_15m_handlers, candle)

    async def _emit(self, handlers: List[_Handler], *args) -> None:
        for h in handlers:
            await h(*args)


def _build_exchange():
    import ccxt
    return ccxt.binance({"enableRateLimit": True})
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `.venv/bin/pytest tests/test_backtest_feed.py -v`
Expected: `18 passed`.

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `.venv/bin/pytest -q`
Expected: `N + 37` passed (31 from Tasks 1-7, 6 new here), zero failed.

- [ ] **Step 6: Commit**

```bash
git add backtest_feed.py tests/test_backtest_feed.py
git commit -m "Add BacktestFeed: chronological replay of historical klines and trades"
```

---

### Task 9: Summary stats and CSV (`backtest_report.py`)

**Files:**
- Create: `backtest_report.py`
- Create: `tests/test_backtest_report.py`

**Interfaces:**
- Produces: `compute_summary(trade_records: List[dict]) -> dict` (keys: `total_trades`, `win_rate`, `total_net_pnl`, `profit_factor`, `max_drawdown`, `max_consecutive_losses`), `write_trade_log_csv(trade_records: List[dict], path: str) -> None`. Both consume the dict shape produced by `ExecutionEngine`'s `on_trade_closed` hook (Task 5). Task 10 (`backtest.py`) calls both.

- [ ] **Step 1: Write the failing test file**

Create `tests/test_backtest_report.py`:

```python
import csv

import pytest

from backtest_report import compute_summary, write_trade_log_csv
from state import Side


def _full_close(net: float) -> dict:
    return {
        "side": Side.LONG, "entry_price": 100.0, "exit_price": 105.0, "size": 1.0,
        "reason": "time_exit", "leg_net": net, "total_trade_net": net,
        "fees_paid": 0.1, "entry_time": 0.0, "exit_time": 60.0, "is_partial": False,
    }


def _partial_leg() -> dict:
    return {
        "side": Side.LONG, "entry_price": 100.0, "exit_price": 110.0, "size": 0.5,
        "reason": "tp1", "leg_net": 5.0, "total_trade_net": None,
        "fees_paid": 0.05, "entry_time": 0.0, "exit_time": 30.0, "is_partial": True,
    }


def test_compute_summary_empty_list_returns_zeroed_summary():
    summary = compute_summary([])

    assert summary["total_trades"] == 0
    assert summary["win_rate"] == 0.0
    assert summary["total_net_pnl"] == 0.0
    assert summary["profit_factor"] == 0.0
    assert summary["max_drawdown"] == 0.0
    assert summary["max_consecutive_losses"] == 0


def test_compute_summary_ignores_partial_legs():
    records = [_partial_leg(), _full_close(10.0)]

    summary = compute_summary(records)

    assert summary["total_trades"] == 1


def test_compute_summary_win_rate_and_total_pnl():
    records = [_full_close(10.0), _full_close(-5.0), _full_close(20.0)]

    summary = compute_summary(records)

    assert summary["total_trades"] == 3
    assert summary["win_rate"] == pytest.approx(2 / 3)
    assert summary["total_net_pnl"] == pytest.approx(25.0)


def test_compute_summary_profit_factor():
    records = [_full_close(10.0), _full_close(-5.0)]

    summary = compute_summary(records)

    assert summary["profit_factor"] == pytest.approx(2.0)


def test_compute_summary_max_drawdown_tracks_peak_to_trough():
    records = [_full_close(10.0), _full_close(-15.0), _full_close(-5.0), _full_close(20.0)]
    # equity: 10, -5, -10, 10 ; peak: 10, 10, 10, 10 ; drawdown: 0, 15, 20, 0

    summary = compute_summary(records)

    assert summary["max_drawdown"] == pytest.approx(20.0)


def test_compute_summary_max_consecutive_losses():
    records = [_full_close(-1.0), _full_close(-1.0), _full_close(5.0), _full_close(-1.0)]

    summary = compute_summary(records)

    assert summary["max_consecutive_losses"] == 2


def test_write_trade_log_csv_writes_one_row_per_record(tmp_path):
    path = tmp_path / "trades.csv"
    records = [_full_close(10.0), _partial_leg()]

    write_trade_log_csv(records, str(path))

    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert rows[0]["side"] == "long"
    assert rows[0]["reason"] == "time_exit"
    assert rows[1]["is_partial"] == "True"


def test_write_trade_log_csv_writes_header_only_for_empty_list(tmp_path):
    path = tmp_path / "trades.csv"

    write_trade_log_csv([], str(path))

    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    assert rows == []
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `.venv/bin/pytest tests/test_backtest_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backtest_report'`.

- [ ] **Step 3: Implement backtest_report.py**

Create `backtest_report.py`:

```python
from __future__ import annotations

import csv
from typing import List


def compute_summary(trade_records: List[dict]) -> dict:
    """trade_records: dicts shaped like ExecutionEngine.on_trade_closed's
    payload. Only is_partial=False rows count as a complete trade —
    their total_trade_net already aggregates the entry fee, every partial
    leg, and the final close."""
    closes = [r for r in trade_records if not r["is_partial"]]

    total_trades = len(closes)
    if total_trades == 0:
        return {
            "total_trades": 0, "win_rate": 0.0, "total_net_pnl": 0.0,
            "profit_factor": 0.0, "max_drawdown": 0.0, "max_consecutive_losses": 0,
        }

    nets = [r["total_trade_net"] for r in closes]
    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]

    win_rate = len(wins) / total_trades
    total_net_pnl = sum(nets)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for n in nets:
        equity += n
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    streak = 0
    max_streak = 0
    for n in nets:
        if n <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    return {
        "total_trades": total_trades, "win_rate": win_rate, "total_net_pnl": total_net_pnl,
        "profit_factor": profit_factor, "max_drawdown": max_drawdown,
        "max_consecutive_losses": max_streak,
    }


_CSV_FIELDS = [
    "side", "entry_price", "exit_price", "size", "reason", "leg_net",
    "total_trade_net", "fees_paid", "entry_time", "exit_time", "is_partial",
]


def write_trade_log_csv(trade_records: List[dict], path: str) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for r in trade_records:
            row = dict(r)
            row["side"] = row["side"].value
            writer.writerow(row)
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `.venv/bin/pytest tests/test_backtest_report.py -v`
Expected: `9 passed`.

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `.venv/bin/pytest -q`
Expected: `N + 46` passed (37 from Tasks 1-8, 9 new here), zero failed.

- [ ] **Step 6: Commit**

```bash
git add backtest_report.py tests/test_backtest_report.py
git commit -m "Add backtest summary stats and CSV trade log writer"
```

---

### Task 10: CLI entry point (`backtest.py`)

**Files:**
- Create: `backtest.py`
- Create: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `wire_strategy` (Task 4), `ExecutionEngine.on_trade_closed` (Task 5), `BacktestFeed` (Task 8), `compute_summary`/`write_trade_log_csv` (Task 9), `safety.STATE_FILE_PATH` (existing, isolated here so the backtest never touches the real bot's persisted state).
- Produces: `parse_args(argv) -> argparse.Namespace`, `validate_range(start_ms: int, end_ms: int) -> None`, `async def run_backtest(args, exchange=None) -> dict`, `main(argv=None, exchange=None) -> int`. `exchange` is test-only — production runs always pass `None` (real ccxt).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backtest.py`:

```python
import csv

import pytest

import backtest
import clock


class _FakeExchange:
    def __init__(self, klines, trades):
        self._klines = klines
        self._trades = trades

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        return [k for k in self._klines if k[0] >= since][:limit]

    def fetch_trades(self, symbol, since=None, limit=None):
        return [t for t in self._trades if t["timestamp"] >= since][:limit]


@pytest.fixture(autouse=True)
def _reset_clock():
    yield
    clock.reset()


@pytest.fixture(autouse=True)
def _isolate_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("backtest_feed.CACHE_DIR", str(tmp_path / "cache"))


_BASE_MS = 1_704_067_200_000  # 2024-01-01T00:00:00Z


def test_main_runs_end_to_end_and_writes_a_csv(tmp_path):
    klines_1m = [
        [_BASE_MS,          100.0, 102.0, 99.0,  101.0, 2.0],
        [_BASE_MS + 60_000, 101.0, 103.0, 100.0, 110.0, 3.0],
    ]
    trades = [
        {"timestamp": _BASE_MS + 10_000, "price": 100.5, "amount": 1.0, "side": "buy"},
        {"timestamp": _BASE_MS + 70_000, "price": 109.0, "amount": 1.0, "side": "buy"},
    ]
    exchange = _FakeExchange(klines_1m, trades)
    out_path = tmp_path / "trades.csv"

    exit_code = backtest.main(
        ["--start", "2024-01-01", "--end", "2024-01-02", "--out", str(out_path)],
        exchange=exchange,
    )

    assert exit_code == 0
    assert out_path.exists()
    with open(out_path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows == []  # too little warm-up history for any entry signal to fire


def test_main_rejects_start_after_end():
    exit_code = backtest.main(
        ["--start", "2024-01-02", "--end", "2024-01-01"],
        exchange=_FakeExchange([], []),
    )

    assert exit_code == 1


def test_main_rejects_a_future_end_date():
    exit_code = backtest.main(
        ["--start", "2024-01-01", "--end", "2099-01-01"],
        exchange=_FakeExchange([], []),
    )

    assert exit_code == 1


def test_run_backtest_never_touches_the_real_safety_state_file(tmp_path):
    import asyncio

    import safety

    klines_1m = [[_BASE_MS, 100.0, 100.0, 100.0, 100.0, 1.0]]
    trades = [{"timestamp": _BASE_MS + 1_000, "price": 100.0, "amount": 1.0, "side": "buy"}]
    exchange = _FakeExchange(klines_1m, trades)

    args = backtest.parse_args(["--start", "2024-01-01", "--end", "2024-01-02", "--out", str(tmp_path / "t.csv")])
    asyncio.run(backtest.run_backtest(args, exchange=exchange))

    assert safety.STATE_FILE_PATH != "safety_state.json"
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `.venv/bin/pytest tests/test_backtest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backtest'`.

- [ ] **Step 3: Implement backtest.py**

Create `backtest.py`:

```python
from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from datetime import datetime, timezone

import safety
from backtest_feed import BacktestFeed
from backtest_report import compute_summary, write_trade_log_csv
from config import BACKTEST_SYNTHETIC_SPREAD_PCT
from execution import ExecutionEngine
from main import wire_strategy
from risk import PAPER_BALANCE_USDT
from state import MarketState


def _parse_date_utc(value: str) -> int:
    """Parses YYYY-MM-DD as milliseconds since epoch, UTC midnight."""
    dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def parse_args(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest the BTC scalping strategy against historical Binance data.")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD (UTC, inclusive)")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD (UTC, exclusive)")
    parser.add_argument("--balance", type=float, default=PAPER_BALANCE_USDT)
    parser.add_argument("--spread-pct", type=float, default=BACKTEST_SYNTHETIC_SPREAD_PCT)
    parser.add_argument("--out", default="backtest_trades.csv")
    parser.add_argument("--no-cache", action="store_true")
    return parser.parse_args(argv)


def validate_range(start_ms: int, end_ms: int) -> None:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if start_ms >= end_ms:
        raise ValueError("--start must be before --end")
    if end_ms > now_ms:
        raise ValueError("--end cannot be in the future")


async def run_backtest(args: argparse.Namespace, exchange=None) -> dict:
    start_ms = _parse_date_utc(args.start)
    end_ms = _parse_date_utc(args.end)
    validate_range(start_ms, end_ms)

    _, state_file_path = tempfile.mkstemp(prefix="backtest_safety_state_", suffix=".json")
    safety.STATE_FILE_PATH = state_file_path

    state = MarketState()
    trade_records: list = []
    engine = ExecutionEngine(state, on_trade_closed=trade_records.append)
    feed = BacktestFeed(state, exchange=exchange, spread_pct=args.spread_pct, use_cache=not args.no_cache)
    wire_strategy(state, feed, engine)

    await feed.replay(start_ms, end_ms)

    summary = compute_summary(trade_records)
    write_trade_log_csv(trade_records, args.out)
    return summary


def _print_summary(summary: dict) -> None:
    print(f"Trades: {summary['total_trades']}")
    print(f"Win rate: {summary['win_rate']:.1%}")
    print(f"Total net P&L: ${summary['total_net_pnl']:+.2f}")
    print(f"Profit factor: {summary['profit_factor']:.2f}")
    print(f"Max drawdown: ${summary['max_drawdown']:.2f}")
    print(f"Max consecutive losses: {summary['max_consecutive_losses']}")


def main(argv=None, exchange=None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        summary = asyncio.run(run_backtest(args, exchange=exchange))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `.venv/bin/pytest tests/test_backtest.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Verify the CLI's `--help` and a real argument-parsing error work**

```bash
.venv/bin/python backtest.py --help
```
Expected: prints usage with `--start`, `--end`, `--balance`, `--spread-pct`, `--out`, `--no-cache`, exit code 0.

```bash
.venv/bin/python backtest.py --end 2024-01-02; echo "exit code: $?"
```
Expected: argparse error about missing required `--start`, exit code 2.

- [ ] **Step 6: Run the full suite to confirm no regression**

Run: `.venv/bin/pytest -q`
Expected: `N + 50` passed (46 from Tasks 1-9, 4 new here), zero failed.

- [ ] **Step 7: Commit**

```bash
git add backtest.py tests/test_backtest.py
git commit -m "Add backtest.py CLI entry point"
```

---

### Task 11: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `.venv/bin/pytest -q`
Expected: `N + 50` passed, where `N` is the baseline recorded in Task 0 — zero failed, zero skipped.

- [ ] **Step 2: Run a real (non-mocked) smoke test against live Binance data**

This is the only point in the whole plan that touches the real network — confirms the `ccxt` wiring (`_build_exchange`, real `fetch_ohlcv`/`fetch_trades` shapes) actually works end-to-end, not just against the fakes used in every other test.

```bash
.venv/bin/python backtest.py --start "$(date -u -d '2 days ago' +%F)" --end "$(date -u -d '1 day ago' +%F)" --out /tmp/backtest_smoke.csv
```

Expected: completes within a few minutes, prints the six summary lines (`Trades:`, `Win rate:`, `Total net P&L:`, `Profit factor:`, `Max drawdown:`, `Max consecutive losses:`), exit code 0. `backtest_cache/` now contains the fetched klines/trades for that day. Re-run the same command — it should finish near-instantly (cache hit) and print an identical summary.

- [ ] **Step 3: If the count doesn't match, investigate before moving on**

Diff the actual `pytest -v` output against the expected test names listed in Tasks 1-10's "run the tests" steps to find which test is missing, duplicated, or unexpectedly failing — do not just re-run and hope.
