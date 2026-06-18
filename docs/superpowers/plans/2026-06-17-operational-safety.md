# Endurecimiento de Seguridad Operativa — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a daily kill switch, crash-safe state persistence with exchange reconciliation, realistic fees/slippage (fixing a TP1 accounting bug along the way), and a spread entry filter to the BTC scalping bot.

**Architecture:** All new session-level safety logic (kill switch state machine, JSON persistence, exchange reconciliation) lives in a new `safety.py` module, mirroring the project's one-file-per-responsibility pattern. `risk.py` becomes fee-aware and gains a pure `check_tp1`/`apply_partial_close` split so partial take-profits get real PnL accounting and real exchange orders. `execution.py` fills orders by crossing the bid/ask spread instead of using `last_price`. `signals.py` gains one more entry gate (spread vs ATR).

**Tech Stack:** Python 3.12, asyncio, ccxt (futures orders), pytest (new — project has no tests today).

## Global Constraints

- Python 3.12, project venv at `.venv/` (repo root). Always invoke tools via `.venv/bin/python` / `.venv/bin/pytest` — never rely on `source activate` persisting across separate shell invocations.
- New constants and their exact values (from the approved spec, `docs/superpowers/specs/2026-06-16-operational-safety-design.md`):
  - `TAKER_FEE_RATE = 0.0005`
  - `KILL_SWITCH_DAILY_LOSS_PCT = 0.02`
  - `KILL_SWITCH_CONSECUTIVE_LOSSES = 3`
  - `SPREAD_FILTER_ATR_PCT = 0.05`
  - `STATE_FILE_PATH = "safety_state.json"`
- Follow existing code style: `from __future__ import annotations` at the top of every new module, type hints on all function signatures, no comments except where they explain a non-obvious WHY (matches the existing files' style).
- `requirements-dev.txt` holds test-only dependencies (`pytest`), kept separate from the runtime `requirements.txt`.
- Commit after every task.
- Deviation from the spec text (documented here so it doesn't look like an inconsistency later): the spec shows `safety.after_trade_closed(state, total_trade_net, balance: float = PAPER_BALANCE_USDT)` with a cross-module default. To avoid a circular import between `risk.py` (which defines `PAPER_BALANCE_USDT`) and `safety.py` (which would need it as a default), `balance` is a **required** parameter on `after_trade_closed`, and `risk.py` (the only caller) passes its own existing `PAPER_BALANCE_USDT` constant explicitly at the call site. Same threshold, same behavior, no cycle.

---

### Task 1: Test tooling + safety fields on the data model

**Files:**
- Create: `requirements-dev.txt`
- Create: `conftest.py` (repo root, empty — makes pytest add the repo root to `sys.path` so flat-file modules like `state.py` import cleanly from `tests/`)
- Create: `tests/test_state.py`
- Modify: `state.py:70-82` (`Position` dataclass), `state.py:146-149` (`MarketState` dataclass)

**Interfaces:**
- Produces: `MarketState.consecutive_losses: int`, `MarketState.kill_switch_active: bool`, `MarketState.last_reset_date: Optional[str]`, `Position.fees_paid: float`, `Position.realized_pnl: float`. Every later task's tests run via `.venv/bin/pytest`.

- [x] **Step 1: Create the venv and runtime install**

```bash
cd /home/guille/dev/scalping-bot
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Expected: no errors; `.venv/bin/pip list` shows `websockets`, `ccxt`, `python-dotenv`, `yfinance`.

- [x] **Step 2: Add the dev requirements file and install it**

Create `requirements-dev.txt`:

```
pytest>=8.0.0
```

```bash
.venv/bin/pip install -r requirements-dev.txt
```

Expected: pytest installs cleanly.

- [x] **Step 3: Add the root conftest.py**

Create `conftest.py` (empty file — its presence at the repo root is what makes pytest's default "prepend" import mode add the repo root to `sys.path`):

```python
```

- [x] **Step 4: Write the failing test**

Create `tests/test_state.py`:

```python
from state import MarketState, Position, Side


def test_market_state_defaults_include_safety_fields():
    state = MarketState()
    assert state.consecutive_losses == 0
    assert state.kill_switch_active is False
    assert state.last_reset_date is None


def test_position_defaults_include_fee_tracking_fields():
    pos = Position(
        side=Side.LONG,
        entry_price=100.0,
        size=1.0,
        entry_time=0.0,
        stop_loss=95.0,
        tp1=110.0,
        initial_atr=2.0,
        initial_sl_distance=5.0,
    )
    assert pos.fees_paid == 0.0
    assert pos.realized_pnl == 0.0
```

- [x] **Step 5: Run the test, verify it fails**

```bash
.venv/bin/pytest tests/test_state.py -v
```

Expected: FAIL — `TypeError` or `AttributeError` complaining the fields don't exist yet.

- [x] **Step 6: Add the fields to state.py**

In `state.py`, the `Position` dataclass currently ends with (around line 80-82):

```python
    tp1_hit: bool = False
    breakeven_moved: bool = False
    trailing_stop: Optional[float] = None
```

Change it to:

```python
    tp1_hit: bool = False
    breakeven_moved: bool = False
    trailing_stop: Optional[float] = None
    fees_paid: float = 0.0
    realized_pnl: float = 0.0
```

The `MarketState` dataclass currently ends with (around line 146-148):

```python
    # Session tracking
    trades_today: int = 0
    pnl_today: float = 0.0
```

Change it to:

```python
    # Session tracking
    trades_today: int = 0
    pnl_today: float = 0.0

    # Daily safety / kill switch
    consecutive_losses: int = 0
    kill_switch_active: bool = False
    last_reset_date: Optional[str] = None
```

- [x] **Step 7: Run the test, verify it passes**

```bash
.venv/bin/pytest tests/test_state.py -v
```

Expected: 2 passed.

- [x] **Step 8: Commit**

```bash
git add requirements-dev.txt conftest.py tests/test_state.py state.py
git commit -m "Add pytest tooling and safety fields to MarketState/Position"
```

---

### Task 2: Daily kill switch + JSON persistence (`safety.py`)

**Files:**
- Create: `safety.py`
- Create: `tests/test_safety.py`
- Modify: `config.py` (append constants)

**Interfaces:**
- Consumes: `MarketState.consecutive_losses/kill_switch_active/last_reset_date/pnl_today/trades_today/position` and `Position` (Task 1).
- Produces: `safety.maybe_reset_daily(state: MarketState) -> None`, `safety.can_open_new_position(state: MarketState) -> bool`, `safety.after_trade_closed(state: MarketState, total_trade_net: float, balance: float) -> None`, `safety.save_state(state: MarketState) -> None`, `safety.load_into_state(state: MarketState) -> None`. Task 4 (`risk.py`) calls `after_trade_closed`. Task 7 (`main.py`) calls `can_open_new_position` and `load_into_state`.

- [x] **Step 1: Append new config constants**

In `config.py`, after the existing `# Buffer sizes` block at the end of the file, add:

```python

# Daily kill switch
KILL_SWITCH_DAILY_LOSS_PCT = 0.02       # -2% of balance halts new entries for the rest of the UTC day
KILL_SWITCH_CONSECUTIVE_LOSSES = 3      # 3 losing trades in a row halts new entries

# State persistence
STATE_FILE_PATH = "safety_state.json"
```

- [x] **Step 2: Write the failing tests**

Create `tests/test_safety.py`:

```python
import json

import pytest

import safety
from state import MarketState, Position, Side


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    path = tmp_path / "safety_state.json"
    monkeypatch.setattr(safety, "STATE_FILE_PATH", str(path))
    return path


def test_maybe_reset_daily_resets_counters_on_date_rollover():
    state = MarketState()
    state.last_reset_date = "2020-01-01"
    state.pnl_today = -50.0
    state.trades_today = 4
    state.consecutive_losses = 2
    state.kill_switch_active = True

    safety.maybe_reset_daily(state)

    assert state.pnl_today == 0.0
    assert state.trades_today == 0
    assert state.consecutive_losses == 0
    assert state.kill_switch_active is False
    assert state.last_reset_date == safety._today_utc()


def test_maybe_reset_daily_is_a_noop_when_already_reset_today():
    state = MarketState()
    state.last_reset_date = safety._today_utc()
    state.pnl_today = -50.0

    safety.maybe_reset_daily(state)

    assert state.pnl_today == -50.0


def test_can_open_new_position_false_when_kill_switch_active():
    state = MarketState()
    state.last_reset_date = safety._today_utc()
    state.kill_switch_active = True

    assert safety.can_open_new_position(state) is False


def test_can_open_new_position_true_by_default():
    state = MarketState()

    assert safety.can_open_new_position(state) is True


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


def test_save_then_load_round_trips_open_position(_isolate_state_file):
    state = MarketState()
    state.position = Position(
        side=Side.SHORT,
        entry_price=200.0,
        size=0.5,
        entry_time=123.0,
        stop_loss=210.0,
        tp1=180.0,
        initial_atr=3.0,
        initial_sl_distance=10.0,
        fees_paid=0.05,
        realized_pnl=-0.05,
    )

    safety.save_state(state)

    loaded = MarketState()
    safety.load_into_state(loaded)

    assert loaded.position is not None
    assert loaded.position.side == Side.SHORT
    assert loaded.position.size == pytest.approx(0.5)
    assert loaded.position.realized_pnl == pytest.approx(-0.05)


def test_load_into_state_starts_fresh_when_file_missing(_isolate_state_file):
    state = MarketState()

    safety.load_into_state(state)  # file was never written

    assert state.position is None
    assert state.pnl_today == 0.0


def test_load_into_state_starts_fresh_on_corrupt_json(_isolate_state_file):
    with open(safety.STATE_FILE_PATH, "w") as f:
        f.write("{not valid json")

    state = MarketState()
    safety.load_into_state(state)

    assert state.position is None
    assert state.pnl_today == 0.0


def test_save_state_does_not_raise_when_write_fails(monkeypatch, tmp_path):
    bad_path = tmp_path / "missing_dir" / "safety_state.json"  # parent dir doesn't exist
    monkeypatch.setattr(safety, "STATE_FILE_PATH", str(bad_path))
    state = MarketState()

    safety.save_state(state)  # must not raise
```

- [x] **Step 3: Run the tests, verify they fail**

```bash
.venv/bin/pytest tests/test_safety.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'safety'`.

- [x] **Step 4: Implement safety.py**

Create `safety.py`:

```python
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from config import (
    KILL_SWITCH_CONSECUTIVE_LOSSES,
    KILL_SWITCH_DAILY_LOSS_PCT,
    STATE_FILE_PATH,
)
from state import MarketState, Position, Side

logger = logging.getLogger(__name__)


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


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


def can_open_new_position(state: MarketState) -> bool:
    maybe_reset_daily(state)
    return not state.kill_switch_active


def after_trade_closed(state: MarketState, total_trade_net: float, balance: float) -> None:
    if total_trade_net < 0:
        state.consecutive_losses += 1
    else:
        state.consecutive_losses = 0

    daily_loss_breached = state.pnl_today <= -KILL_SWITCH_DAILY_LOSS_PCT * balance
    streak_breached = state.consecutive_losses >= KILL_SWITCH_CONSECUTIVE_LOSSES

    if (daily_loss_breached or streak_breached) and not state.kill_switch_active:
        state.kill_switch_active = True
        logger.warning(
            "KILL SWITCH activated | daily_loss_breached=%s streak_breached=%s "
            "pnl_today=$%+.2f consecutive_losses=%d",
            daily_loss_breached, streak_breached, state.pnl_today, state.consecutive_losses,
        )

    save_state(state)


def _position_to_dict(pos: Optional[Position]) -> Optional[dict]:
    if pos is None:
        return None
    data = asdict(pos)
    data["side"] = pos.side.value
    return data


def _position_from_dict(data: Optional[dict]) -> Optional[Position]:
    if data is None:
        return None
    data = dict(data)
    data["side"] = Side(data["side"])
    return Position(**data)


def save_state(state: MarketState) -> None:
    payload = {
        "date_utc": state.last_reset_date,
        "pnl_today": state.pnl_today,
        "trades_today": state.trades_today,
        "consecutive_losses": state.consecutive_losses,
        "kill_switch_active": state.kill_switch_active,
        "position": _position_to_dict(state.position),
    }
    try:
        with open(STATE_FILE_PATH, "w") as f:
            json.dump(payload, f)
    except OSError:
        logger.exception("Failed to write %s", STATE_FILE_PATH)


def load_into_state(state: MarketState) -> None:
    try:
        with open(STATE_FILE_PATH, "r") as f:
            payload = json.load(f)
    except FileNotFoundError:
        return
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not parse %s — starting with fresh state", STATE_FILE_PATH)
        return

    state.last_reset_date = payload.get("date_utc")
    state.pnl_today = payload.get("pnl_today", 0.0)
    state.trades_today = payload.get("trades_today", 0)
    state.consecutive_losses = payload.get("consecutive_losses", 0)
    state.kill_switch_active = payload.get("kill_switch_active", False)
    state.position = _position_from_dict(payload.get("position"))
```

Note: `tests/test_safety.py` monkeypatches the module-level `safety.STATE_FILE_PATH` (not `config.STATE_FILE_PATH`) — this works because `save_state`/`load_into_state` reference the name imported into `safety`'s own namespace, so `monkeypatch.setattr(safety, "STATE_FILE_PATH", ...)` correctly redirects file I/O to a temp path during tests without touching the real `config.STATE_FILE_PATH`.

- [x] **Step 5: Run the tests, verify they pass**

```bash
.venv/bin/pytest tests/test_safety.py -v
```

Expected: 12 passed.

- [x] **Step 6: Commit**

```bash
git add config.py safety.py tests/test_safety.py
git commit -m "Add daily kill switch and JSON state persistence"
```

---

### Task 3: Exchange reconciliation on startup (`safety.py`)

**Files:**
- Modify: `safety.py` (append `reconcile_with_exchange` and a private helper)
- Modify: `tests/test_safety.py` (append tests)

**Interfaces:**
- Consumes: `Position`, `Side` from `state.py` (Task 1). Takes a plain `exchange` object with a ccxt-shaped `fetch_positions(symbols: list[str]) -> list[dict]` method — no concrete ccxt dependency, so tests use a fake.
- Produces: `safety.reconcile_with_exchange(state: MarketState, exchange) -> None`. Task 7 (`main.py`) calls this when `not PAPER_MODE`.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_safety.py`:

```python
import sys


class _FakeExchange:
    def __init__(self, positions):
        self._positions = positions

    def fetch_positions(self, symbols):
        return self._positions


class _FailingExchange:
    def fetch_positions(self, symbols):
        raise RuntimeError("network down")


def test_reconcile_ok_when_both_sides_flat():
    state = MarketState()
    exchange = _FakeExchange([])

    safety.reconcile_with_exchange(state, exchange)  # must not raise/exit


def test_reconcile_ok_when_positions_match():
    state = MarketState()
    state.position = Position(
        side=Side.LONG,
        entry_price=100.0,
        size=0.5,
        entry_time=0.0,
        stop_loss=95.0,
        tp1=110.0,
        initial_atr=2.0,
        initial_sl_distance=5.0,
    )
    exchange = _FakeExchange([{"contracts": 0.5, "side": "long"}])

    safety.reconcile_with_exchange(state, exchange)  # must not raise/exit
    assert state.position is not None  # persisted position is left intact


def test_reconcile_exits_on_size_mismatch():
    state = MarketState()
    state.position = Position(
        side=Side.LONG,
        entry_price=100.0,
        size=0.5,
        entry_time=0.0,
        stop_loss=95.0,
        tp1=110.0,
        initial_atr=2.0,
        initial_sl_distance=5.0,
    )
    exchange = _FakeExchange([{"contracts": 0.9, "side": "long"}])

    with pytest.raises(SystemExit):
        safety.reconcile_with_exchange(state, exchange)


def test_reconcile_exits_when_only_exchange_has_a_position():
    state = MarketState()
    exchange = _FakeExchange([{"contracts": 0.5, "side": "long"}])

    with pytest.raises(SystemExit):
        safety.reconcile_with_exchange(state, exchange)


def test_reconcile_exits_on_exchange_query_failure():
    state = MarketState()
    exchange = _FailingExchange()

    with pytest.raises(SystemExit):
        safety.reconcile_with_exchange(state, exchange)
```

- [x] **Step 2: Run the tests, verify they fail**

```bash
.venv/bin/pytest tests/test_safety.py -v -k reconcile
```

Expected: FAIL — `AttributeError: module 'safety' has no attribute 'reconcile_with_exchange'`.

- [x] **Step 3: Implement reconcile_with_exchange**

Append to `safety.py` (add `import sys` to the top imports alongside the existing `import json`):

```python
_SIZE_TOLERANCE_PCT = 0.001  # 0.1% size tolerance when matching persisted vs exchange position


def _fetch_exchange_position(exchange) -> Optional[dict]:
    positions = exchange.fetch_positions(["BTC/USDT"])
    for p in positions:
        contracts = float(p.get("contracts") or 0)
        if contracts > 0:
            side = Side.LONG if p.get("side") == "long" else Side.SHORT
            return {"side": side, "size": contracts}
    return None


def reconcile_with_exchange(state: MarketState, exchange) -> None:
    """Compares the persisted position (already loaded into state.position by
    load_into_state) against the exchange's real reported position. Exits the
    process rather than guessing when they disagree."""
    try:
        exchange_pos = _fetch_exchange_position(exchange)
    except Exception:
        logger.error("Could not fetch exchange positions for reconciliation", exc_info=True)
        sys.exit(1)

    persisted = state.position

    if persisted is None and exchange_pos is None:
        logger.info("Reconciliation OK: no open position on either side")
        return

    if persisted is not None and exchange_pos is not None:
        size_diff_pct = abs(persisted.size - exchange_pos["size"]) / exchange_pos["size"]
        if persisted.side == exchange_pos["side"] and size_diff_pct <= _SIZE_TOLERANCE_PCT:
            logger.info(
                "Reconciliation OK: resuming %s position, size=%.6f",
                persisted.side.value, persisted.size,
            )
            return

    logger.error(
        "RECONCILIATION MISMATCH — persisted=%s exchange=%s — refusing to start, "
        "manual review required",
        persisted, exchange_pos,
    )
    sys.exit(1)
```

- [x] **Step 4: Run the tests, verify they pass**

```bash
.venv/bin/pytest tests/test_safety.py -v
```

Expected: 17 passed.

- [x] **Step 5: Commit**

```bash
git add safety.py tests/test_safety.py
git commit -m "Add exchange position reconciliation on startup"
```

---

### Task 4: Fee-aware PnL and the TP1 fix (`risk.py`)

**Files:**
- Modify: `config.py` (append `TAKER_FEE_RATE` and `SPREAD_FILTER_ATR_PCT`)
- Modify: `risk.py:1-19` (imports), `risk.py:49-74` (`open_position`), `risk.py:77-96` (`close_position`), `risk.py:175-188` (replace `_handle_tp1`), `risk.py:192-224` (`manage_position`)
- Create: `tests/test_risk.py`

**Interfaces:**
- Consumes: `safety.after_trade_closed(state, total_trade_net, balance)` (Task 2), `Position.fees_paid`/`realized_pnl` (Task 1).
- Produces: `risk.open_position(state, side, price, balance=PAPER_BALANCE_USDT) -> None` (now deducts an entry fee), `risk.check_tp1(state) -> Optional[float]` (new, pure), `risk.apply_partial_close(state, close_size: float, fill_price: float) -> float` (new), `risk.close_position(state, price, reason) -> float` (now fee-aware, calls `safety.after_trade_closed`), `risk.manage_position(state) -> tuple[Optional[float], Optional[str]]` (return type changed from `Optional[str]`). Task 5 (`execution.py`) calls `check_tp1` (indirectly via `manage_position`), `apply_partial_close`, `close_position`, `open_position`.

- [x] **Step 1: Append the fee constant**

In `config.py`, after the `STATE_FILE_PATH` line added in Task 2, add:

```python

# Fees
TAKER_FEE_RATE = 0.0005   # 0.05% per side, Binance Futures USDT-M, no BNB discount

# Spread filter
SPREAD_FILTER_ATR_PCT = 0.05  # block entries when spread > 5% of 1m ATR
```

(`SPREAD_FILTER_ATR_PCT` is added here too since it's a one-line addition and avoids a third small edit to `config.py` in Task 6; Task 6 will use it but not redefine it.)

- [x] **Step 2: Write the failing tests**

Create `tests/test_risk.py`:

```python
import pytest

import safety
from config import TAKER_FEE_RATE, TP1_CLOSE_PCT
from risk import (
    PAPER_BALANCE_USDT,
    apply_partial_close,
    check_tp1,
    close_position,
    open_position,
)
from state import MarketState, Side


def _state_with_long_position(entry: float = 100.0, atr: float = 2.0) -> MarketState:
    state = MarketState()
    state.atr = atr
    state.last_price = entry
    open_position(state, Side.LONG, entry)
    return state


def test_open_position_deducts_entry_fee_from_pnl_today():
    state = _state_with_long_position(entry=100.0)
    pos = state.position
    expected_fee = pos.size * 100.0 * TAKER_FEE_RATE

    assert pos.fees_paid == pytest.approx(expected_fee)
    assert pos.realized_pnl == pytest.approx(-expected_fee)
    assert state.pnl_today == pytest.approx(-expected_fee)


def test_check_tp1_returns_close_size_once_when_price_reaches_target():
    state = _state_with_long_position(entry=100.0)
    pos = state.position
    state.last_price = pos.tp1

    close_size = check_tp1(state)

    assert close_size == pytest.approx(round(pos.size * TP1_CLOSE_PCT, 6))
    assert pos.tp1_hit is True
    assert check_tp1(state) is None  # only fires once


def test_check_tp1_returns_none_when_price_has_not_reached_target():
    state = _state_with_long_position(entry=100.0)
    pos = state.position
    state.last_price = pos.entry_price  # nowhere near tp1

    assert check_tp1(state) is None
    assert pos.tp1_hit is False


def test_apply_partial_close_credits_net_pnl_and_shrinks_size():
    state = _state_with_long_position(entry=100.0)
    pos = state.position
    entry_fee = pos.fees_paid
    original_size = pos.size
    close_size = round(original_size * TP1_CLOSE_PCT, 6)

    net = apply_partial_close(state, close_size, fill_price=110.0)

    expected_gross = (110.0 - 100.0) * close_size
    expected_fee = close_size * 110.0 * TAKER_FEE_RATE
    expected_net = expected_gross - expected_fee

    assert net == pytest.approx(expected_net)
    assert pos.size == pytest.approx(original_size - close_size)
    assert pos.fees_paid == pytest.approx(entry_fee + expected_fee)
    assert pos.realized_pnl == pytest.approx(-entry_fee + expected_net)
    assert state.pnl_today == pytest.approx(-entry_fee + expected_net)


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


def test_trade_with_tp1_then_breakeven_exit_uses_total_realized_pnl(monkeypatch):
    state = _state_with_long_position(entry=100.0)
    pos = state.position
    entry_fee = pos.fees_paid
    original_size = pos.size
    close_size = round(original_size * TP1_CLOSE_PCT, 6)

    partial_net = apply_partial_close(state, close_size, fill_price=110.0)

    calls = []
    monkeypatch.setattr(
        safety, "after_trade_closed",
        lambda s, total_net, balance: calls.append(total_net),
    )

    final_net = close_position(state, price=100.0, reason="stop_loss")

    expected_total = (-entry_fee) + partial_net + final_net
    assert calls[0] == pytest.approx(expected_total)


def test_manage_position_returns_tuple_of_tp1_size_and_exit_reason():
    from risk import manage_position

    state = _state_with_long_position(entry=100.0)
    pos = state.position
    state.last_price = pos.stop_loss  # force an immediate stop-loss hit

    tp1_close_size, reason = manage_position(state)

    assert tp1_close_size is None
    assert reason == "stop_loss"
```

- [x] **Step 3: Run the tests, verify they fail**

```bash
.venv/bin/pytest tests/test_risk.py -v
```

Expected: FAIL — `ImportError: cannot import name 'check_tp1' from 'risk'` (and similar for `apply_partial_close`).

- [x] **Step 4: Modify risk.py**

In `risk.py`, update the imports (currently lines 1-19) to add `TAKER_FEE_RATE` and the `safety` module:

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
```

Replace `open_position` (currently lines 49-74):

```python
def open_position(
    state: MarketState,
    side: Side,
    price: float,
    balance: float = PAPER_BALANCE_USDT,
) -> None:
    stop_loss, tp1 = _compute_levels(side, price, state.atr)
    size = _compute_size(price, stop_loss, balance)
    sl_dist = abs(price - stop_loss)
    entry_fee = size * price * TAKER_FEE_RATE

    state.position = Position(
        side=side,
        entry_price=price,
        size=size,
        entry_time=time.time(),
        stop_loss=stop_loss,
        tp1=tp1,
        initial_atr=state.atr,
        initial_sl_distance=sl_dist,
        fees_paid=entry_fee,
        realized_pnl=-entry_fee,
    )
    state.pnl_today -= entry_fee
    state.prior_volume_velocity = state.volume_velocity

    logger.info(
        "OPEN %s @ %.2f | SL=%.2f | TP1=%.2f | size=%.6f BTC | risk=$%.2f | entry_fee=$%.2f",
        side.value.upper(), price, stop_loss, tp1, size, size * sl_dist, entry_fee,
    )
```

Replace `close_position` (currently lines 77-96):

```python
def close_position(state: MarketState, price: float, reason: str) -> float:
    pos = state.position
    if pos is None:
        return 0.0

    gross = (
        (price - pos.entry_price) * pos.size
        if pos.side == Side.LONG
        else (pos.entry_price - price) * pos.size
    )
    fee = pos.size * price * TAKER_FEE_RATE
    net = gross - fee

    pos.fees_paid += fee
    pos.realized_pnl += net

    state.pnl_today += net
    state.trades_today += 1
    total_trade_net = pos.realized_pnl
    state.position = None

    logger.info(
        "CLOSE %s @ %.2f | reason=%-16s | leg_net=$%+.2f | trade_net=$%+.2f | daily=$%+.2f",
        pos.side.value.upper(), price, reason, net, total_trade_net, state.pnl_today,
    )

    safety.after_trade_closed(state, total_trade_net, PAPER_BALANCE_USDT)
    return net
```

Replace `_handle_tp1` (currently lines 175-188) with two new functions:

```python
def check_tp1(state: MarketState) -> Optional[float]:
    """Returns the size (BTC) to close if TP1 is hit for the first time, else None.
    Marks pos.tp1_hit so it only fires once. Does not mutate size or PnL —
    execution.partial_exit applies the real fill via apply_partial_close."""
    pos = state.position
    if pos is None or pos.tp1_hit:
        return None

    price = state.last_price
    hit = (pos.side == Side.LONG and price >= pos.tp1) or \
          (pos.side == Side.SHORT and price <= pos.tp1)

    if not hit:
        return None

    pos.tp1_hit = True
    return round(pos.size * TP1_CLOSE_PCT, 6)


def apply_partial_close(state: MarketState, close_size: float, fill_price: float) -> float:
    """Realizes PnL (net of fee) for a partial close of close_size BTC at fill_price,
    shrinks pos.size accordingly, and returns the net P&L for this leg."""
    pos = state.position
    if pos is None:
        return 0.0

    gross = (
        (fill_price - pos.entry_price) * close_size
        if pos.side == Side.LONG
        else (pos.entry_price - fill_price) * close_size
    )
    fee = close_size * fill_price * TAKER_FEE_RATE
    net = gross - fee

    pos.size = round(pos.size - close_size, 6)
    pos.fees_paid += fee
    pos.realized_pnl += net
    state.pnl_today += net

    logger.info(
        "TP1 hit @ %.2f — closed %.6f BTC | leg_net=$%+.2f | position reduced to %.6f BTC",
        fill_price, close_size, net, pos.size,
    )
    return net
```

Replace `manage_position` (currently lines 192-224):

```python
def manage_position(state: MarketState) -> tuple[Optional[float], Optional[str]]:
    """
    Called on every tick. Returns (tp1_close_size, exit_reason); either can be None.
    Also handles all dynamic SL updates (breakeven, breathing, structural trail).
    """
    from momentum import should_abort_for_momentum

    if state.position is None:
        return None, None

    pos = state.position
    price = state.last_price
    held_min = (time.time() - pos.entry_time) / 60.0

    # Update stops (order matters: breakeven before trail)
    _apply_breakeven(state)
    _apply_breathing_stop(state)
    _apply_structural_trail(state)
    tp1_close_size = check_tp1(state)

    # Exit checks
    sl_hit = (pos.side == Side.LONG and price <= pos.stop_loss) or \
             (pos.side == Side.SHORT and price >= pos.stop_loss)
    if sl_hit:
        return tp1_close_size, "stop_loss"

    if held_min >= TIME_EXIT_MINUTES:
        return tp1_close_size, "time_exit"

    if should_abort_for_momentum(state):
        return tp1_close_size, "momentum_abort"

    return tp1_close_size, None
```

- [x] **Step 5: Run the tests, verify they pass**

```bash
.venv/bin/pytest tests/test_risk.py -v
```

Expected: 7 passed.

- [x] **Step 6: Run the full suite to confirm nothing else broke**

```bash
.venv/bin/pytest -v
```

Expected: all tests passed (Tasks 1-4 combined).

- [x] **Step 7: Commit**

```bash
git add config.py risk.py tests/test_risk.py
git commit -m "Make risk.py fee-aware and fix the TP1 partial-close accounting bug"
```

---

### Task 5: Realistic fills + live partial-exit orders (`execution.py`)

**Files:**
- Modify: `execution.py:1-13` (imports), `execution.py:46-70` (`enter`), `execution.py:72-89` (`exit`), `execution.py:91-97` (`monitor_and_exit`); add a new `partial_exit` method and an `exchange` property.
- Create: `tests/test_execution.py`

**Interfaces:**
- Consumes: `risk.open_position`, `risk.apply_partial_close`, `risk.close_position`, `risk.manage_position` returning `tuple[Optional[float], Optional[str]]` (Task 4).
- Produces: `ExecutionEngine.enter(side: Side) -> bool` (fills at ask/bid), `ExecutionEngine.exit(reason: str) -> float` (fills at bid/ask), `ExecutionEngine.partial_exit(close_size: float, reason: str) -> float` (new), `ExecutionEngine.monitor_and_exit() -> None` (updated), `ExecutionEngine.exchange` (new public property). Task 7 (`main.py`) uses `engine.exchange`.

- [x] **Step 1: Write the failing tests**

Create `tests/test_execution.py`:

```python
import asyncio

import pytest

import execution as execution_module
from execution import ExecutionEngine
from state import MarketState, Side


def _state_with_book(bid: float = 99.0, ask: float = 101.0, last_price: float = 100.0) -> MarketState:
    state = MarketState()
    state.last_bid = bid
    state.last_ask = ask
    state.last_price = last_price
    state.atr = 2.0
    return state


def test_enter_long_fills_at_ask_in_paper_mode():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)

    result = asyncio.run(engine.enter(Side.LONG))

    assert result is True
    assert state.position is not None
    assert state.position.entry_price == pytest.approx(101.0)


def test_enter_short_fills_at_bid_in_paper_mode():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)

    result = asyncio.run(engine.enter(Side.SHORT))

    assert result is True
    assert state.position.entry_price == pytest.approx(99.0)


def test_enter_rejects_when_book_not_yet_received():
    state = MarketState()  # last_bid/last_ask default to 0.0
    state.last_price = 100.0
    engine = ExecutionEngine(state)

    result = asyncio.run(engine.enter(Side.LONG))

    assert result is False
    assert state.position is None


def test_exit_long_fills_at_bid_in_paper_mode():
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    asyncio.run(engine.enter(Side.LONG))

    net = asyncio.run(engine.exit("time_exit"))

    assert state.position is None
    assert isinstance(net, float)


def test_partial_exit_sends_reduce_only_order_in_live_mode(monkeypatch):
    state = _state_with_book(bid=99.0, ask=101.0)
    engine = ExecutionEngine(state)
    asyncio.run(engine.enter(Side.LONG))

    sent_orders = []

    class _FakeExchange:
        def create_market_order(self, symbol, side, amount, params=None):
            sent_orders.append((symbol, side, amount, params))

    engine._exchange = _FakeExchange()
    monkeypatch.setattr(execution_module, "PAPER_MODE", False)

    close_size = round(state.position.size * 0.5, 6)
    asyncio.run(engine.partial_exit(close_size, "tp1"))

    assert len(sent_orders) == 1
    symbol, side, amount, params = sent_orders[0]
    assert symbol == "BTC/USDT"
    assert side == "sell"
    assert amount == pytest.approx(close_size)
    assert params == {"reduceOnly": True}


def test_exchange_property_exposes_underlying_client():
    state = MarketState()
    engine = ExecutionEngine(state)
    engine._exchange = "fake-client"

    assert engine.exchange == "fake-client"
```

- [x] **Step 2: Run the tests, verify they fail**

```bash
.venv/bin/pytest tests/test_execution.py -v
```

Expected: FAIL — entry price assertions fail (still using `last_price`), and `AttributeError: 'ExecutionEngine' object has no attribute 'partial_exit'` / no `exchange` property.

- [x] **Step 3: Modify execution.py**

Update the imports (currently lines 1-13):

```python
from __future__ import annotations

import asyncio
import logging
import os

from risk import apply_partial_close, close_position, manage_position, open_position
from state import MarketState, Side

logger = logging.getLogger(__name__)

PAPER_MODE: bool = os.getenv("PAPER_MODE", "true").lower() == "true"
```

Add the `exchange` property right after `_init_exchange` (which stays as-is):

```python
    @property
    def exchange(self):
        return self._exchange
```

Replace `enter` (currently lines 46-70):

```python
    async def enter(self, side: Side) -> bool:
        if self.state.last_bid <= 0 or self.state.last_ask <= 0:
            return False

        fill_price = self.state.last_ask if side == Side.LONG else self.state.last_bid
        open_position(self.state, side, fill_price)

        if PAPER_MODE or self._exchange is None:
            return True

        pos = self.state.position
        if pos is None:
            return False

        try:
            order_side = "buy" if side == Side.LONG else "sell"
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._exchange.create_market_order("BTC/USDT", order_side, pos.size),
            )
            return True
        except Exception:
            logger.exception("Live entry order failed — position kept in paper")
            return False
```

Replace `exit` (currently lines 72-89):

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

        return close_position(self.state, fill_price, reason)
```

Add `partial_exit` right after `exit`:

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

        return apply_partial_close(self.state, close_size, fill_price)
```

Replace `monitor_and_exit` (currently lines 91-97):

```python
    async def monitor_and_exit(self) -> None:
        """Called on every trade tick. Evaluates TP1 and all exit conditions."""
        if self.state.position is None:
            return
        tp1_close_size, reason = manage_position(self.state)
        if tp1_close_size:
            await self.partial_exit(tp1_close_size, "tp1")
        if reason:
            await self.exit(reason)
```

- [x] **Step 4: Run the tests, verify they pass**

```bash
.venv/bin/pytest tests/test_execution.py -v
```

Expected: 6 passed.

- [x] **Step 5: Run the full suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests passed (Tasks 1-5 combined).

- [x] **Step 6: Commit**

```bash
git add execution.py tests/test_execution.py
git commit -m "Fill orders by crossing the spread and send real TP1 partial-close orders"
```

---

### Task 6: Spread entry filter (`signals.py`)

**Files:**
- Modify: `signals.py:1-10` (imports), `signals.py:66-90` (`check_entry_signal`)
- Create: `tests/test_signals.py`

**Interfaces:**
- Consumes: `config.SPREAD_FILTER_ATR_PCT` (added in Task 4), `MarketState.spread`/`atr` (already existed).
- Produces: updated `signals.check_entry_signal(state: MarketState) -> Optional[Side]` with one more rejection gate. No other task depends on this one.

- [x] **Step 1: Write the failing tests**

Create `tests/test_signals.py`:

```python
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
```

- [x] **Step 2: Run the tests, verify the first passes and confirm the gate doesn't exist yet**

```bash
.venv/bin/pytest tests/test_signals.py -v
```

Expected: `test_entry_signal_allowed_when_spread_within_atr_threshold` PASSES (no spread gate yet, nothing blocks it), `test_entry_signal_rejected_when_spread_exceeds_atr_threshold` FAILS (still returns `Side.LONG` instead of `None`).

- [x] **Step 3: Modify signals.py**

Update the imports (currently lines 1-10):

```python
from __future__ import annotations

import logging
from typing import Optional, Tuple

from config import SPREAD_FILTER_ATR_PCT, SQUEEZE_COMPRESSION_ATR, SQUEEZE_LEVEL_ATR_PROXIMITY, SQUEEZE_MIN_BARS
from order_flow import detect_cvd_divergence, get_book_imbalance
from state import MarketState, Regime, Side

logger = logging.getLogger(__name__)
```

In `check_entry_signal`, right after the `direction is None` check and before the "Hard block: never trade against confirmed 15m trend" comment, insert:

```python
    direction = state.squeeze_direction
    if direction is None:
        return None

    # Spread filter — refuse to trade when the book is abnormally wide
    if state.atr > 0 and state.spread > SPREAD_FILTER_ATR_PCT * state.atr:
        logger.debug(
            "Signal rejected: spread %.4f exceeds %.0f%% of ATR %.4f",
            state.spread, SPREAD_FILTER_ATR_PCT * 100, state.atr,
        )
        return None

    # Hard block: never trade against confirmed 15m trend
```

- [x] **Step 4: Run the tests, verify they pass**

```bash
.venv/bin/pytest tests/test_signals.py -v
```

Expected: 2 passed.

- [x] **Step 5: Run the full suite**

```bash
.venv/bin/pytest -v
```

Expected: all tests passed (Tasks 1-6 combined).

- [x] **Step 6: Commit**

```bash
git add signals.py tests/test_signals.py
git commit -m "Add spread-vs-ATR entry filter"
```

---

### Task 7: Wire it all into main.py

**Files:**
- Modify: `main.py:10-18` (imports), `main.py:30-36` (start of `run()`), `main.py:70-74` (entry-signal gate)

**Interfaces:**
- Consumes: `safety.load_into_state`, `safety.can_open_new_position`, `safety.reconcile_with_exchange` (Tasks 2-3), `ExecutionEngine.exchange` (Task 5), `execution.PAPER_MODE` (already existed).
- Produces: a fully wired `main.run()`. Nothing else depends on this — it's the integration point.

- [x] **Step 1: Modify main.py imports**

Current (lines 10-18):

```python
from context import MacroFilter, update_mtf_trends
from data_feed import DataFeed
from execution import ExecutionEngine
from indicators import detect_swing_points, update_indicators
from momentum import update_volume_velocity
from order_flow import snapshot_cvd_on_close
from regime import update_mtf_trend, update_regime
from signals import check_entry_signal, update_squeeze
from state import Candle, MarketState
```

Change to:

```python
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
```

- [x] **Step 2: Load persisted state and reconcile on startup**

Current start of `run()` (lines 30-36):

```python
async def run() -> None:
    state = MarketState()
    feed = DataFeed(state)
    engine = ExecutionEngine(state)
    macro = MacroFilter(state)
```

Change to:

```python
async def run() -> None:
    state = MarketState()
    safety.load_into_state(state)

    feed = DataFeed(state)
    engine = ExecutionEngine(state)
    macro = MacroFilter(state)

    if not PAPER_MODE:
        safety.reconcile_with_exchange(state, engine.exchange)
```

- [x] **Step 3: Gate new entries on the kill switch**

Current entry-signal check inside `on_candle_1m` (lines 70-74):

```python
        # 7. Check for entry signal (only if flat)
        if state.position is None:
            signal = check_entry_signal(state)
            if signal is not None:
                await engine.enter(signal)
```

Change to:

```python
        # 7. Check for entry signal (only if flat and kill switch is not active)
        if state.position is None and safety.can_open_new_position(state):
            signal = check_entry_signal(state)
            if signal is not None:
                await engine.enter(signal)
```

- [x] **Step 4: Verify main.py imports and runs cleanly in paper mode**

```bash
.venv/bin/python -c "import main"
```

Expected: no output, exit code 0 (confirms no syntax/import errors from the wiring changes).

```bash
timeout 10 .venv/bin/python main.py; echo "exit code: $?"
```

Expected: logs show `BTC Scalping Bot starting — mode=PAPER` and `WebSocket connected to Binance`, then the process is killed by `timeout` after 10s (exit code 124) — that's expected, it just confirms the bot starts and connects without crashing. No real orders are placed; `PAPER_MODE` defaults to `true` when no `.env` is present.

- [x] **Step 5: Run the full test suite one last time**

```bash
.venv/bin/pytest -v
```

Expected: all tests passed (Tasks 1-7 combined, no regressions).

- [x] **Step 6: Commit**

```bash
git add main.py
git commit -m "Wire kill switch and crash-reconciliation into main.py"
```
