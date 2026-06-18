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
