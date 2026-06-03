from __future__ import annotations

from dataclasses import dataclass


LINE_DOWN = "Line Down"
NON_CRITICAL = "Non-Critical"
NO_ISSUES = "No Issues"
UNKNOWN_ERROR = "Unknown/Error"

ACTIVE_SEVERITIES = (LINE_DOWN, NON_CRITICAL)
STATUS_ORDER = (LINE_DOWN, NON_CRITICAL, NO_ISSUES, UNKNOWN_ERROR)


@dataclass(frozen=True)
class Machine:
    machine_number: str
    name: str
    area: str
    cell: str
    asset_tag: str
    display_order: int


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


def status_from_counts(line_down_count: int, non_critical_count: int, total_open: int) -> str:
    if line_down_count > 0:
        return LINE_DOWN
    if non_critical_count > 0:
        return NON_CRITICAL
    if total_open == 0:
        return NO_ISSUES
    return UNKNOWN_ERROR
