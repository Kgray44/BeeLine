from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from beeline_issue_tracker.domain import (
    ACTIVE_SEVERITIES,
    Issue,
    Machine,
    MachineSummary,
    ResolvedIssue,
    status_from_counts,
)

from .database import connect


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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

    def list_active_issues(self, machine_number: str) -> list[Issue]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, machine_number, logged_by, title, description, severity, category, created_at, updated_at
                FROM active_issues
                WHERE machine_number = ?
                ORDER BY
                    CASE severity WHEN 'Line Down' THEN 0 ELSE 1 END,
                    created_at DESC
                """,
                (machine_number,),
            ).fetchall()
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

    def list_recent_resolved_issues(self, machine_number: str, limit: int | None = 8) -> list[ResolvedIssue]:
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
                ORDER BY resolved_at DESC
                """
            params: list[str | int] = [machine_number]
            if limit is not None:
                sql += " LIMIT ?"
                params.append(max(0, int(limit)))
            rows = conn.execute(sql, params).fetchall()
        return [self._resolved_from_row(row) for row in rows]

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
