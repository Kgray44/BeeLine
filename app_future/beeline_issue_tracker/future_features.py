from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from beeline_issue_tracker.domain import Issue, LINE_DOWN, ResolvedIssue


NEW_ISSUE_MINUTES = 30
AGING_ISSUE_MINUTES = 120
DEFAULT_STALE_HOURS = 8
DEFAULT_CRITICAL_AGING_MINUTES = 120


@dataclass(frozen=True)
class IssueAge:
    label: str
    state: str
    minutes_open: int
    minutes_since_update: int


@dataclass(frozen=True)
class PriorityIssue:
    issue: Issue
    machine_name: str
    area: str
    cell: str
    machine_open_count: int
    category_open_count: int
    priority: str
    age: IssueAge


@dataclass(frozen=True)
class KnownFix:
    pattern: str
    category: str
    solution_preview: str
    times_seen: int
    last_used: str
    related_issue_id: int


@dataclass(frozen=True)
class IntakeSuggestion:
    issue_id: int
    title: str
    category: str
    solution_preview: str
    resolved_at: str
    confidence: str


@dataclass(frozen=True)
class MachineOpenCluster:
    machine_number: str
    machine_name: str
    open_count: int
    line_down_count: int


@dataclass(frozen=True)
class ShiftHandoffSummary:
    start_at: str
    end_at: str
    current_line_down: list[Issue]
    current_stale: list[Issue]
    opened: list[Issue]
    resolved: list[ResolvedIssue]
    multiple_open: list[MachineOpenCluster]
    recurring_patterns: list[KnownFix]
    archive_pending_count: int
    archive_failed_count: int


@dataclass(frozen=True)
class DataHealthSummary:
    db_path: str
    db_exists: bool
    runtime_config_path: str
    archive_path: str
    archive_path_exists: bool
    machine_count: int
    active_issue_count: int
    resolved_cache_count: int
    archive_pending_count: int
    archive_failed_count: int
    last_resolved_label: str
    last_archive_success: str


def pi_mode_enabled() -> bool:
    return os.environ.get("BEELINE_PI_MODE", "").strip().casefold() in {"1", "true", "yes", "on"}


def stale_minutes_from_environment() -> int:
    return _env_int("BEELINE_STALE_HOURS", DEFAULT_STALE_HOURS, minimum=1, maximum=72) * 60


def critical_aging_minutes_from_environment() -> int:
    return _env_int(
        "BEELINE_CRITICAL_AGING_MINUTES",
        DEFAULT_CRITICAL_AGING_MINUTES,
        minimum=30,
        maximum=24 * 60,
    )


def issue_age(issue: Issue, *, now: datetime | None = None) -> IssueAge:
    current = _coerce_now(now)
    created = _parse_iso(issue.created_at) or current
    updated = _parse_iso(issue.updated_at) or created
    minutes_open = max(0, int((current - created).total_seconds() // 60))
    minutes_since_update = max(0, int((current - updated).total_seconds() // 60))

    state = "Active"
    if issue.severity == LINE_DOWN and minutes_open >= critical_aging_minutes_from_environment():
        state = "Critical Aging"
    elif minutes_open >= stale_minutes_from_environment():
        state = "Stale"
    elif minutes_open >= AGING_ISSUE_MINUTES:
        state = "Aging"
    elif minutes_open < NEW_ISSUE_MINUTES:
        state = "New"

    return IssueAge(
        label=duration_label(minutes_open),
        state=state,
        minutes_open=minutes_open,
        minutes_since_update=minutes_since_update,
    )


def priority_label(issue: Issue, machine_open_count: int, category_open_count: int, age: IssueAge) -> str:
    if issue.severity == LINE_DOWN and age.state in {"Critical Aging", "Stale"}:
        return "P1"
    if issue.severity == LINE_DOWN:
        return "P2"
    if machine_open_count >= 2 or category_open_count >= 2 or age.state in {"Aging", "Stale"}:
        return "P3"
    return "P4"


def normalized_pattern_key(title: str, category: str = "") -> str:
    words = re.findall(r"[a-z0-9]+", f"{category} {title}".casefold())
    compact = [word for word in words if len(word) >= 3]
    return " ".join(compact[:10])


def duration_label(minutes: int) -> str:
    minutes = max(0, int(minutes))
    hours = minutes // 60
    days = hours // 24
    if days:
        return f"{days}d {hours % 24}h"
    if hours:
        return f"{hours}h {minutes % 60}m"
    if minutes:
        return f"{minutes}m"
    return "<1m"


def preview(value: str, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text or "-"
    return text[: max(0, limit - 3)].rstrip() + "..."


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    if value < minimum or value > maximum:
        return default
    return value
