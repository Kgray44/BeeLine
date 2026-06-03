from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from beeline_issue_tracker.domain import (
    ACTIVE_SEVERITIES,
    Issue,
    IssueAttachment,
    IssueEvent,
    IssueWithMachineContext,
    Machine,
    MachineResolvedStats,
    MachineSummary,
    ResolvedIssue,
    ResolvedIssueWithMachineContext,
    status_from_counts,
)

from .database import connect


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


ACTIVE_SORTS = {
    "date_desc": "created_at DESC, id DESC",
    "date_asc": "created_at ASC, id ASC",
    "title_asc": "LOWER(title) ASC, created_at DESC",
    "title_desc": "LOWER(title) DESC, created_at DESC",
}
RESOLVED_SORTS = {
    "date_desc": "resolved_at DESC, id DESC",
    "date_asc": "resolved_at ASC, id ASC",
    "title_asc": "LOWER(title) ASC, resolved_at DESC",
    "title_desc": "LOWER(title) DESC, resolved_at DESC",
}
GLOBAL_ACTIVE_SORTS = {
    "date_desc": "ai.created_at DESC, ai.id DESC",
    "date_asc": "ai.created_at ASC, ai.id ASC",
    "title_asc": "LOWER(ai.title) ASC, ai.created_at DESC",
    "title_desc": "LOWER(ai.title) DESC, ai.created_at DESC",
    "severity": "CASE ai.severity WHEN 'Line Down' THEN 0 WHEN 'Non-Critical' THEN 1 ELSE 2 END, ai.created_at DESC",
    "open_issues": "ai.created_at DESC, ai.id DESC",
}
ACTIVE_SEARCH_FIELDS = (
    "title",
    "description",
    "logged_by",
    "severity",
    "category",
    "machine_number",
)
RESOLVED_SEARCH_FIELDS = (
    "title",
    "description",
    "logged_by",
    "severity",
    "category",
    "machine_number",
    "solution",
    "resolved_by",
    "archive_status",
)
GLOBAL_ACTIVE_SEARCH_FIELDS = (
    "ai.title",
    "ai.description",
    "ai.logged_by",
    "ai.severity",
    "ai.category",
    "ai.machine_number",
    "m.name",
    "m.area",
    "m.cell",
)


class IssueRepository:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def list_machines_with_status(self) -> list[MachineSummary]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    m.machine_number,
                    m.name,
                    m.area,
                    m.cell,
                    m.asset_tag,
                    m.display_order,
                    COUNT(ai.id) AS open_issue_count,
                    SUM(CASE WHEN ai.severity = 'Line Down' THEN 1 ELSE 0 END) AS line_down_count,
                    SUM(CASE WHEN ai.severity = 'Non-Critical' THEN 1 ELSE 0 END) AS non_critical_count
                FROM machines m
                LEFT JOIN active_issues ai ON ai.machine_number = m.machine_number
                WHERE m.is_active = 1
                GROUP BY
                    m.machine_number,
                    m.name,
                    m.area,
                    m.cell,
                    m.asset_tag,
                    m.display_order
                ORDER BY m.display_order, m.machine_number
                """
            ).fetchall()

        summaries: list[MachineSummary] = []
        for row in rows:
            open_count = int(row["open_issue_count"] or 0)
            status = status_from_counts(
                int(row["line_down_count"] or 0),
                int(row["non_critical_count"] or 0),
                open_count,
            )
            summaries.append(
                MachineSummary(
                    machine_number=row["machine_number"],
                    name=row["name"],
                    area=row["area"],
                    cell=row["cell"],
                    asset_tag=row["asset_tag"],
                    display_order=int(row["display_order"]),
                    calculated_status=status,
                    open_issue_count=open_count,
                )
            )
        return summaries

    def get_machine(self, machine_number: str) -> Machine | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT machine_number, name, area, cell, asset_tag, display_order
                FROM machines
                WHERE machine_number = ? AND is_active = 1
                """,
                (machine_number,),
            ).fetchone()
        if row is None:
            return None
        return Machine(
            machine_number=row["machine_number"],
            name=row["name"],
            area=row["area"],
            cell=row["cell"],
            asset_tag=row["asset_tag"],
            display_order=int(row["display_order"]),
        )

    def get_machine_summary(self, machine_number: str) -> MachineSummary | None:
        return next(
            (machine for machine in self.list_machines_with_status() if machine.machine_number == machine_number),
            None,
        )

    def list_active_issues(
        self,
        machine_number: str,
        query: str = "",
        sort_key: str = "date_desc",
        limit: int | None = None,
    ) -> list[Issue]:
        with connect(self.db_path) as conn:
            sql = """
                SELECT id, machine_number, logged_by, title, description, severity, category, created_at, updated_at
                FROM active_issues
                WHERE machine_number = ?
                """
            params: list[str | int] = [machine_number]
            search_sql, search_params = _search_clause(ACTIVE_SEARCH_FIELDS, query)
            sql += search_sql
            params.extend(search_params)
            sql += f" ORDER BY {ACTIVE_SORTS.get(sort_key, ACTIVE_SORTS['date_desc'])}"
            if limit is not None:
                sql += " LIMIT ?"
                params.append(max(0, int(limit)))
            rows = conn.execute(sql, params).fetchall()
        return [self._issue_from_row(row) for row in rows]

    def get_active_issue(self, issue_id: int) -> Issue | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, machine_number, logged_by, title, description, severity, category, created_at, updated_at
                FROM active_issues
                WHERE id = ?
                """,
                (issue_id,),
            ).fetchone()
        return self._issue_from_row(row) if row else None

    def get_issue_with_machine_context(self, issue_id: int) -> IssueWithMachineContext | None:
        issue = self.get_active_issue(issue_id)
        if issue is None:
            return None
        return IssueWithMachineContext(issue=issue, machine=self.get_machine_summary(issue.machine_number))

    def list_resolved_issues(
        self,
        machine_number: str,
        query: str = "",
        sort_key: str = "date_desc",
        limit: int | None = 10,
    ) -> list[ResolvedIssue]:
        with connect(self.db_path) as conn:
            sql = """
                SELECT
                    id,
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
                WHERE machine_number = ?
                """
            params: list[str | int] = [machine_number]
            search_sql, search_params = _search_clause(RESOLVED_SEARCH_FIELDS, query)
            sql += search_sql
            params.extend(search_params)
            sql += f" ORDER BY {RESOLVED_SORTS.get(sort_key, RESOLVED_SORTS['date_desc'])}"
            if limit is not None:
                sql += " LIMIT ?"
                params.append(max(0, int(limit)))
            rows = conn.execute(sql, params).fetchall()
        return [self._resolved_from_row(row) for row in rows]

    def list_recent_resolved_issues(self, machine_number: str, limit: int | None = 8) -> list[ResolvedIssue]:
        return self.list_resolved_issues(machine_number, limit=limit)

    def get_resolved_issue(self, resolved_issue_id: int) -> ResolvedIssue | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    id,
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
                WHERE id = ?
                """,
                (resolved_issue_id,),
            ).fetchone()
        return self._resolved_from_row(row) if row else None

    def get_resolved_issue_with_machine_context(
        self,
        resolved_issue_id: int,
    ) -> ResolvedIssueWithMachineContext | None:
        issue = self.get_resolved_issue(resolved_issue_id)
        if issue is None:
            return None
        return ResolvedIssueWithMachineContext(issue=issue, machine=self.get_machine_summary(issue.machine_number))

    def find_related_resolved_issues(self, issue: Issue, limit: int = 5) -> list[ResolvedIssue]:
        keywords = _keywords(issue.title)
        candidates = self.list_resolved_issues(issue.machine_number, limit=None)
        scored: list[tuple[int, ResolvedIssue]] = []
        for candidate in candidates:
            score = 0
            if issue.category and candidate.category == issue.category:
                score += 3
            candidate_keywords = _keywords(candidate.title)
            score += len(keywords & candidate_keywords)
            if score:
                scored.append((score, candidate))
        scored.sort(key=lambda item: (item[0], _timestamp_score(item[1].resolved_at)), reverse=True)
        return [candidate for _score, candidate in scored[: max(0, int(limit))]]

    def get_machine_issue_trend_summary(self, machine_number: str) -> dict[str, int]:
        with connect(self.db_path) as conn:
            active_count = conn.execute(
                "SELECT COUNT(*) FROM active_issues WHERE machine_number = ?",
                (machine_number,),
            ).fetchone()[0]
            resolved_count = conn.execute(
                "SELECT COUNT(*) FROM resolved_issues_cache WHERE machine_number = ?",
                (machine_number,),
            ).fetchone()[0]
            line_down_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM active_issues
                WHERE machine_number = ? AND severity = 'Line Down'
                """,
                (machine_number,),
            ).fetchone()[0]
        return {
            "active": int(active_count),
            "resolved": int(resolved_count),
            "line_down_active": int(line_down_count),
        }

    def list_all_active_issues(
        self,
        query: str = "",
        severity: str | None = None,
        machine_number: str | None = None,
        area: str | None = None,
        cell: str | None = None,
        sort_key: str = "date_desc",
        limit: int | None = 50,
    ) -> list[Issue]:
        with connect(self.db_path) as conn:
            sql = """
                SELECT
                    ai.id,
                    ai.machine_number,
                    ai.logged_by,
                    ai.title,
                    ai.description,
                    ai.severity,
                    ai.category,
                    ai.created_at,
                    ai.updated_at
                FROM active_issues ai
                INNER JOIN machines m ON m.machine_number = ai.machine_number
                WHERE m.is_active = 1
                """
            params: list[str | int] = []
            if severity:
                sql += " AND ai.severity = ?"
                params.append(severity)
            if machine_number:
                sql += " AND ai.machine_number = ?"
                params.append(machine_number)
            if area:
                sql += " AND m.area = ?"
                params.append(area)
            if cell:
                sql += " AND m.cell = ?"
                params.append(cell)
            search_sql, search_params = _search_clause(GLOBAL_ACTIVE_SEARCH_FIELDS, query)
            sql += search_sql
            params.extend(search_params)
            sql += f" ORDER BY {GLOBAL_ACTIVE_SORTS.get(sort_key, GLOBAL_ACTIVE_SORTS['date_desc'])}"
            if limit is not None:
                sql += " LIMIT ?"
                params.append(max(0, int(limit)))
            rows = conn.execute(sql, params).fetchall()
        return [self._issue_from_row(row) for row in rows]

    def get_latest_resolved_issue(self) -> ResolvedIssue | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    id,
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
                ORDER BY resolved_at DESC
                LIMIT 1
                """
            ).fetchone()
        return self._resolved_from_row(row) if row else None

    def archive_status_counts(self) -> dict[str, int]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT archive_status, COUNT(*) AS status_count
                FROM resolved_issues_cache
                GROUP BY archive_status
                ORDER BY archive_status
                """
            ).fetchall()
        return {row["archive_status"]: int(row["status_count"]) for row in rows}

    def log_issue(
        self,
        *,
        machine_number: str,
        logged_by: str,
        title: str,
        description: str,
        severity: str,
        category: str = "",
    ) -> Issue:
        machine_number = machine_number.strip()
        logged_by = logged_by.strip()
        title = title.strip()
        description = description.strip()
        severity = severity.strip()
        category = category.strip()

        if not logged_by:
            raise ValueError("Logged by is required.")
        if not title:
            raise ValueError("Issue title is required.")
        if not description:
            raise ValueError("Problem description is required.")
        if severity not in ACTIVE_SEVERITIES:
            raise ValueError("Status must be Line Down or Non-Critical.")

        now = utc_now_iso()
        with connect(self.db_path) as conn:
            machine_exists = conn.execute(
                "SELECT 1 FROM machines WHERE machine_number = ? AND is_active = 1",
                (machine_number,),
            ).fetchone()
            if machine_exists is None:
                raise ValueError(f"Machine {machine_number} was not found.")
            cursor = conn.execute(
                """
                INSERT INTO active_issues
                    (machine_number, logged_by, title, description, severity, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (machine_number, logged_by, title, description, severity, category, now, now),
            )
            issue_id = int(cursor.lastrowid)
            self._insert_event(
                conn,
                issue_id=issue_id,
                original_issue_id=issue_id,
                machine_number=machine_number,
                event_type="issue_created",
                actor=logged_by,
                details={
                    "title": title,
                    "severity": severity,
                    "category": category,
                },
            )
        issue = self.get_active_issue(issue_id)
        if issue is None:
            raise RuntimeError("Issue was saved but could not be reloaded.")
        return issue

    def resolve_issue(self, issue_id: int, *, solution: str, resolved_by: str = "") -> ResolvedIssue:
        solution = solution.strip()
        resolved_by = resolved_by.strip()

        if not solution:
            raise ValueError("Solution/fix text is required.")

        resolved_at = utc_now_iso()
        with connect(self.db_path) as conn:
            issue = conn.execute(
                """
                SELECT id, machine_number, logged_by, title, description, severity, category, created_at, updated_at
                FROM active_issues
                WHERE id = ?
                """,
                (issue_id,),
            ).fetchone()
            if issue is None:
                raise ValueError("The issue is no longer active.")

            cursor = conn.execute(
                """
                INSERT INTO resolved_issues_cache
                    (
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
                        archive_status
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    int(issue["id"]),
                    issue["machine_number"],
                    issue["logged_by"],
                    issue["title"],
                    issue["description"],
                    issue["severity"],
                    issue["category"],
                    issue["created_at"],
                    resolved_at,
                    resolved_by,
                    solution,
                ),
            )
            cache_id = int(cursor.lastrowid)
            self._insert_event(
                conn,
                issue_id=cache_id,
                original_issue_id=int(issue["id"]),
                machine_number=issue["machine_number"],
                event_type="issue_resolved",
                actor=resolved_by,
                details={
                    "solution": solution,
                    "title": issue["title"],
                    "severity": issue["severity"],
                    "category": issue["category"],
                },
            )
            conn.execute("DELETE FROM active_issues WHERE id = ?", (issue_id,))

            resolved = conn.execute(
                """
                SELECT
                    id,
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
                WHERE id = ?
                """,
                (cache_id,),
            ).fetchone()

        if resolved is None:
            raise RuntimeError("Resolved issue was saved but could not be reloaded.")
        return self._resolved_from_row(resolved)

    def mark_archive_result(self, resolved_issue_id: int, *, success: bool, error: str = "") -> None:
        archive_status = "archived" if success else "archive_error"
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE resolved_issues_cache
                SET archive_status = ?, archive_error = ?
                WHERE id = ?
                """,
                (archive_status, error[:500], resolved_issue_id),
            )
            resolved = conn.execute(
                """
                SELECT id, original_issue_id, machine_number
                FROM resolved_issues_cache
                WHERE id = ?
                """,
                (resolved_issue_id,),
            ).fetchone()
            if resolved is not None:
                self._insert_event(
                    conn,
                    issue_id=int(resolved["id"]),
                    original_issue_id=int(resolved["original_issue_id"]),
                    machine_number=resolved["machine_number"],
                    event_type="archive_success" if success else "archive_failure",
                    actor="BeeLine Archive Worker",
                    details={
                        "archive_status": archive_status,
                        "error": error[:500],
                    },
                )

    def list_issue_events(self, machine_number: str | None = None, limit: int = 100) -> list[IssueEvent]:
        with connect(self.db_path) as conn:
            sql = """
                SELECT id, issue_id, original_issue_id, machine_number, event_type, actor, created_at, details_json
                FROM issue_events
                """
            params: list[str | int] = []
            if machine_number:
                sql += " WHERE machine_number = ?"
                params.append(machine_number)
            sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
            params.append(max(0, int(limit)))
            rows = conn.execute(sql, params).fetchall()
        return [self._event_from_row(row) for row in rows]

    def list_events_for_issue(self, issue_identifier: int) -> list[IssueEvent]:
        """Return events matching either active original ID or resolved cache ID."""
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, issue_id, original_issue_id, machine_number, event_type, actor, created_at, details_json
                FROM issue_events
                WHERE issue_id = ? OR original_issue_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (issue_identifier, issue_identifier),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def list_attachments_for_issue(
        self,
        *,
        issue_id: int | None = None,
        resolved_issue_id: int | None = None,
    ) -> list[IssueAttachment]:
        if issue_id is None and resolved_issue_id is None:
            return []
        with connect(self.db_path) as conn:
            clauses = []
            params: list[int] = []
            if issue_id is not None:
                clauses.append("issue_id = ?")
                params.append(issue_id)
            if resolved_issue_id is not None:
                clauses.append("resolved_issue_id = ?")
                params.append(resolved_issue_id)
            rows = conn.execute(
                f"""
                SELECT
                    id,
                    issue_id,
                    resolved_issue_id,
                    machine_number,
                    file_path,
                    original_filename,
                    note,
                    created_at,
                    created_by
                FROM issue_attachments
                WHERE {' OR '.join(clauses)}
                ORDER BY created_at DESC, id DESC
                """,
                params,
            ).fetchall()
        return [self._attachment_from_row(row) for row in rows]

    def add_issue_attachment(
        self,
        *,
        machine_number: str,
        file_path: str,
        original_filename: str,
        issue_id: int | None = None,
        resolved_issue_id: int | None = None,
        note: str = "",
        created_by: str = "",
    ) -> IssueAttachment:
        if issue_id is None and resolved_issue_id is None:
            raise ValueError("Attachment must belong to an active or resolved issue.")
        now = utc_now_iso()
        with connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO issue_attachments
                    (
                        issue_id,
                        resolved_issue_id,
                        machine_number,
                        file_path,
                        original_filename,
                        note,
                        created_at,
                        created_by
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    issue_id,
                    resolved_issue_id,
                    machine_number.strip(),
                    file_path.strip(),
                    original_filename.strip(),
                    note.strip(),
                    now,
                    created_by.strip(),
                ),
            )
            row = conn.execute(
                """
                SELECT
                    id,
                    issue_id,
                    resolved_issue_id,
                    machine_number,
                    file_path,
                    original_filename,
                    note,
                    created_at,
                    created_by
                FROM issue_attachments
                WHERE id = ?
                """,
                (int(cursor.lastrowid),),
            ).fetchone()
        if row is None:
            raise RuntimeError("Attachment was saved but could not be reloaded.")
        return self._attachment_from_row(row)

    def get_machine_resolved_stats(self, machine_number: str) -> MachineResolvedStats:
        resolved = self.list_resolved_issues(machine_number, sort_key="date_desc", limit=None)
        if not resolved:
            return MachineResolvedStats(
                machine_number=machine_number,
                total_resolved=0,
                most_common_category="",
                most_common_title="",
                last_resolved_title="",
                last_resolved_at="",
                average_time_open_seconds=None,
                recurring_warning="",
            )

        category_counts = Counter(issue.category.strip() for issue in resolved if issue.category.strip())
        title_labels: dict[str, str] = {}
        title_counts: Counter[str] = Counter()
        durations: list[int] = []
        for issue in resolved:
            normalized_title = _normalize_title(issue.title)
            if normalized_title:
                title_counts[normalized_title] += 1
                title_labels.setdefault(normalized_title, issue.title)
            created = _parse_iso(issue.created_at)
            resolved_at = _parse_iso(issue.resolved_at)
            if created and resolved_at:
                durations.append(max(0, int((resolved_at - created).total_seconds())))

        most_common_category = category_counts.most_common(1)[0][0] if category_counts else ""
        most_common_title_key = title_counts.most_common(1)[0][0] if title_counts else ""
        most_common_title = title_labels.get(most_common_title_key, "")
        recurring_warning = ""
        if most_common_title_key and title_counts[most_common_title_key] >= 2:
            recurring_warning = f"{most_common_title} repeated {title_counts[most_common_title_key]} times"
        elif most_common_category and category_counts[most_common_category] >= 2:
            recurring_warning = f"{most_common_category} repeated {category_counts[most_common_category]} times"

        average_seconds = int(sum(durations) / len(durations)) if durations else None
        latest = resolved[0]
        return MachineResolvedStats(
            machine_number=machine_number,
            total_resolved=len(resolved),
            most_common_category=most_common_category,
            most_common_title=most_common_title,
            last_resolved_title=latest.title,
            last_resolved_at=latest.resolved_at,
            average_time_open_seconds=average_seconds,
            recurring_warning=recurring_warning,
        )

    @staticmethod
    def _insert_event(
        conn,
        *,
        issue_id: int | None,
        original_issue_id: int | None,
        machine_number: str,
        event_type: str,
        actor: str,
        details: dict[str, object],
    ) -> None:
        conn.execute(
            """
            INSERT INTO issue_events
                (issue_id, original_issue_id, machine_number, event_type, actor, created_at, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issue_id,
                original_issue_id,
                machine_number,
                event_type,
                actor,
                utc_now_iso(),
                json.dumps(details, sort_keys=True),
            ),
        )

    @staticmethod
    def _issue_from_row(row) -> Issue:
        return Issue(
            id=int(row["id"]),
            machine_number=row["machine_number"],
            logged_by=row["logged_by"],
            title=row["title"],
            description=row["description"],
            severity=row["severity"],
            category=row["category"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _resolved_from_row(row) -> ResolvedIssue:
        return ResolvedIssue(
            id=int(row["id"]),
            original_issue_id=int(row["original_issue_id"]),
            machine_number=row["machine_number"],
            logged_by=row["logged_by"],
            title=row["title"],
            description=row["description"],
            severity=row["severity"],
            category=row["category"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
            resolved_by=row["resolved_by"],
            solution=row["solution"],
            archive_status=row["archive_status"],
            archive_error=row["archive_error"],
        )

    @staticmethod
    def _event_from_row(row) -> IssueEvent:
        return IssueEvent(
            id=int(row["id"]),
            issue_id=int(row["issue_id"]) if row["issue_id"] is not None else None,
            original_issue_id=int(row["original_issue_id"]) if row["original_issue_id"] is not None else None,
            machine_number=row["machine_number"],
            event_type=row["event_type"],
            actor=row["actor"],
            created_at=row["created_at"],
            details_json=row["details_json"],
        )

    @staticmethod
    def _attachment_from_row(row) -> IssueAttachment:
        return IssueAttachment(
            id=int(row["id"]),
            issue_id=int(row["issue_id"]) if row["issue_id"] is not None else None,
            resolved_issue_id=int(row["resolved_issue_id"]) if row["resolved_issue_id"] is not None else None,
            machine_number=row["machine_number"],
            file_path=row["file_path"],
            original_filename=row["original_filename"],
            note=row["note"],
            created_at=row["created_at"],
            created_by=row["created_by"],
        )


def _search_clause(fields: tuple[str, ...], query: str) -> tuple[str, list[str]]:
    terms = [term for term in " ".join(query.casefold().split()).split(" ") if term]
    if not terms:
        return "", []
    clauses = []
    params: list[str] = []
    for term in terms:
        clauses.append("(" + " OR ".join(f"LOWER({field}) LIKE ?" for field in fields) + ")")
        params.extend([f"%{term}%"] * len(fields))
    return " AND " + " AND ".join(clauses), params


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def _normalize_title(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.casefold())
    stop_words = {"the", "a", "an", "and", "or", "to", "is", "at", "on", "of", "for"}
    return " ".join(word for word in words if word not in stop_words)


def _keywords(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", value.casefold()) if len(word) >= 4}


def _timestamp_score(value: str) -> float:
    parsed = _parse_iso(value)
    return parsed.timestamp() if parsed else 0.0
