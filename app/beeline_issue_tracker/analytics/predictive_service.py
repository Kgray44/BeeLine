from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from beeline_issue_tracker.analytics.models import (
    FixSuggestion,
    MachineRiskSummary,
    MachineTrendPoint,
    PredictiveMaintenanceAlert,
    RecurringIssuePattern,
    RelatedIssueMatch,
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LEVELS,
)
from beeline_issue_tracker.analytics.risk_engine import (
    build_machine_risk_summary,
    detect_recurring_patterns_for_machine,
)
from beeline_issue_tracker.analytics.text_match import build_fix_suggestions, find_related_resolved_issues
from beeline_issue_tracker.config import AnalyticsConfig
from beeline_issue_tracker.data.analytics_repository import AnalyticsRepository, build_trend_points_from_records
from beeline_issue_tracker.domain import Issue


class PredictiveMaintenanceService:
    def __init__(
        self,
        repository: AnalyticsRepository,
        *,
        now_provider=None,
        settings: AnalyticsConfig | None = None,
    ):
        self.repository = repository
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.settings = settings or AnalyticsConfig()

    def get_all_machine_risks(self) -> list[MachineRiskSummary]:
        if not self.settings.enabled:
            return []
        risks = [
            build_machine_risk_summary(risk_input, now=self._now())
            for risk_input in self.repository.get_all_machine_risk_inputs()
        ]
        return sort_machine_risks(risks, sort_key="risk_score")

    def get_machine_risk(self, machine_number: str) -> MachineRiskSummary | None:
        if not self.settings.enabled:
            return None
        for risk_input in self.repository.get_all_machine_risk_inputs():
            if risk_input.machine_number == machine_number:
                return build_machine_risk_summary(risk_input, now=self._now())
        return None

    def get_predictive_alerts(self, limit: int = 20) -> list[PredictiveMaintenanceAlert]:
        if not self.settings.enabled:
            return []
        now = self._now().isoformat()
        alerts: list[PredictiveMaintenanceAlert] = []
        risks = self.get_all_machine_risks()
        for risk in risks:
            if risk.risk_level in {RISK_CRITICAL, RISK_HIGH}:
                alerts.append(
                    PredictiveMaintenanceAlert(
                        machine_number=risk.machine_number,
                        machine_name=risk.machine_name,
                        risk_level=risk.risk_level,
                        risk_score=risk.risk_score,
                        title=f"{risk.risk_level} risk: Machine {risk.machine_number}",
                        message=f"{risk.predicted_problem} | {risk.predicted_window}",
                        reasons=risk.risk_reasons[:4],
                        suggested_action=risk.suggested_action,
                        created_at=now,
                        alert_type="machine_risk",
                    )
                )

        for pattern in self.get_recurring_patterns(days=self.settings.recurrence_window_days):
            risk = next((item for item in risks if item.machine_number == pattern.machine_number), None)
            risk_level = risk.risk_level if risk else RISK_HIGH
            risk_score = risk.risk_score if risk else self.settings.high_risk_threshold
            alerts.append(
                PredictiveMaintenanceAlert(
                    machine_number=pattern.machine_number,
                    machine_name=risk.machine_name if risk else "",
                    risk_level=risk_level,
                    risk_score=risk_score,
                    title=f"Recurring pattern: {pattern.display_label}",
                    message=pattern.risk_note,
                    reasons=(f"{pattern.occurrence_count} matching issue(s)",),
                    suggested_action=(
                        f"Review prior fix: {pattern.common_solutions[0]}"
                        if pattern.common_solutions
                        else f"Inspect recurring {pattern.category or pattern.display_label} problems."
                    ),
                    created_at=now,
                    alert_type="recurrence",
                )
            )

        deduped: list[PredictiveMaintenanceAlert] = []
        seen: set[tuple[str, str, str, str]] = set()
        for alert in sorted(alerts, key=lambda item: (item.risk_score, item.created_at), reverse=True):
            key = (alert.machine_number, alert.alert_type, alert.title, alert.risk_level)
            if key in seen:
                continue
            seen.add(key)
            if self.repository.is_predictive_alert_dismissed(alert):
                continue
            if self.settings.persist_predictive_alerts:
                persisted = self.repository.persist_predictive_alert_if_new(alert)
                alert = replace(persisted, machine_name=alert.machine_name)
            deduped.append(alert)
            if len(deduped) >= max(0, int(limit)):
                break
        return deduped

    def dismiss_alert(self, alert_id: int, *, dismissed_by: str = "") -> None:
        self.repository.dismiss_predictive_alert(alert_id, dismissed_by=dismissed_by)

    def get_recurring_patterns(
        self,
        machine_number: str | None = None,
        days: int = 60,
    ) -> list[RecurringIssuePattern]:
        if not self.settings.enabled:
            return []
        patterns: list[RecurringIssuePattern] = []
        for risk_input in self.repository.get_all_machine_risk_inputs():
            if machine_number and risk_input.machine_number != machine_number:
                continue
            issues = list(risk_input.active_issues) + list(risk_input.resolved_issues)
            patterns.extend(
                detect_recurring_patterns_for_machine(
                    risk_input.machine_number,
                    issues,
                    now=self._now(),
                    days=days,
                )
            )
        patterns.sort(key=lambda pattern: (pattern.occurrence_count, pattern.last_seen_at), reverse=True)
        return patterns

    def get_related_issues_for_active_issue(self, issue_id: int, limit: int = 5) -> list[RelatedIssueMatch]:
        if not self.settings.enabled or not self.settings.enable_related_issues:
            return []
        current = self.repository.issue_repository.get_active_issue(issue_id)
        if current is None:
            return []
        resolved_history = self.repository.list_all_resolved_history(limit=500)
        return find_related_resolved_issues(current, resolved_history, limit=limit)

    def get_related_issues_for_resolved_issue(self, resolved_issue_id: int, limit: int = 5) -> list[RelatedIssueMatch]:
        if not self.settings.enabled or not self.settings.enable_related_issues:
            return []
        resolved = self.repository.issue_repository.get_resolved_issue(resolved_issue_id)
        if resolved is None:
            return []
        current_like = Issue(
            id=resolved.original_issue_id,
            machine_number=resolved.machine_number,
            logged_by=resolved.logged_by,
            title=resolved.title,
            description=resolved.description,
            severity=resolved.severity,
            category=resolved.category,
            created_at=resolved.created_at,
            updated_at=resolved.resolved_at,
            public_issue_id=resolved.public_issue_id,
        )
        resolved_history = [
            issue
            for issue in self.repository.list_all_resolved_history(limit=500)
            if issue.id != resolved_issue_id
        ]
        return find_related_resolved_issues(current_like, resolved_history, limit=limit)

    def get_fix_suggestions_for_active_issue(self, issue_id: int, limit: int = 5) -> list[FixSuggestion]:
        if not self.settings.enabled or not self.settings.enable_fix_suggestions:
            return []
        current = self.repository.issue_repository.get_active_issue(issue_id)
        if current is None:
            return []
        resolved_history = self.repository.list_all_resolved_history(limit=500)
        related = find_related_resolved_issues(current, resolved_history, limit=limit)
        return build_fix_suggestions(related, resolved_history, limit=limit)

    def get_machine_trend(
        self,
        machine_number: str,
        bucket: str = "week",
        periods: int = 8,
    ) -> list[MachineTrendPoint]:
        if not self.settings.enabled:
            return []
        return build_trend_points_from_records(
            self.repository.list_all_issue_history(machine_number),
            now=self._now(),
            bucket=bucket,
            periods=periods,
        )

    def get_global_trend(
        self,
        bucket: str = "week",
        periods: int = 8,
    ) -> list[MachineTrendPoint]:
        if not self.settings.enabled:
            return []
        return build_trend_points_from_records(
            self.repository.list_all_issue_history(),
            now=self._now(),
            bucket=bucket,
            periods=periods,
        )

    def get_category_breakdown(self, machine_number: str | None = None, days: int = 30) -> dict[str, int]:
        if not self.settings.enabled:
            return {}
        return self.repository.get_category_counts(machine_number=machine_number, days=days)

    def get_severity_breakdown(self, machine_number: str | None = None, days: int = 30) -> dict[str, int]:
        if not self.settings.enabled:
            return {}
        return self.repository.get_severity_counts(machine_number=machine_number, days=days)

    def _now(self) -> datetime:
        now = self.now_provider()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)


def filter_machine_risks(
    risks: list[MachineRiskSummary],
    *,
    query: str = "",
    risk_level: str = "",
) -> list[MachineRiskSummary]:
    terms = [term for term in " ".join(query.casefold().split()).split(" ") if term]
    level = risk_level if risk_level in RISK_LEVELS else ""
    filtered: list[MachineRiskSummary] = []
    for risk in risks:
        if level and risk.risk_level != level:
            continue
        haystack = " ".join(
            (
                risk.machine_number,
                risk.machine_name,
                risk.area,
                risk.cell,
                risk.risk_level,
                risk.predicted_problem,
                risk.suggested_action,
            )
        ).casefold()
        if terms and not all(term in haystack for term in terms):
            continue
        filtered.append(risk)
    return filtered


def sort_machine_risks(risks: list[MachineRiskSummary], *, sort_key: str = "risk_score") -> list[MachineRiskSummary]:
    if sort_key == "machine_asc":
        return sorted(risks, key=lambda risk: risk.machine_number.casefold())
    if sort_key == "recent_issue_count":
        return sorted(risks, key=lambda risk: (-risk.recent_issue_count, -risk.risk_score, risk.machine_number))
    if sort_key == "open_issue_count":
        return sorted(risks, key=lambda risk: (-risk.open_issue_count, -risk.risk_score, risk.machine_number))
    return sorted(risks, key=lambda risk: (-risk.risk_score, risk.machine_number.casefold()))
