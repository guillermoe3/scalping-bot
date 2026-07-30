import json

import pytest

import daily_safety
from config import DRAWDOWN_CIRCUIT_BREAKER_PCT, PAPER_BALANCE_USDT
from daily_state import DailyState


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    path = tmp_path / "daily_safety_state.json"
    monkeypatch.setattr(daily_safety, "DAILY_STATE_FILE_PATH", str(path))
    return path


# --- circuit breaker ---

def test_update_circuit_breaker_trips_at_threshold():
    state = DailyState(usdt_balance=400.0, equity_peak_usdt=1000.0)

    daily_safety.update_circuit_breaker(state, last_price=0.0)

    assert state.breaker_active is True  # drawdown 0.6 >= 0.50


def test_update_circuit_breaker_does_not_trip_below_threshold():
    state = DailyState(usdt_balance=600.0, equity_peak_usdt=1000.0)

    daily_safety.update_circuit_breaker(state, last_price=0.0)

    assert state.breaker_active is False  # drawdown 0.4 < 0.50


def test_update_circuit_breaker_tracks_new_peak():
    state = DailyState(usdt_balance=1500.0, equity_peak_usdt=1000.0)

    daily_safety.update_circuit_breaker(state, last_price=0.0)

    assert state.equity_peak_usdt == pytest.approx(1500.0)
    assert state.breaker_active is False


def test_update_circuit_breaker_calls_hook_once_on_trip():
    state = DailyState(usdt_balance=400.0, equity_peak_usdt=1000.0)
    captured = []

    daily_safety.update_circuit_breaker(state, last_price=0.0, on_breaker_tripped=captured.append)
    daily_safety.update_circuit_breaker(state, last_price=0.0, on_breaker_tripped=captured.append)

    assert len(captured) == 1  # already active the second time — no re-trip
    assert captured[0]["drawdown_pct"] == pytest.approx(0.6)
    assert captured[0]["equity_usdt"] == pytest.approx(400.0)


# --- persistence ---

def test_save_then_load_round_trips_state(_isolate_state_file):
    state = DailyState(btc_balance=0.015, usdt_balance=200.0,
                        equity_peak_usdt=1200.0, breaker_active=True,
                        last_rebalance_date="2026-07-30")
    from daily_state import append_close
    append_close(state, timestamp=1000, close=50000.0)

    daily_safety.save_state(state)
    loaded = DailyState()
    found = daily_safety.load_into_state(loaded)

    assert found is True
    assert loaded.btc_balance == pytest.approx(0.015)
    assert loaded.usdt_balance == pytest.approx(200.0)
    assert loaded.equity_peak_usdt == pytest.approx(1200.0)
    assert loaded.breaker_active is True
    assert loaded.last_rebalance_date == "2026-07-30"
    assert [c.close for c in loaded.closes] == [50000.0]


def test_load_into_state_returns_false_when_file_missing(_isolate_state_file):
    state = DailyState()

    found = daily_safety.load_into_state(state)

    assert found is False
    assert state.btc_balance == 0.0


def test_load_into_state_returns_false_on_corrupt_json(_isolate_state_file):
    with open(daily_safety.DAILY_STATE_FILE_PATH, "w") as f:
        f.write("{not valid json")
    state = DailyState()

    found = daily_safety.load_into_state(state)

    assert found is False


# --- exchange balances / reconciliation ---

class _FakeBalanceExchange:
    def __init__(self, btc, usdt):
        self._btc = btc
        self._usdt = usdt

    def fetch_balance(self):
        return {"total": {"BTC": self._btc, "USDT": self._usdt}}


class _FailingExchange:
    def fetch_balance(self):
        raise RuntimeError("network down")


def test_fetch_spot_balances_returns_btc_and_usdt():
    exchange = _FakeBalanceExchange(0.5, 1000.0)

    btc, usdt = daily_safety.fetch_spot_balances(exchange)

    assert btc == pytest.approx(0.5)
    assert usdt == pytest.approx(1000.0)


def test_fetch_spot_balances_exits_on_failure():
    with pytest.raises(SystemExit):
        daily_safety.fetch_spot_balances(_FailingExchange())


def test_reconcile_ok_within_tolerance():
    state = DailyState(btc_balance=0.5, usdt_balance=1000.0)
    exchange = _FakeBalanceExchange(0.5, 1000.0)

    daily_safety.reconcile_with_exchange(state, exchange)  # must not raise


def test_reconcile_exits_on_mismatch():
    state = DailyState(btc_balance=0.5, usdt_balance=1000.0)
    exchange = _FakeBalanceExchange(0.9, 1000.0)

    with pytest.raises(SystemExit):
        daily_safety.reconcile_with_exchange(state, exchange)


# --- bootstrap ---

def test_ensure_initialized_seeds_paper_balance_when_fresh_and_no_exchange():
    state = DailyState()

    daily_safety.ensure_initialized(state, exchange=None, found_persisted=False, last_price=50000.0)

    assert state.usdt_balance == pytest.approx(PAPER_BALANCE_USDT)
    assert state.btc_balance == 0.0
    assert state.equity_peak_usdt == pytest.approx(PAPER_BALANCE_USDT)


def test_ensure_initialized_seeds_from_exchange_when_fresh_and_live():
    state = DailyState()
    exchange = _FakeBalanceExchange(0.1, 500.0)

    daily_safety.ensure_initialized(state, exchange, found_persisted=False, last_price=50000.0)

    assert state.btc_balance == pytest.approx(0.1)
    assert state.usdt_balance == pytest.approx(500.0)
    assert state.equity_peak_usdt == pytest.approx(0.1 * 50000.0 + 500.0)


def test_ensure_initialized_reconciles_when_persisted_and_live():
    state = DailyState(btc_balance=0.5, usdt_balance=1000.0)
    exchange = _FakeBalanceExchange(0.9, 1000.0)  # mismatch

    with pytest.raises(SystemExit):
        daily_safety.ensure_initialized(state, exchange, found_persisted=True, last_price=50000.0)


def test_ensure_initialized_skips_reconcile_when_persisted_and_paper():
    state = DailyState(btc_balance=0.5, usdt_balance=1000.0)

    daily_safety.ensure_initialized(state, exchange=None, found_persisted=True, last_price=50000.0)  # must not raise

    assert state.btc_balance == pytest.approx(0.5)  # untouched
