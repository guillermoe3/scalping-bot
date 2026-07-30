import asyncio

import pytest

from config import SPOT_TAKER_FEE_RATE
from daily_execution import DailyExecutionEngine
from daily_state import DailyState, current_exposure_pct


def test_rebalance_noop_when_gap_below_band():
    state = DailyState(usdt_balance=1000.0, btc_balance=0.0)
    engine = DailyExecutionEngine(state)

    result = asyncio.run(engine.rebalance(target_exposure=0.05, last_price=50000.0))

    assert result is False
    assert state.btc_balance == 0.0
    assert state.usdt_balance == pytest.approx(1000.0)


def test_rebalance_buys_toward_target_when_gap_above_band():
    state = DailyState(usdt_balance=1000.0, btc_balance=0.0)
    engine = DailyExecutionEngine(state)

    result = asyncio.run(engine.rebalance(target_exposure=0.50, last_price=50000.0))

    assert result is True
    assert state.btc_balance > 0.0
    assert current_exposure_pct(state, 50000.0) == pytest.approx(0.50, abs=0.01)


def test_rebalance_sells_to_flat_when_target_zero():
    state = DailyState(usdt_balance=50.0, btc_balance=1.0)  # ~74% exposure @ price 140
    engine = DailyExecutionEngine(state)

    result = asyncio.run(engine.rebalance(target_exposure=0.0, last_price=140.0))

    assert result is True
    assert state.btc_balance == pytest.approx(0.0, abs=1e-9)


def test_rebalance_charges_taker_fee_on_buy():
    state = DailyState(usdt_balance=1000.0, btc_balance=0.0)
    engine = DailyExecutionEngine(state)

    asyncio.run(engine.rebalance(target_exposure=0.50, last_price=50000.0))

    expected_btc = 500.0 / 50000.0
    expected_fee = expected_btc * 50000.0 * SPOT_TAKER_FEE_RATE
    assert state.usdt_balance == pytest.approx(1000.0 - 500.0 - expected_fee)
    assert state.btc_balance == pytest.approx(expected_btc)


def test_rebalance_calls_on_rebalanced_hook_with_trade_details():
    state = DailyState(usdt_balance=1000.0, btc_balance=0.0)
    captured = []
    engine = DailyExecutionEngine(state, on_rebalanced=captured.append)

    asyncio.run(engine.rebalance(target_exposure=0.50, last_price=50000.0))

    assert len(captured) == 1
    assert captured[0]["side"] == "buy"
    assert captured[0]["price"] == pytest.approx(50000.0)


def test_rebalance_hook_not_called_when_below_band():
    state = DailyState(usdt_balance=1000.0, btc_balance=0.0)
    captured = []
    engine = DailyExecutionEngine(state, on_rebalanced=captured.append)

    asyncio.run(engine.rebalance(target_exposure=0.05, last_price=50000.0))

    assert captured == []


def test_paper_mode_engine_has_no_exchange():
    state = DailyState()
    engine = DailyExecutionEngine(state)

    assert engine.exchange is None
