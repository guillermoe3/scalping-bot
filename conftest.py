import pytest

import config
import signals


@pytest.fixture(autouse=True)
def _reset_signal_globals():
    compression = config.SQUEEZE_COMPRESSION_ATR
    min_bars = config.SQUEEZE_MIN_BARS
    yield
    signals.ENTRY_VARIANT = "fade"
    signals.DISABLED_GATES = set()
    signals.reset_signal_stats()
    config.SQUEEZE_COMPRESSION_ATR = compression
    config.SQUEEZE_MIN_BARS = min_bars
