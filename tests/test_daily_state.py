import pytest

from config import DAILY_CLOSES_BUFFER
from daily_state import DailyState, append_close, close_values, current_equity_usdt, current_exposure_pct


def test_append_close_adds_to_history():
    state = DailyState()

    append_close(state, timestamp=1000, close=50000.0)

    assert close_values(state) == [50000.0]


def test_append_close_respects_maxlen():
    state = DailyState()

    for i in range(DAILY_CLOSES_BUFFER + 10):
        append_close(state, timestamp=i, close=float(i))

    assert len(state.closes) == DAILY_CLOSES_BUFFER
    assert close_values(state)[0] == 10.0  # the oldest 10 entries were trimmed
    assert close_values(state)[-1] == float(DAILY_CLOSES_BUFFER + 9)


def test_current_equity_usdt_sums_cash_and_btc_value():
    state = DailyState(usdt_balance=1000.0, btc_balance=0.02)

    assert current_equity_usdt(state, last_price=50000.0) == pytest.approx(2000.0)


def test_current_exposure_pct_fraction_in_btc():
    state = DailyState(usdt_balance=1000.0, btc_balance=0.02)

    assert current_exposure_pct(state, last_price=50000.0) == pytest.approx(0.5)


def test_current_exposure_pct_zero_when_equity_is_zero():
    state = DailyState()

    assert current_exposure_pct(state, last_price=50000.0) == 0.0
