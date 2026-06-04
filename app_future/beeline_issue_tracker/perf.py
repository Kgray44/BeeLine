from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone


logger = logging.getLogger("beeline_issue_tracker.perf")

_DISABLED_VALUES = {"0", "false", "no", "off"}
_RECENT_OPERATIONS_MAX = 80


@dataclass(frozen=True)
class PerfSample:
    event: str
    elapsed_ms: int
    level: str
    created_at: str
    details: str


_RECENT_OPERATIONS: deque[PerfSample] = deque(maxlen=_RECENT_OPERATIONS_MAX)


def now() -> float:
    return time.perf_counter()


def elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def log(event: str, **fields: object) -> None:
    if os.environ.get("BEELINE_PERF_LOG", "1").strip().casefold() in _DISABLED_VALUES:
        return
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    if details:
        logger.info("[PERF] %s %s", event, details)
    else:
        logger.info("[PERF] %s", event)
    _record_recent_operation(event, fields, details)


def recent_operations(limit: int = 20) -> list[PerfSample]:
    rows = list(_RECENT_OPERATIONS)
    rows.reverse()
    return rows[: max(0, int(limit))]


def _record_recent_operation(event: str, fields: dict[str, object], details: str) -> None:
    elapsed_value = fields.get("elapsed_ms")
    if elapsed_value is None:
        return
    try:
        elapsed = int(elapsed_value)
    except (TypeError, ValueError):
        return
    if elapsed >= 5000:
        level = "critical"
    elif elapsed >= 1000:
        level = "slow"
    elif elapsed >= 500:
        level = "warning"
    else:
        level = "ok"
    _RECENT_OPERATIONS.append(
        PerfSample(
            event=event,
            elapsed_ms=elapsed,
            level=level,
            created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            details=details,
        )
    )
