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
