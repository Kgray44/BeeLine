from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from beeline_issue_tracker.analytics.models import (
    IssueHistoryRecord,
    MachineRiskInput,
    MachineTrendPoint,
    PredictiveMaintenanceAlert,
)
from beeline_issue_tracker.data.database import connect
from beeline_issue_tracker.data.repository import IssueRepository, utc_now_iso
from beeline_issue_tracker.domain import Issue, ResolvedIssue


class AnalyticsRepository:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.issue_repository = IssueRepository(db_path)

    def list_all_issue_history(self, machine_number: str | None = None) -> list[IssueHistoryRecord]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    ai.id AS issue_id,
                    ai.id AS original_issue_id,
                    ai.machine_number,
                    m.name AS machine_name,
                    m.area,
                    m.cell,
                    ai.title,
                    ai.description,
                    ai.severity,
                    ai.category,
                    ai.created_at,
                    ai.updated_at,
                    NULL AS resolved_at,
                    '' AS solution,
                    1 AS is_active
                FROM active_issues ai
                INNER JOIN machines m ON m.machine_number = ai.machine_number
                WHERE m.is_active = 1 AND (? IS NULL OR ai.machine_number = ?)
                UNION ALL
                SELECT
                    ri.id AS issue_id,
                    ri.original_issue_id,
                    ri.machine_number,
                    m.name AS machine_name,
                    m.area,
                    m.cell,
                    ri.title,
                    ri.description,
                    ri.severity,
                    ri.category,
                    ri.created_at,
                    ri.resolved_at AS updated_at,
                    ri.resolved_at,
                    ri.solution,
                    0 AS is_active
                FROM resolved_issues_cache ri
                INNER JOIN machines m ON m.machine_number = ri.machine_number
                WHERE m.is_active = 1 AND (? IS NULL OR ri.machine_number = ?)
                ORDER BY created_at DESC, issue_id DESC
                """,
                (machine_number, machine_number, machine_number, machine_number),
            ).fetchall()
        return [self._history_from_row(row) for row in rows]

    def list_recent_issue_activity(self, days: int = 30) -> list[IssueHistoryRecord]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, int(days)))
        return [
            record
            for record in self.list_all_issue_history()
            if _record_time(record) is not None and _record_time(record) >= cutoff
        ]

    def list_machine_resolved_history(self, machine_number: str, limit: int | None = None) -> list[ResolvedIssue]:
        return self.issue_repository.list_resolved_issues(machine_number, limit=limit)

    def list_all_resolved_history(self, limit: int | None = None) -> list[ResolvedIssue]:
        with connect(self.db_path) as conn:
            sql = """
                SELECT
                    id,
                    issue_id AS public_issue_id,
                    original_issue_id,
                    machine_number,
                    logged_by,
                    title,
                    description,
                    severity,
                    category,
                    created_at,
                    resolved_at,
                    resolved_by,
                    solution,
                    archive_status,
                    archive_error
                FROM resolved_issues_cache
                ORDER BY resolved_at DESC, id DESC
                """
            params: list[int] = []
            if limit is not None:
                sql += " LIMIT ?"
                params.append(max(0, int(limit)))
            rows = conn.execute(sql, params).fetchall()
        return [IssueRepository._resolved_from_row(row) for row in rows]

    def list_machine_active_history(self, machine_number: str) -> list[Issue]:
        return self.issue_repository.list_active_issues(machine_number, limit=None)

    def list_all_machine_activity(self) -> dict[str, list[IssueHistoryRecord]]:
        activity: dict[str, list[IssueHistoryRecord]] = {}
        for record in self.list_all_issue_history():
            activity.setdefault(record.machine_number, []).append(record)
        return activity

    def get_machine_activity_counts(self, machine_number: str, days: int) -> dict[str, int]:
        records = self.list_all_issue_history(machine_number)
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, int(days)))
        recent = [record for record in records if _record_time(record) is not None and _record_time(record) >= cutoff]
        return {
            "active": sum(1 for record in recent if record.is_active),
            "resolved": sum(1 for record in recent if not record.is_active),
            "line_down": sum(1 for record in recent if record.severity == "Line Down"),
            "non_critical": sum(1 for record in recent if record.severity == "Non-Critical"),
            "total": len(recent),
        }

    def get_category_counts(self, machine_number: str | None = None, days: int | None = None) -> dict[str, int]:
        return self._counts_by_field("category", machine_number=machine_number, days=days)

    def get_severity_counts(self, machine_number: str | None = None, days: int | None = None) -> dict[str, int]:
        return self._counts_by_field("severity", machine_number=machine_number, days=days)

    def get_line_down_counts(self, machine_number: str | None = None, days: int | None = None) -> int:
        records = self._filtered_records(machine_number=machine_number, days=days)
        return sum(1 for record in records if record.severity == "Line Down")

    def get_resolution_time_samples(self, machine_number: str | None = None) -> list[int]:
        resolved = (
            self.list_machine_resolved_history(machine_number, limit=None)
            if machine_number
            else self.list_all_resolved_history(limit=None)
        )
        samples: list[int] = []
        for issue in resolved:
            created = _parse_iso(issue.created_at)
            resolved_at = _parse_iso(issue.resolved_at)
            if created is None or resolved_at is None:
                continue
            samples.append(max(0, int((resolved_at - created).total_seconds() // 60)))
        return samples

    def get_all_machine_risk_inputs(self) -> list[MachineRiskInput]:
        inputs: list[MachineRiskInput] = []
        for machine in self.issue_repository.list_machines_with_status():
            inputs.append(
                MachineRiskInput(
                    machine_number=machine.machine_number,
                    machine_name=machine.name,
                    area=machine.area,
                    cell=machine.cell,
                    asset_tag=machine.asset_tag,
                    display_order=machine.display_order,
                    active_issues=tuple(self.issue_repository.list_active_issues(machine.machine_number, limit=None)),
                    resolved_issues=tuple(self.issue_repository.list_resolved_issues(machine.machine_number, limit=None)),
                )
            )
        return inputs

    def list_predictive_alerts(
        self,
        *,
        include_dismissed: bool = False,
        limit: int | None = 100,
    ) -> list[PredictiveMaintenanceAlert]:
        with connect(self.db_path) as conn:
            sql = """
                SELECT
                    id,
                    machine_number,
                    risk_level,
                    risk_score,
                    title,
                    message,
                    reasons_json,
                    suggested_action,
                    alert_type,
                    created_at
                FROM predictive_alerts
                WHERE (? = 1 OR dismissed_at = '')
                ORDER BY created_at DESC, id DESC
                """
            params: list[int] = [1 if include_dismissed else 0]
            if limit is not None:
                sql += " LIMIT ?"
                params.append(max(0, int(limit)))
            rows = conn.execute(sql, params).fetchall()
        return [self._alert_from_row(row) for row in rows]

    def persist_predictive_alert_if_new(self, alert: PredictiveMaintenanceAlert) -> PredictiveMaintenanceAlert:
        with connect(self.db_path) as conn:
            existing = conn.execute(
                """
                SELECT
                    id,
                    machine_number,
                    risk_level,
                    risk_score,
                    title,
                    message,
                    reasons_json,
                    suggested_action,
                    alert_type,
                    created_at
                FROM predictive_alerts
                WHERE machine_number = ?
                    AND alert_type = ?
                    AND title = ?
                    AND risk_level = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (alert.machine_number, alert.alert_type, alert.title, alert.risk_level),
            ).fetchone()
            if existing is not None:
                return self._alert_from_row(existing)

            cursor = conn.execute(
                """
                INSERT INTO predictive_alerts
                    (
                        machine_number,
                        risk_level,
                        risk_score,
                        title,
                        message,
                        reasons_json,
                        suggested_action,
                        alert_type,
                        created_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert.machine_number,
                    alert.risk_level,
                    int(alert.risk_score),
                    alert.title,
                    alert.message,
                    json.dumps(list(alert.reasons)),
                    alert.suggested_action,
                    alert.alert_type,
                    alert.created_at,
                ),
            )
            alert_id = int(cursor.lastrowid)
            row = conn.execute(
                """
                SELECT
                    id,
                    machine_number,
                    risk_level,
                    risk_score,
                    title,
                    message,
                    reasons_json,
                    suggested_action,
                    alert_type,
                    created_at
                FROM predictive_alerts
                WHERE id = ?
                """,
                (alert_id,),
            ).fetchone()
        return self._alert_from_row(row)

    def is_predictive_alert_dismissed(self, alert: PredictiveMaintenanceAlert) -> bool:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM predictive_alerts
                WHERE machine_number = ?
                    AND alert_type = ?
                    AND title = ?
                    AND risk_level = ?
                    AND dismissed_at <> ''
                LIMIT 1
                """,
                (alert.machine_number, alert.alert_type, alert.title, alert.risk_level),
            ).fetchone()
        return row is not None

    def dismiss_predictive_alert(self, alert_id: int, *, dismissed_by: str = "") -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE predictive_alerts
                SET dismissed_at = ?, dismissed_by = ?
                WHERE id = ?
                """,
                (utc_now_iso(), dismissed_by.strip(), int(alert_id)),
            )

    def _counts_by_field(self, field: str, *, machine_number: str | None, days: int | None) -> dict[str, int]:
        if field not in {"category", "severity"}:
            raise ValueError("Unsupported analytics count field.")
        counts: dict[str, int] = {}
        for record in self._filtered_records(machine_number=machine_number, days=days):
            key = getattr(record, field).strip() or "Uncategorized"
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold())))

    def _filtered_records(self, *, machine_number: str | None, days: int | None) -> list[IssueHistoryRecord]:
        records = self.list_all_issue_history(machine_number)
        if days is None:
            return records
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, int(days)))
        return [
            record
            for record in records
            if _record_time(record) is not None and _record_time(record) >= cutoff
        ]

    @staticmethod
    def _history_from_row(row) -> IssueHistoryRecord:
        return IssueHistoryRecord(
            issue_id=int(row["issue_id"]),
            original_issue_id=int(row["original_issue_id"]) if row["original_issue_id"] is not None else None,
            machine_number=row["machine_number"],
            machine_name=row["machine_name"],
            area=row["area"],
            cell=row["cell"],
            title=row["title"],
            description=row["description"],
            severity=row["severity"],
            category=row["category"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            resolved_at=row["resolved_at"],
            solution=row["solution"],
            is_active=bool(row["is_active"]),
        )

    @staticmethod
    def _alert_from_row(row) -> PredictiveMaintenanceAlert:
        try:
            reasons = tuple(str(reason) for reason in json.loads(row["reasons_json"]))
        except (TypeError, ValueError):
            reasons = ()
        return PredictiveMaintenanceAlert(
            machine_number=row["machine_number"],
            machine_name="",
            risk_level=row["risk_level"],
            risk_score=int(row["risk_score"]),
            title=row["title"],
            message=row["message"],
            reasons=reasons,
            suggested_action=row["suggested_action"],
            created_at=row["created_at"],
            alert_type=row["alert_type"],
            id=int(row["id"]),
        )


def build_trend_points_from_records(
    records: list[IssueHistoryRecord],
    *,
    now: datetime,
    bucket: str = "week",
    periods: int = 8,
) -> list[MachineTrendPoint]:
    now = _coerce_now(now)
    period_count = max(1, int(periods))
    delta = _bucket_delta(bucket)
    starts = [now - delta * index for index in range(period_count, 0, -1)]
    points: list[MachineTrendPoint] = []
    for start in starts:
        end = start + delta
        bucket_records = [record for record in records if _record_in_window(record, start, end)]
        resolved_records = [record for record in bucket_records if not record.is_active]
        durations = []
        for record in resolved_records:
            created = _parse_iso(record.created_at)
            resolved_at = _parse_iso(record.resolved_at or "")
            if created and resolved_at:
                durations.append(max(0, int((resolved_at - created).total_seconds() // 60)))
        points.append(
            MachineTrendPoint(
                period_label=_period_label(start, bucket),
                start_at=start.isoformat(),
                end_at=end.isoformat(),
                open_count=sum(1 for record in bucket_records if record.is_active),
                resolved_count=len(resolved_records),
                line_down_count=sum(1 for record in bucket_records if record.severity == "Line Down"),
                non_critical_count=sum(1 for record in bucket_records if record.severity == "Non-Critical"),
                average_time_open_minutes=int(sum(durations) / len(durations)) if durations else None,
            )
        )
    return points


def _record_in_window(record: IssueHistoryRecord, start: datetime, end: datetime) -> bool:
    timestamp = _record_time(record)
    return timestamp is not None and start <= timestamp < end


def _record_time(record: IssueHistoryRecord) -> datetime | None:
    return _parse_iso(record.resolved_at or record.created_at)


def _bucket_delta(bucket: str) -> timedelta:
    if bucket == "day":
        return timedelta(days=1)
    if bucket == "month":
        return timedelta(days=30)
    return timedelta(days=7)


def _period_label(start: datetime, bucket: str) -> str:
    if bucket == "day":
        return start.strftime("%m/%d")
    if bucket == "month":
        return start.strftime("%b %Y")
    return start.strftime("%m/%d")


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_now(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)
