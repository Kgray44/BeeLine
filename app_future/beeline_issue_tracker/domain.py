from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re


LINE_DOWN = "Line Down"
NON_CRITICAL = "Non-Critical"
NO_ISSUES = "No Issues"
UNKNOWN_ERROR = "Unknown/Error"

ACTIVE_SEVERITIES = (LINE_DOWN, NON_CRITICAL)
STATUS_ORDER = (LINE_DOWN, NON_CRITICAL, NO_ISSUES, UNKNOWN_ERROR)
ISSUE_ID_PATTERN = re.compile(r"^ISS-(\d{8})-(\d{3})$")


@dataclass(frozen=True)
class Machine:
    machine_number: str
    name: str
    area: str
    cell: str
    asset_tag: str
    display_order: int
    manufacturer: str
    model: str
    imm_serial: str
    robot_type: str
    robot_model: str
    robot_serial: str


@dataclass(frozen=True)
class MachineSummary(Machine):
    calculated_status: str
    open_issue_count: int


@dataclass(frozen=True)
class Issue:
    id: int
    machine_number: str
    logged_by: str
    title: str
    description: str
    severity: str
    category: str
    created_at: str
    updated_at: str
    public_issue_id: str = ""
    what_changed: str = ""
    tried_already: str = ""


@dataclass(frozen=True)
class IssueSearchResult:
    state: str
    issue_id: int
    machine_number: str
    machine_name: str
    machine_model: str
    title: str
    description: str
    status: str
    category: str
    logged_by: str
    created_at: str
    updated_at: str
    resolved_at: str
    resolved_by: str
    resolution: str
    history_text: str
    public_issue_id: str = ""
    source: str = ""


@dataclass(frozen=True)
class ResolvedIssue:
    id: int
    original_issue_id: int
    machine_number: str
    logged_by: str
    title: str
    description: str
    severity: str
    category: str
    created_at: str
    resolved_at: str
    resolved_by: str
    solution: str
    archive_status: str
    archive_error: str
    public_issue_id: str = ""
    what_changed: str = ""
    tried_already: str = ""


@dataclass(frozen=True)
class IssueEvent:
    id: int
    issue_id: int | None
    original_issue_id: int | None
    machine_number: str
    event_type: str
    actor: str
    created_at: str
    details_json: str


@dataclass(frozen=True)
class IssueAttachment:
    id: int
    issue_id: int | None
    resolved_issue_id: int | None
    machine_number: str
    file_path: str
    original_filename: str
    note: str
    created_at: str
    created_by: str


@dataclass(frozen=True)
class MachineResolvedStats:
    machine_number: str
    total_resolved: int
    most_common_category: str
    most_common_title: str
    last_resolved_title: str
    last_resolved_at: str
    average_time_open_seconds: int | None
    recurring_warning: str


@dataclass(frozen=True)
class IssueWithMachineContext:
    issue: Issue
    machine: MachineSummary | None


@dataclass(frozen=True)
class ResolvedIssueWithMachineContext:
    issue: ResolvedIssue
    machine: MachineSummary | None


def status_from_counts(line_down_count: int, non_critical_count: int, total_open: int) -> str:
    if line_down_count > 0:
        return LINE_DOWN
    if non_critical_count > 0:
        return NON_CRITICAL
    if total_open == 0:
        return NO_ISSUES
    return UNKNOWN_ERROR


def generate_issue_id(created_at: str | datetime, existing_issues) -> str:
    date_key = issue_id_date_key(created_at)
    used_sequences: set[int] = set()
    used_ids: set[str] = set()

    for existing in existing_issues:
        existing_id = _extract_public_issue_id(existing)
        match = ISSUE_ID_PATTERN.match(existing_id)
        if not match:
            continue
        used_ids.add(existing_id)
        if match.group(1) == date_key:
            used_sequences.add(int(match.group(2)))

    next_sequence = (max(used_sequences) + 1) if used_sequences else 1
    while next_sequence <= 999:
        candidate = f"ISS-{date_key}-{next_sequence:03d}"
        if candidate not in used_ids:
            return candidate
        next_sequence += 1

    raise ValueError(f"Issue ID sequence exhausted for {date_key}.")


def issue_id_date_key(created_at: str | datetime) -> str:
    if isinstance(created_at, datetime):
        return created_at.strftime("%Y%m%d")

    text = str(created_at or "").strip()
    if not text:
        raise ValueError("Issue creation date is required for issue ID generation.")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(normalized).strftime("%Y%m%d")
    except ValueError:
        pass

    for pattern, length in (("%Y-%m-%d", 10), ("%Y%m%d", 8)):
        try:
            return datetime.strptime(text[:length], pattern).strftime("%Y%m%d")
        except ValueError:
            continue
    raise ValueError(f"Could not parse issue creation date: {created_at!r}")


def display_issue_id(issue) -> str:
    public_issue_id = str(getattr(issue, "public_issue_id", "") or "").strip()
    if public_issue_id:
        return public_issue_id
    fallback = getattr(issue, "original_issue_id", None)
    if fallback is None:
        fallback = getattr(issue, "id", "")
    return str(fallback)


def issue_id_sort_key(issue) -> str:
    public_issue_id = str(getattr(issue, "public_issue_id", "") or "").strip()
    if public_issue_id:
        return public_issue_id.casefold()
    fallback = getattr(issue, "original_issue_id", None)
    if fallback is None:
        fallback = getattr(issue, "id", "")
    try:
        return f"{int(fallback):012d}"
    except (TypeError, ValueError):
        return str(fallback).casefold()


def _extract_public_issue_id(existing) -> str:
    if isinstance(existing, str):
        return existing.strip()
    for key in ("public_issue_id", "issue_id"):
        try:
            value = existing[key]
        except (KeyError, IndexError, TypeError):
            value = getattr(existing, key, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
