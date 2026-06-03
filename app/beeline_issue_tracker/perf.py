from __future__ import annotations

import logging
import os
import time


logger = logging.getLogger("beeline_issue_tracker.perf")

_DISABLED_VALUES = {"0", "false", "no", "off"}


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
