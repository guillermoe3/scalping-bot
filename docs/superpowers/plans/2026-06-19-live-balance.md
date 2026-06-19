# Live Account Balance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `PAPER_BALANCE_USDT` constant used for LIVE-mode position sizing and the daily kill switch threshold with the real Binance Futures account balance, captured as a fixed daily snapshot.

**Architecture:** `safety.py` gains a `fetch_real_balance(exchange)` helper and `MarketState.daily_starting_balance`, resolved once per UTC day inside the existing `maybe_reset_daily`/`can_open_new_position` flow (mirroring the `exchange` parameter already used by `reconcile_with_exchange`). `risk.py` reads that field instead of a hardcoded constant. `main.py` threads `engine.exchange` through. Paper mode and the backtest harness are untouched — `engine.exchange` is already `None` there.

**Tech Stack:** Python 3.12, pytest, ccxt (already a dependency, no new packages).

## Global Constraints

- Branch base: `master` at commit `ab7287c` (spec commit). Create a new branch `live-balance` (worktree at `.worktrees/live-balance`) before starting Task 1.
- Fail-closed: any exchange error or malformed response during balance resolution must `sys.exit(1)` — never fall back silently to a guessed number in LIVE mode. Same criterion `reconcile_with_exchange` already uses.
- Paper mode (`exchange=None`) and the backtest harness must never touch the network for balance — always resolve to `config.PAPER_BALANCE_USDT`.
- Single margin currency: USDT only (matches the rest of the bot — `config.SYMBOL = "BTCUSDT"`).
- Baseline before Task 1: `pytest -q` → `120 passed`. Track this number through every task.

---

### Task 1: Move `PAPER_BALANCE_USDT` from `risk.py` to `config.py`

**Files:**
- Modify: `config.py` (add constant)
- Modify: `risk.py:1-24` (remove constant, import it instead)

**Interfaces:**
- Produces: `config.PAPER_BALANCE_USDT` (float, `10_000.0`) — every later task imports it from `config`, not `risk`.

- [ ] **Step 1: Add the constant to `config.py`**

In `config.py`, after line 45 (`ATR_BREATHING_THRESHOLD = 1.2 # expand SL if live ATR grows 20%+ vs entry ATR`), add:

```python
PAPER_BALANCE_USDT = 10_000.0  # paper-mode balance; LIVE mode overrides this daily (see safety.py)
```

- [ ] **Step 2: Remove the constant from `risk.py`, import it from `config` instead**

In `risk.py`, replace lines 1-24:

```python
from __future__ import annotations

import logging
import time
from typing import Optional

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

logger = logging.getLogger(__name__)

# Used in paper mode; replace with live account balance query for live trading
PAPER_BALANCE_USDT = 10_000.0
```

with:

```python
from __future__ import annotations

import logging
import time
from typing import Optional

import safety
from config import (
    ACCOUNT_RISK_PCT,
    ATR_BREATHING_THRESHOLD,
    BREAKEVEN_ATR_TRIGGER,
    INITIAL_SL_ATR,
    PAPER_BALANCE_USDT,
    TAKER_FEE_RATE,
    TIME_EXIT_MINUTES,
    TP1_CLOSE_PCT,
    TP1_RR,
)
from indicators import detect_swing_points
from state import MarketState, Position, Side

logger = logging.getLogger(__name__)
```

(`from risk import PAPER_BALANCE_USDT` in `tests/test_risk.py` keeps working unchanged — importing a name makes it an attribute of the importing module too.)

- [ ] **Step 3: Run the full suite, confirm zero regressions**

Run: `.venv/bin/pytest -q`
Expected: `120 passed` (pure refactor, no behavior change yet).

- [ ] **Step 4: Commit**

```bash
git add config.py risk.py
git commit -m "Move PAPER_BALANCE_USDT from risk.py to config.py"
```

---

### Task 2: Add `daily_starting_balance` field to `MarketState`

**Files:**
- Modify: `state.py:152-155`
- Test: `tests/test_state.py:4-8`

**Interfaces:**
- Produces: `MarketState.daily_starting_balance: Optional[float]`, default `None`. Tasks 3-9 read/write this field.

- [ ] **Step 1: Extend the existing defaults test**

In `tests/test_state.py`, replace:

```python
def test_market_state_defaults_include_safety_fields():
    state = MarketState()
    assert state.consecutive_losses == 0
    assert state.kill_switch_active is False
    assert state.last_reset_date is None
```

with:

```python
def test_market_state_defaults_include_safety_fields():
    state = MarketState()
    assert state.consecutive_losses == 0
    assert state.kill_switch_active is False
    assert state.last_reset_date is None
    assert state.daily_starting_balance is None
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/pytest tests/test_state.py -v`
Expected: FAIL — `AttributeError: 'MarketState' object has no attribute 'daily_starting_balance'`.

- [ ] **Step 3: Add the field**

In `state.py`, replace lines 152-155:

```python
    # Daily safety / kill switch
    consecutive_losses: int = 0
    kill_switch_active: bool = False
    last_reset_date: Optional[str] = None
```

with:

```python
    # Daily safety / kill switch
    consecutive_losses: int = 0
    kill_switch_active: bool = False
    last_reset_date: Optional[str] = None
    daily_starting_balance: Optional[float] = None
```

- [ ] **Step 4: Run test, verify it passes**

Run: `.venv/bin/pytest tests/test_state.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/pytest -q`
Expected: `120 passed` (no new test functions, just an extra assertion in an existing test).

- [ ] **Step 6: Commit**

```bash
git add state.py tests/test_state.py
git commit -m "Add daily_starting_balance field to MarketState"
```

---

### Task 3: Add `safety.fetch_real_balance(exchange)`

**Files:**
- Modify: `safety.py` (add function, before `maybe_reset_daily`)
- Test: `tests/test_safety.py`

**Interfaces:**
- Consumes: `exchange.fetch_balance() -> dict` shaped like ccxt's unified response (`{"total": {"USDT": <float>, ...}, ...}`).
- Produces: `safety.fetch_real_balance(exchange) -> float`. Task 4 calls this.

- [ ] **Step 1: Write the failing tests**

In `tests/test_safety.py`, add near the bottom (after the existing `_FailingExchange` class, before the reconciliation tests — order doesn't matter functionally, but keep exchange fakes grouped):

```python
class _FakeBalanceExchange:
    def __init__(self, usdt_total):
        self._usdt_total = usdt_total
        self.fetch_balance_calls = 0

    def fetch_balance(self):
        self.fetch_balance_calls += 1
        return {"total": {"USDT": self._usdt_total}}


class _FailingBalanceExchange:
    def fetch_balance(self):
        raise RuntimeError("network down")


class _MalformedBalanceExchange:
    def fetch_balance(self):
        return {"total": {}}  # no USDT key


def test_fetch_real_balance_returns_usdt_total():
    exchange = _FakeBalanceExchange(14230.55)

    assert safety.fetch_real_balance(exchange) == pytest.approx(14230.55)


def test_fetch_real_balance_exits_on_fetch_failure():
    exchange = _FailingBalanceExchange()

    with pytest.raises(SystemExit):
        safety.fetch_real_balance(exchange)


def test_fetch_real_balance_exits_when_usdt_key_missing():
    exchange = _MalformedBalanceExchange()

    with pytest.raises(SystemExit):
        safety.fetch_real_balance(exchange)
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/test_safety.py -k fetch_real_balance -v`
Expected: FAIL — `AttributeError: module 'safety' has no attribute 'fetch_real_balance'`.

- [ ] **Step 3: Implement `fetch_real_balance`**

In `safety.py`, add this function right before `def maybe_reset_daily`:

```python
def fetch_real_balance(exchange) -> float:
    """Fetches the real USDT wallet balance from the exchange. Exits the
    process rather than guessing when the fetch fails or the response is
    malformed — same fail-closed criterion as reconcile_with_exchange."""
    try:
        balance = exchange.fetch_balance()
        total = balance["total"]["USDT"]
    except Exception:
        logger.error("Could not fetch real account balance", exc_info=True)
        sys.exit(1)
    return float(total)
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `.venv/bin/pytest tests/test_safety.py -k fetch_real_balance -v`
Expected: `3 passed`.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/pytest -q`
Expected: `123 passed` (120 baseline + 3 new).

- [ ] **Step 6: Commit**

```bash
git add safety.py tests/test_safety.py
git commit -m "Add safety.fetch_real_balance for LIVE-mode balance resolution"
```

---

### Task 4: Resolve and persist `daily_starting_balance` in `maybe_reset_daily`

**Files:**
- Modify: `safety.py:10-34`
- Test: `tests/test_safety.py`

**Interfaces:**
- Consumes: `safety.fetch_real_balance(exchange)` (Task 3), `config.PAPER_BALANCE_USDT` (Task 1).
- Produces: `maybe_reset_daily(state: MarketState, exchange=None) -> None`. Task 5 threads `exchange` into this.

- [ ] **Step 1: Update the import block**

In `safety.py`, replace:

```python
from config import (
    KILL_SWITCH_CONSECUTIVE_LOSSES,
    KILL_SWITCH_DAILY_LOSS_PCT,
    STATE_FILE_PATH,
)
```

with:

```python
from config import (
    KILL_SWITCH_CONSECUTIVE_LOSSES,
    KILL_SWITCH_DAILY_LOSS_PCT,
    PAPER_BALANCE_USDT,
    STATE_FILE_PATH,
)
```

- [ ] **Step 2: Write the failing tests**

In `tests/test_safety.py`, update the existing noop test (it must now also seed `daily_starting_balance`, since "already reset today" now also means "balance already resolved today"):

Replace:

```python
def test_maybe_reset_daily_is_a_noop_when_already_reset_today():
    state = MarketState()
    state.last_reset_date = safety._today_utc()
    state.pnl_today = -50.0

    safety.maybe_reset_daily(state)

    assert state.pnl_today == -50.0
```

with:

```python
def test_maybe_reset_daily_is_a_noop_when_already_reset_today():
    state = MarketState()
    state.last_reset_date = safety._today_utc()
    state.daily_starting_balance = 10_000.0
    state.pnl_today = -50.0

    safety.maybe_reset_daily(state)

    assert state.pnl_today == -50.0
    assert state.daily_starting_balance == 10_000.0
```

Then add these new tests (place them near the other `maybe_reset_daily` tests):

```python
def test_maybe_reset_daily_sets_paper_balance_when_no_exchange():
    state = MarketState()

    safety.maybe_reset_daily(state)

    assert state.daily_starting_balance == PAPER_BALANCE_USDT


def test_maybe_reset_daily_fetches_real_balance_from_exchange():
    state = MarketState()
    exchange = _FakeBalanceExchange(14230.55)

    safety.maybe_reset_daily(state, exchange)

    assert state.daily_starting_balance == pytest.approx(14230.55)


def test_maybe_reset_daily_does_not_refetch_same_day():
    state = MarketState()
    exchange = _FakeBalanceExchange(14230.55)
    safety.maybe_reset_daily(state, exchange)

    safety.maybe_reset_daily(state, exchange)

    assert exchange.fetch_balance_calls == 1


def test_maybe_reset_daily_refetches_on_date_rollover():
    state = MarketState()
    state.last_reset_date = "2020-01-01"
    state.daily_starting_balance = 999.0
    exchange = _FakeBalanceExchange(14230.55)

    safety.maybe_reset_daily(state, exchange)

    assert state.daily_starting_balance == pytest.approx(14230.55)


def test_maybe_reset_daily_exits_when_balance_fetch_fails():
    state = MarketState()
    exchange = _FailingBalanceExchange()

    with pytest.raises(SystemExit):
        safety.maybe_reset_daily(state, exchange)
```

Add `from config import PAPER_BALANCE_USDT` to the top of `tests/test_safety.py` (alongside the existing `import safety` line).

- [ ] **Step 2b: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/test_safety.py -k maybe_reset_daily -v`
Expected: FAIL — the noop test fails on the new `daily_starting_balance` assertion, the new tests fail with `AttributeError` (state has no `daily_starting_balance` set by `maybe_reset_daily` yet) or `TypeError: maybe_reset_daily() takes 1 positional argument but 2 were given`.

- [ ] **Step 3: Implement**

In `safety.py`, replace:

```python
def maybe_reset_daily(state: MarketState) -> None:
    """Reset daily counters and the kill switch when the UTC date has rolled over."""
    today = _today_utc()
    if state.last_reset_date == today:
        return
    state.pnl_today = 0.0
    state.trades_today = 0
    state.consecutive_losses = 0
    state.kill_switch_active = False
    state.last_reset_date = today
    save_state(state)
```

with:

```python
def maybe_reset_daily(state: MarketState, exchange=None) -> None:
    """Reset daily counters and the kill switch when the UTC date has rolled
    over, and (re)resolve the daily starting balance used for position
    sizing and the kill switch threshold."""
    today = _today_utc()
    if state.last_reset_date == today and state.daily_starting_balance is not None:
        return
    state.daily_starting_balance = (
        PAPER_BALANCE_USDT if exchange is None else fetch_real_balance(exchange)
    )
    state.pnl_today = 0.0
    state.trades_today = 0
    state.consecutive_losses = 0
    state.kill_switch_active = False
    state.last_reset_date = today
    save_state(state)
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `.venv/bin/pytest tests/test_safety.py -k maybe_reset_daily -v`
Expected: `6 passed`.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/pytest -q`
Expected: `128 passed` (120 baseline + 3 from Task 3 + 5 new in this task + 1 existing test updated, not added).

- [ ] **Step 6: Commit**

```bash
git add safety.py tests/test_safety.py
git commit -m "Resolve and cache daily_starting_balance in maybe_reset_daily"
```

---

### Task 5: Thread `exchange` through `can_open_new_position`

**Files:**
- Modify: `safety.py:37-39`
- Test: `tests/test_safety.py`

**Interfaces:**
- Consumes: `maybe_reset_daily(state, exchange=None)` (Task 4).
- Produces: `can_open_new_position(state: MarketState, exchange=None) -> bool`. Task 9 (`main.py`) calls this with `engine.exchange`.

- [ ] **Step 1: Write the failing test**

In `tests/test_safety.py`, add:

```python
def test_can_open_new_position_threads_exchange_to_balance_resolution():
    state = MarketState()
    exchange = _FakeBalanceExchange(14230.55)

    safety.can_open_new_position(state, exchange)

    assert state.daily_starting_balance == pytest.approx(14230.55)
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/pytest tests/test_safety.py -k threads_exchange -v`
Expected: FAIL — `TypeError: can_open_new_position() takes 1 positional argument but 2 were given`.

- [ ] **Step 3: Implement**

In `safety.py`, replace:

```python
def can_open_new_position(state: MarketState) -> bool:
    maybe_reset_daily(state)
    return not state.kill_switch_active
```

with:

```python
def can_open_new_position(state: MarketState, exchange=None) -> bool:
    maybe_reset_daily(state, exchange)
    return not state.kill_switch_active
```

- [ ] **Step 4: Run test, verify it passes**

Run: `.venv/bin/pytest tests/test_safety.py -k threads_exchange -v`
Expected: `1 passed`.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/pytest -q`
Expected: `129 passed`.

- [ ] **Step 6: Commit**

```bash
git add safety.py tests/test_safety.py
git commit -m "Thread exchange through can_open_new_position"
```

---

### Task 6: Drop the `balance` parameter from `after_trade_closed`

**Files:**
- Modify: `safety.py:42-59`
- Modify: `risk.py:110`
- Test: `tests/test_safety.py`
- Test: `tests/test_risk.py`

**Interfaces:**
- Consumes: `state.daily_starting_balance` (Task 2/4).
- Produces: `after_trade_closed(state: MarketState, total_trade_net: float) -> None` (was 3 positional args, now 2). Every caller of the old 3-arg form breaks — this task updates all of them in the same commit.

- [ ] **Step 1: Update the three existing `test_safety.py` tests that pass `balance=` explicitly**

Replace:

```python
def test_after_trade_closed_triggers_kill_switch_on_daily_loss_pct():
    state = MarketState()
    state.last_reset_date = safety._today_utc()
    state.pnl_today = -250.0  # -2.5% of a 10,000 balance

    safety.after_trade_closed(state, total_trade_net=-250.0, balance=10_000.0)

    assert state.kill_switch_active is True


def test_after_trade_closed_triggers_kill_switch_on_consecutive_losses():
    state = MarketState()
    state.last_reset_date = safety._today_utc()

    safety.after_trade_closed(state, total_trade_net=-10.0, balance=10_000.0)
    safety.after_trade_closed(state, total_trade_net=-10.0, balance=10_000.0)
    safety.after_trade_closed(state, total_trade_net=-10.0, balance=10_000.0)

    assert state.consecutive_losses == 3
    assert state.kill_switch_active is True


def test_after_trade_closed_resets_streak_on_winning_trade():
    state = MarketState()
    state.last_reset_date = safety._today_utc()

    safety.after_trade_closed(state, total_trade_net=-10.0, balance=10_000.0)
    safety.after_trade_closed(state, total_trade_net=-10.0, balance=10_000.0)
    safety.after_trade_closed(state, total_trade_net=25.0, balance=10_000.0)

    assert state.consecutive_losses == 0
    assert state.kill_switch_active is False
```

with:

```python
def test_after_trade_closed_triggers_kill_switch_on_daily_loss_pct():
    state = MarketState()
    state.last_reset_date = safety._today_utc()
    state.daily_starting_balance = 10_000.0
    state.pnl_today = -250.0  # -2.5% of a 10,000 balance

    safety.after_trade_closed(state, total_trade_net=-250.0)

    assert state.kill_switch_active is True


def test_after_trade_closed_triggers_kill_switch_on_consecutive_losses():
    state = MarketState()
    state.last_reset_date = safety._today_utc()
    state.daily_starting_balance = 10_000.0

    safety.after_trade_closed(state, total_trade_net=-10.0)
    safety.after_trade_closed(state, total_trade_net=-10.0)
    safety.after_trade_closed(state, total_trade_net=-10.0)

    assert state.consecutive_losses == 3
    assert state.kill_switch_active is True


def test_after_trade_closed_resets_streak_on_winning_trade():
    state = MarketState()
    state.last_reset_date = safety._today_utc()
    state.daily_starting_balance = 10_000.0

    safety.after_trade_closed(state, total_trade_net=-10.0)
    safety.after_trade_closed(state, total_trade_net=-10.0)
    safety.after_trade_closed(state, total_trade_net=25.0)

    assert state.consecutive_losses == 0
    assert state.kill_switch_active is False
```

- [ ] **Step 2: Update the two `test_risk.py` tests that monkeypatch `after_trade_closed`**

Replace:

```python
def test_close_position_aggregates_realized_pnl_and_calls_kill_switch(monkeypatch):
    state = _state_with_long_position(entry=100.0)
    pos = state.position
    entry_fee = pos.fees_paid
    size = pos.size

    calls = []
    monkeypatch.setattr(
        safety, "after_trade_closed",
        lambda s, total_net, balance: calls.append((total_net, balance)),
    )

    net = close_position(state, price=105.0, reason="time_exit")

    expected_gross = (105.0 - 100.0) * size
    expected_fee = size * 105.0 * TAKER_FEE_RATE
    expected_net = expected_gross - expected_fee
    expected_total_trade_net = -entry_fee + expected_net

    assert net == pytest.approx(expected_net)
    assert state.position is None
    assert len(calls) == 1
    assert calls[0][0] == pytest.approx(expected_total_trade_net)
    assert calls[0][1] == PAPER_BALANCE_USDT
```

with:

```python
def test_close_position_aggregates_realized_pnl_and_calls_kill_switch(monkeypatch):
    state = _state_with_long_position(entry=100.0)
    pos = state.position
    entry_fee = pos.fees_paid
    size = pos.size

    calls = []
    monkeypatch.setattr(
        safety, "after_trade_closed",
        lambda s, total_net: calls.append(total_net),
    )

    net = close_position(state, price=105.0, reason="time_exit")

    expected_gross = (105.0 - 100.0) * size
    expected_fee = size * 105.0 * TAKER_FEE_RATE
    expected_net = expected_gross - expected_fee
    expected_total_trade_net = -entry_fee + expected_net

    assert net == pytest.approx(expected_net)
    assert state.position is None
    assert len(calls) == 1
    assert calls[0] == pytest.approx(expected_total_trade_net)
```

And replace:

```python
    calls = []
    monkeypatch.setattr(
        safety, "after_trade_closed",
        lambda s, total_net, balance: calls.append(total_net),
    )
```

(inside `test_trade_with_tp1_then_breakeven_exit_uses_total_realized_pnl`) with:

```python
    calls = []
    monkeypatch.setattr(
        safety, "after_trade_closed",
        lambda s, total_net: calls.append(total_net),
    )
```

- [ ] **Step 3: Run the affected tests, verify they fail**

Run: `.venv/bin/pytest tests/test_safety.py -k after_trade_closed tests/test_risk.py -v`
Expected: FAIL — `TypeError: after_trade_closed() missing 1 required positional argument: 'balance'` (safety tests) and the monkeypatched lambdas raising `TypeError` for the wrong arg count (risk tests), since the implementation hasn't changed yet.

- [ ] **Step 4: Implement the signature change in `safety.py`**

Replace:

```python
def after_trade_closed(state: MarketState, total_trade_net: float, balance: float) -> None:
    if total_trade_net < 0:
        state.consecutive_losses += 1
    else:
        state.consecutive_losses = 0

    daily_loss_breached = state.pnl_today <= -KILL_SWITCH_DAILY_LOSS_PCT * balance
    streak_breached = state.consecutive_losses >= KILL_SWITCH_CONSECUTIVE_LOSSES
```

with:

```python
def after_trade_closed(state: MarketState, total_trade_net: float) -> None:
    if total_trade_net < 0:
        state.consecutive_losses += 1
    else:
        state.consecutive_losses = 0

    balance = state.daily_starting_balance or PAPER_BALANCE_USDT
    daily_loss_breached = state.pnl_today <= -KILL_SWITCH_DAILY_LOSS_PCT * balance
    streak_breached = state.consecutive_losses >= KILL_SWITCH_CONSECUTIVE_LOSSES
```

- [ ] **Step 5: Update the call site in `risk.py`**

In `risk.py`, replace line 110:

```python
    safety.after_trade_closed(state, total_trade_net, PAPER_BALANCE_USDT)
```

with:

```python
    safety.after_trade_closed(state, total_trade_net)
```

- [ ] **Step 6: Run the affected tests, verify they pass**

Run: `.venv/bin/pytest tests/test_safety.py -k after_trade_closed -v && .venv/bin/pytest tests/test_risk.py -v`
Expected: all pass.

- [ ] **Step 7: Run full suite**

Run: `.venv/bin/pytest -q`
Expected: `129 passed` (no net new tests this task — 3 signature updates in `test_safety.py`, 2 in `test_risk.py`).

- [ ] **Step 8: Commit**

```bash
git add safety.py risk.py tests/test_safety.py tests/test_risk.py
git commit -m "Drop balance parameter from after_trade_closed, read state.daily_starting_balance"
```

---

### Task 7: Persist `daily_starting_balance` in `safety_state.json`

**Files:**
- Modify: `safety.py:78-120` (`save_state`, `load_into_state`)
- Test: `tests/test_safety.py`

**Interfaces:**
- Produces: `safety_state.json` gains a `"daily_starting_balance"` key. `load_into_state` restores `MarketState.daily_starting_balance` from it, defaulting to `None` when the key is absent (old-format files).

- [ ] **Step 1: Write the failing tests**

In `tests/test_safety.py`, update `test_save_then_load_round_trips_flat_state`:

Replace:

```python
def test_save_then_load_round_trips_flat_state(_isolate_state_file):
    state = MarketState()
    state.last_reset_date = "2026-06-17"
    state.pnl_today = -42.5
    state.trades_today = 3
    state.consecutive_losses = 1
    state.kill_switch_active = False

    safety.save_state(state)

    loaded = MarketState()
    safety.load_into_state(loaded)

    assert loaded.last_reset_date == "2026-06-17"
    assert loaded.pnl_today == pytest.approx(-42.5)
    assert loaded.trades_today == 3
    assert loaded.consecutive_losses == 1
    assert loaded.position is None
```

with:

```python
def test_save_then_load_round_trips_flat_state(_isolate_state_file):
    state = MarketState()
    state.last_reset_date = "2026-06-17"
    state.daily_starting_balance = 12345.67
    state.pnl_today = -42.5
    state.trades_today = 3
    state.consecutive_losses = 1
    state.kill_switch_active = False

    safety.save_state(state)

    loaded = MarketState()
    safety.load_into_state(loaded)

    assert loaded.last_reset_date == "2026-06-17"
    assert loaded.daily_starting_balance == pytest.approx(12345.67)
    assert loaded.pnl_today == pytest.approx(-42.5)
    assert loaded.trades_today == 3
    assert loaded.consecutive_losses == 1
    assert loaded.position is None
```

Then add:

```python
def test_load_into_state_defaults_daily_starting_balance_when_key_missing(_isolate_state_file):
    payload = {
        "date_utc": "2026-06-17",
        "pnl_today": 0.0,
        "trades_today": 0,
        "consecutive_losses": 0,
        "kill_switch_active": False,
        "position": None,
    }
    with open(safety.STATE_FILE_PATH, "w") as f:
        json.dump(payload, f)

    state = MarketState()
    safety.load_into_state(state)

    assert state.daily_starting_balance is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `.venv/bin/pytest tests/test_safety.py -k "round_trips_flat_state or defaults_daily_starting_balance" -v`
Expected: FAIL — `loaded.daily_starting_balance` is `None` instead of `12345.67` in the first test (the new test passes trivially since the field already defaults to `None`, but keep it for explicit documentation of the old-format-file contract).

- [ ] **Step 3: Implement**

In `safety.py`, replace `save_state`:

```python
def save_state(state: MarketState) -> None:
    payload = {
        "date_utc": state.last_reset_date,
        "pnl_today": state.pnl_today,
        "trades_today": state.trades_today,
        "consecutive_losses": state.consecutive_losses,
        "kill_switch_active": state.kill_switch_active,
        "position": _position_to_dict(state.position),
    }
```

with:

```python
def save_state(state: MarketState) -> None:
    payload = {
        "date_utc": state.last_reset_date,
        "daily_starting_balance": state.daily_starting_balance,
        "pnl_today": state.pnl_today,
        "trades_today": state.trades_today,
        "consecutive_losses": state.consecutive_losses,
        "kill_switch_active": state.kill_switch_active,
        "position": _position_to_dict(state.position),
    }
```

Replace the body of `load_into_state`:

```python
    try:
        last_reset_date = payload.get("date_utc")
        pnl_today = payload.get("pnl_today", 0.0)
        trades_today = payload.get("trades_today", 0)
        consecutive_losses = payload.get("consecutive_losses", 0)
        kill_switch_active = payload.get("kill_switch_active", False)
        position = _position_from_dict(payload.get("position"))
    except (TypeError, KeyError, ValueError):
        logger.warning("Could not parse %s — starting with fresh state", STATE_FILE_PATH)
        return

    state.last_reset_date = last_reset_date
    state.pnl_today = pnl_today
    state.trades_today = trades_today
    state.consecutive_losses = consecutive_losses
    state.kill_switch_active = kill_switch_active
    state.position = position
```

with:

```python
    try:
        last_reset_date = payload.get("date_utc")
        daily_starting_balance = payload.get("daily_starting_balance")
        pnl_today = payload.get("pnl_today", 0.0)
        trades_today = payload.get("trades_today", 0)
        consecutive_losses = payload.get("consecutive_losses", 0)
        kill_switch_active = payload.get("kill_switch_active", False)
        position = _position_from_dict(payload.get("position"))
    except (TypeError, KeyError, ValueError):
        logger.warning("Could not parse %s — starting with fresh state", STATE_FILE_PATH)
        return

    state.last_reset_date = last_reset_date
    state.daily_starting_balance = daily_starting_balance
    state.pnl_today = pnl_today
    state.trades_today = trades_today
    state.consecutive_losses = consecutive_losses
    state.kill_switch_active = kill_switch_active
    state.position = position
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `.venv/bin/pytest tests/test_safety.py -k "round_trips_flat_state or defaults_daily_starting_balance" -v`
Expected: `2 passed`.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/pytest -q`
Expected: `130 passed`.

- [ ] **Step 6: Commit**

```bash
git add safety.py tests/test_safety.py
git commit -m "Persist daily_starting_balance in safety_state.json"
```

---

### Task 8: `risk.open_position` sizes against `state.daily_starting_balance`

**Files:**
- Modify: `risk.py:51-56`
- Test: `tests/test_risk.py`

**Interfaces:**
- Consumes: `state.daily_starting_balance` (Task 2/4).
- Produces: `open_position(state, side, price, balance=None)` — explicit `balance` still wins when passed (existing tests using it directly are unaffected); when omitted, resolves from `state.daily_starting_balance`, falling back to `config.PAPER_BALANCE_USDT`.

- [ ] **Step 1: Update the test imports**

In `tests/test_risk.py`, replace:

```python
from config import TAKER_FEE_RATE, TP1_CLOSE_PCT
```

with:

```python
from config import ACCOUNT_RISK_PCT, INITIAL_SL_ATR, TAKER_FEE_RATE, TP1_CLOSE_PCT
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_risk.py`:

```python
def test_open_position_sizes_against_daily_starting_balance():
    state = MarketState()
    state.atr = 2.0
    state.daily_starting_balance = 50_000.0

    open_position(state, Side.LONG, price=100.0)

    sl_dist = INITIAL_SL_ATR * state.atr
    expected_size = round((50_000.0 * ACCOUNT_RISK_PCT) / sl_dist, 6)
    assert state.position.size == pytest.approx(expected_size)


def test_open_position_falls_back_to_paper_balance_when_unset():
    state = MarketState()
    state.atr = 2.0
    assert state.daily_starting_balance is None

    open_position(state, Side.LONG, price=100.0)

    sl_dist = INITIAL_SL_ATR * state.atr
    expected_size = round((PAPER_BALANCE_USDT * ACCOUNT_RISK_PCT) / sl_dist, 6)
    assert state.position.size == pytest.approx(expected_size)
```

- [ ] **Step 3: Run tests, verify the first one fails**

Run: `.venv/bin/pytest tests/test_risk.py -k daily_starting_balance -v`
Expected: `test_open_position_sizes_against_daily_starting_balance` FAILS (current code always sizes against `PAPER_BALANCE_USDT`, ignoring `state.daily_starting_balance`). `test_open_position_falls_back_to_paper_balance_when_unset` passes already — that's expected, it's a regression-safety test for behavior that shouldn't change.

- [ ] **Step 4: Implement**

In `risk.py`, replace:

```python
def open_position(
    state: MarketState,
    side: Side,
    price: float,
    balance: float = PAPER_BALANCE_USDT,
) -> None:
    stop_loss, tp1 = _compute_levels(side, price, state.atr)
```

with:

```python
def open_position(
    state: MarketState,
    side: Side,
    price: float,
    balance: Optional[float] = None,
) -> None:
    if balance is None:
        balance = state.daily_starting_balance or PAPER_BALANCE_USDT
    stop_loss, tp1 = _compute_levels(side, price, state.atr)
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `.venv/bin/pytest tests/test_risk.py -k daily_starting_balance -v`
Expected: `2 passed`.

- [ ] **Step 6: Run full suite**

Run: `.venv/bin/pytest -q`
Expected: `132 passed`.

- [ ] **Step 7: Commit**

```bash
git add risk.py tests/test_risk.py
git commit -m "Size positions against state.daily_starting_balance"
```

---

### Task 9: Wire `main.py` to pass `engine.exchange` through

**Files:**
- Modify: `main.py:31-40` (`run()` startup)
- Modify: `main.py:77` (`on_candle_1m` entry-signal gate)

**Interfaces:**
- Consumes: `safety.maybe_reset_daily(state, exchange=None)` (Task 4), `safety.can_open_new_position(state, exchange=None)` (Task 5).

No test file exists for `main.py`'s `run()` on this branch (it's an async function that opens a real WebSocket connection — there is no existing unit-test harness for it). Verification for this task is the full test suite (unaffected files) plus a manual import smoke check.

- [ ] **Step 1: Add the startup balance resolution call**

In `main.py`, replace:

```python
    feed = DataFeed(state)
    engine = ExecutionEngine(state)
    macro = MacroFilter(state)

    if not PAPER_MODE:
        safety.reconcile_with_exchange(state, engine.exchange)
```

with:

```python
    feed = DataFeed(state)
    engine = ExecutionEngine(state)
    macro = MacroFilter(state)

    if not PAPER_MODE:
        safety.reconcile_with_exchange(state, engine.exchange)
    safety.maybe_reset_daily(state, engine.exchange)
```

- [ ] **Step 2: Thread `engine.exchange` into the entry-signal gate**

In `main.py`, replace line 77:

```python
        if state.position is None and safety.can_open_new_position(state):
```

with:

```python
        if state.position is None and safety.can_open_new_position(state, engine.exchange):
```

- [ ] **Step 3: Smoke-check the module imports and parses correctly**

Run: `.venv/bin/python -c "import main"`
Expected: no output, exit code 0 (confirms no syntax/import errors — `engine` is already in scope inside the `on_candle_1m` closure, so this is a static check, not behavioral).

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: `132 passed` (no test file covers `main.py` directly, so the count is unchanged from Task 8).

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "Thread engine.exchange into safety's daily balance resolution"
```

---

### Task 10: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `.venv/bin/pytest -q`
Expected: `132 passed`, zero failed, zero skipped. (120 baseline + 3 from Task 3 + 5 from Task 4 + 1 from Task 5 + 1 from Task 7 + 2 from Task 8; Tasks 1, 2, 6, and 9 net zero new tests.)

- [ ] **Step 2: If the count doesn't match, investigate before moving on**

Diff the actual `pytest -v` output against the expected test names listed in Tasks 1-9's "run the tests" steps to find which test is missing, duplicated, or unexpectedly failing — do not just re-run and hope.

- [ ] **Step 3: Manual paper-mode smoke check**

Run: `.venv/bin/python -c "
import asyncio
from state import MarketState
import safety

state = MarketState()
safety.maybe_reset_daily(state, exchange=None)
print('daily_starting_balance:', state.daily_starting_balance)
assert state.daily_starting_balance == 10_000.0
"`

Expected: prints `daily_starting_balance: 10000.0`, exits 0 — confirms paper mode never touches the network and resolves to the expected constant end-to-end through the real (non-mocked) module.
