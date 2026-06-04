from __future__ import annotations

from dataclasses import dataclass


RISK_CRITICAL = "Critical"
RISK_HIGH = "High"
RISK_MEDIUM = "Medium"
RISK_LOW = "Low"
RISK_STABLE = "Stable"
RISK_UNKNOWN = "Unknown"

RISK_LEVELS = (
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_MEDIUM,
    RISK_LOW,
    RISK_STABLE,
    RISK_UNKNOWN,
)


@dataclass(frozen=True)
class MachineRiskSummary:
    machine_number: str
    machine_name: str
    area: str
    cell: str
    risk_score: int
    risk_level: str
    risk_reasons: tuple[str, ...]
    open_issue_count: int
    line_down_open_count: int
    non_critical_open_count: int
    recent_issue_count: int
    recent_line_down_count: int
    recurring_issue_count: int
    average_time_open_minutes: int | None
    last_issue_at: str
    predicted_problem: str
    suggested_action: str
    predicted_window: str
    confidence: str


@dataclass(frozen=True)
class RecurringIssuePattern:
    machine_number: str
    pattern_key: str
    display_label: str
    category: str
    severity: str
    occurrence_count: int
    first_seen_at: str
    last_seen_at: str
    average_time_between_days: float | None
    example_titles: tuple[str, ...]
    common_solutions: tuple[str, ...]
    risk_note: str


@dataclass(frozen=True)
class RelatedIssueMatch:
    issue_id: int
    original_issue_id: int | None
    machine_number: str
    title: str
    description_preview: str
    solution_preview: str
    severity: str
    category: str
    created_at: str
    resolved_at: str | None
    match_score: int
    match_reasons: tuple[str, ...]


@dataclass(frozen=True)
class FixSuggestion:
    title: str
    suggestion: str
    confidence: str
    based_on_count: int
    supporting_issue_ids: tuple[int, ...]
    caution: str


@dataclass(frozen=True)
class MachineTrendPoint:
    period_label: str
    start_at: str
    end_at: str
    open_count: int
    resolved_count: int
    line_down_count: int
    non_critical_count: int
    average_time_open_minutes: int | None


@dataclass(frozen=True)
class PredictiveMaintenanceAlert:
    machine_number: str
    machine_name: str
    risk_level: str
    risk_score: int
    title: str
    message: str
    reasons: tuple[str, ...]
    suggested_action: str
    created_at: str
    alert_type: str
    id: int | None = None


@dataclass(frozen=True)
class IssueHistoryRecord:
    issue_id: int
    original_issue_id: int | None
    machine_number: str
    machine_name: str
    area: str
    cell: str
    title: str
    description: str
    severity: str
    category: str
    created_at: str
    updated_at: str
    resolved_at: str | None
    solution: str
    is_active: bool


@dataclass(frozen=True)
class MachineRiskInput:
    machine_number: str
    machine_name: str
    area: str
    cell: str
    asset_tag: str
    display_order: int
    active_issues: tuple[object, ...]
    resolved_issues: tuple[object, ...]
