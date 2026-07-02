import asyncio
import sys

import pandas as pd
import pytest
import yfinance as yf

from context import MacroFilter, _pearson
from state import Candle, MarketState, Side


def _candle(close: float, index: int = 0) -> Candle:
    return Candle(open=close, high=close, low=close, close=close, volume=0.0, timestamp=index * 900_000)


def _fake_download(closes):
    def fake(*args, **kwargs):
        return pd.DataFrame({"Close": closes})
    return fake


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
