from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from beeline_issue_tracker.future_features import (
    DataHealthSummary,
    IntakeSuggestion,
    KnownFix,
    MachineOpenCluster,
    PriorityIssue,
    ShiftHandoffSummary,
    issue_age,
    normalized_pattern_key,
    preview,
    priority_label,
)
from beeline_issue_tracker.domain import (
    ACTIVE_SEVERITIES,
    Issue,
    IssueAttachment,
    IssueEvent,
    IssueSearchResult,
    IssueWithMachineContext,
    Machine,
    MachineResolvedStats,
    MachineSummary,
    ResolvedIssue,
    ResolvedIssueWithMachineContext,
    display_issue_id,
    generate_issue_id,
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
    "issue_id_asc": "COALESCE(NULLIF(issue_id, ''), printf('%012d', id)) ASC",
    "issue_id_desc": "COALESCE(NULLIF(issue_id, ''), printf('%012d', id)) DESC",
}
RESOLVED_SORTS = {
    "date_desc": "resolved_at DESC, id DESC",
    "date_asc": "resolved_at ASC, id ASC",
    "title_asc": "LOWER(title) ASC, resolved_at DESC",
    "title_desc": "LOWER(title) DESC, resolved_at DESC",
    "issue_id_asc": "COALESCE(NULLIF(issue_id, ''), printf('%012d', original_issue_id)) ASC",
    "issue_id_desc": "COALESCE(NULLIF(issue_id, ''), printf('%012d', original_issue_id)) DESC",
}
GLOBAL_ACTIVE_SORTS = {
    "date_desc": "ai.created_at DESC, ai.id DESC",
    "date_asc": "ai.created_at ASC, ai.id ASC",
    "title_asc": "LOWER(ai.title) ASC, ai.created_at DESC",
    "title_desc": "LOWER(ai.title) DESC, ai.created_at DESC",
    "issue_id_asc": "COALESCE(NULLIF(ai.issue_id, ''), printf('%012d', ai.id)) ASC",
    "issue_id_desc": "COALESCE(NULLIF(ai.issue_id, ''), printf('%012d', ai.id)) DESC",
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
    "COALESCE(NULLIF(issue_id, ''), CAST(id AS TEXT))",
)
ISSUE_SEARCH_STATES = {"all", "open", "resolved"}
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
    "COALESCE(NULLIF(issue_id, ''), CAST(original_issue_id AS TEXT))",
)
GLOBAL_ACTIVE_SEARCH_FIELDS = (
    "ai.title",
    "ai.description",
    "ai.logged_by",
    "ai.severity",
    "ai.category",
    "ai.machine_number",
    "COALESCE(NULLIF(ai.issue_id, ''), CAST(ai.id AS TEXT))",
    "m.name",
    "m.area",
    "m.cell",
)
GLOBAL_RESOLVED_SEARCH_FIELDS = (
    "ri.title",
    "ri.description",
    "ri.logged_by",
    "ri.severity",
    "ri.category",
    "ri.machine_number",
    "ri.solution",
    "ri.resolved_by",
    "ri.archive_status",
    "COALESCE(NULLIF(ri.issue_id, ''), CAST(ri.original_issue_id AS TEXT))",
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
                    m.manufacturer,
                    m.model,
                    m.imm_serial,
                    m.robot_type,
                    m.robot_model,
                    m.robot_serial,
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
                    m.display_order,
                    m.manufacturer,
                    m.model,
                    m.imm_serial,
                    m.robot_type,
                    m.robot_model,
                    m.robot_serial
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
                    manufacturer=row["manufacturer"],
                    model=row["model"],
                    imm_serial=row["imm_serial"],
                    robot_type=row["robot_type"],
                    robot_model=row["robot_model"],
                    robot_serial=row["robot_serial"],
                    calculated_status=status,
                    open_issue_count=open_count,
                )
            )
        return summaries

    def get_machine(self, machine_number: str) -> Machine | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    machine_number,
                    name,
                    area,
                    cell,
                    asset_tag,
                    display_order,
                    manufacturer,
                    model,
                    imm_serial,
                    robot_type,
                    robot_model,
                    robot_serial
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
            manufacturer=row["manufacturer"],
            model=row["model"],
            imm_serial=row["imm_serial"],
            robot_type=row["robot_type"],
            robot_model=row["robot_model"],
            robot_serial=row["robot_serial"],
        )

    def get_machine_summary(self, machine_number: str) -> MachineSummary | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    m.machine_number,
                    m.name,
                    m.area,
                    m.cell,
                    m.asset_tag,
                    m.display_order,
                    m.manufacturer,
                    m.model,
                    m.imm_serial,
                    m.robot_type,
                    m.robot_model,
                    m.robot_serial,
                    COUNT(ai.id) AS open_issue_count,
                    SUM(CASE WHEN ai.severity = 'Line Down' THEN 1 ELSE 0 END) AS line_down_count,
                    SUM(CASE WHEN ai.severity = 'Non-Critical' THEN 1 ELSE 0 END) AS non_critical_count
                FROM machines m
                LEFT JOIN active_issues ai
                    ON ai.machine_number = m.machine_number
                WHERE m.machine_number = ?
                    AND m.is_active = 1
                GROUP BY
                    m.machine_number,
                    m.name,
                    m.area,
                    m.cell,
                    m.asset_tag,
                    m.display_order,
                    m.manufacturer,
                    m.model,
                    m.imm_serial,
                    m.robot_type,
                    m.robot_model,
                    m.robot_serial
                """,
                (machine_number,),
            ).fetchone()
        if row is None:
            return None
        open_count = int(row["open_issue_count"] or 0)
        status = status_from_counts(
            int(row["line_down_count"] or 0),
            int(row["non_critical_count"] or 0),
            open_count,
        )
        return MachineSummary(
            machine_number=row["machine_number"],
            name=row["name"],
            area=row["area"],
            cell=row["cell"],
            asset_tag=row["asset_tag"],
            display_order=int(row["display_order"]),
            manufacturer=row["manufacturer"],
            model=row["model"],
            imm_serial=row["imm_serial"],
            robot_type=row["robot_type"],
            robot_model=row["robot_model"],
            robot_serial=row["robot_serial"],
            calculated_status=status,
            open_issue_count=open_count,
        )

    def list_active_issues(
        self,
        machine_number: str,
        query: str = "",
        sort_key: str = "date_desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Issue]:
        with connect(self.db_path) as conn:
            sql = """
                SELECT
                    id,
                    issue_id AS public_issue_id,
                    machine_number,
                    logged_by,
                    title,
                    description,
                    severity,
                    category,
                    what_changed,
                    tried_already,
                    created_at,
                    updated_at
                FROM active_issues
                WHERE machine_number = ?
                """
            params: list[str | int] = [machine_number]
            search_sql, search_params = _search_clause(ACTIVE_SEARCH_FIELDS, query)
            sql += search_sql
            params.extend(search_params)
            sql += f" ORDER BY {ACTIVE_SORTS.get(sort_key, ACTIVE_SORTS['date_desc'])}"
            if limit is not None:
                sql += " LIMIT ? OFFSET ?"
                params.append(max(0, int(limit)))
                params.append(max(0, int(offset)))
            rows = conn.execute(sql, params).fetchall()
        return [self._issue_from_row(row) for row in rows]

    def get_active_issue(self, issue_id: int) -> Issue | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    id,
                    issue_id AS public_issue_id,
                    machine_number,
                    logged_by,
                    title,
                    description,
                    severity,
                    category,
                    what_changed,
                    tried_already,
                    created_at,
                    updated_at
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
        offset: int = 0,
    ) -> list[ResolvedIssue]:
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
                    what_changed,
                    tried_already,
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
                sql += " LIMIT ? OFFSET ?"
                params.append(max(0, int(limit)))
                params.append(max(0, int(offset)))
            rows = conn.execute(sql, params).fetchall()
        return [self._resolved_from_row(row) for row in rows]

    def list_recent_resolved_issues(
        self,
        machine_number: str,
        limit: int | None = 50,
        *,
        allow_unlimited: bool = False,
    ) -> list[ResolvedIssue]:
        if limit is None and not allow_unlimited:
            limit = 50
        return self.list_resolved_issues(machine_number, limit=limit)

    def count_active_issues_matching(self, machine_number: str, query: str = "") -> int:
        return self._count_machine_issues(
            "active_issues",
            machine_number,
            ACTIVE_SEARCH_FIELDS,
            query,
        )

    def count_resolved_issues_matching(self, machine_number: str, query: str = "") -> int:
        return self._count_machine_issues(
            "resolved_issues_cache",
            machine_number,
            RESOLVED_SEARCH_FIELDS,
            query,
        )

    def count_total_active_issues(self, machine_number: str) -> int:
        return self.count_active_issues_matching(machine_number)

    def count_total_resolved_issues(self, machine_number: str) -> int:
        return self.count_resolved_issues_matching(machine_number)

    def _count_machine_issues(
        self,
        table: str,
        machine_number: str,
        fields: tuple[str, ...],
        query: str = "",
    ) -> int:
        with connect(self.db_path) as conn:
            sql = f"SELECT COUNT(*) FROM {table} WHERE machine_number = ?"
            params: list[str] = [machine_number]
            search_sql, search_params = _search_clause(fields, query)
            sql += search_sql
            params.extend(search_params)
            return int(conn.execute(sql, params).fetchone()[0])

    def get_resolved_issue(self, resolved_issue_id: int) -> ResolvedIssue | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
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
                    what_changed,
                    tried_already,
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
        candidates = self.list_resolved_issues(issue.machine_number, limit=250)
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

    def search_issues(
        self,
        query: str = "",
        *,
        state_filter: str = "all",
        limit: int | None = 100,
        machine_number: str | None = None,
    ) -> list[IssueSearchResult]:
        normalized_state = state_filter if state_filter in ISSUE_SEARCH_STATES else "all"
        result_limit = None if limit is None else max(0, int(limit))
        rows: list[IssueSearchResult] = []
        with connect(self.db_path) as conn:
            if normalized_state in {"all", "open"}:
                sql = """
                    SELECT
                        'open' AS state,
                        'Open Issue' AS source,
                        ai.id AS issue_id,
                        COALESCE(NULLIF(ai.issue_id, ''), CAST(ai.id AS TEXT)) AS public_issue_id,
                        ai.machine_number,
                        m.name AS machine_name,
                        COALESCE(NULLIF(m.model, ''), m.name) AS machine_model,
                        ai.title,
                        ai.description,
                        ai.severity AS status,
                        ai.category,
                        ai.logged_by,
                        ai.created_at,
                        ai.updated_at,
                        '' AS resolved_at,
                        '' AS resolved_by,
                        '' AS resolution,
                        '' AS history_text
                    FROM active_issues ai
                    INNER JOIN machines m ON m.machine_number = ai.machine_number
                    WHERE m.is_active = 1
                    """
                params: list[str | int] = []
                if machine_number:
                    sql += " AND ai.machine_number = ?"
                    params.append(machine_number)
                search_sql, search_params = _search_clause(GLOBAL_ACTIVE_SEARCH_FIELDS, query)
                sql += search_sql
                params.extend(search_params)
                sql += " ORDER BY ai.created_at DESC, ai.id DESC"
                if result_limit is not None:
                    sql += " LIMIT ?"
                    params.append(result_limit)
                active_rows = conn.execute(sql, params).fetchall()
                rows.extend(self._issue_search_result_from_row(row) for row in active_rows)

            if normalized_state in {"all", "resolved"}:
                sql = """
                    SELECT
                        'resolved' AS state,
                        'Recent Archive' AS source,
                        ri.id AS issue_id,
                        COALESCE(NULLIF(ri.issue_id, ''), CAST(ri.original_issue_id AS TEXT)) AS public_issue_id,
                        ri.machine_number,
                        m.name AS machine_name,
                        COALESCE(NULLIF(m.model, ''), m.name) AS machine_model,
                        ri.title,
                        ri.description,
                        ri.severity AS status,
                        ri.category,
                        ri.logged_by,
                        ri.created_at,
                        ri.resolved_at AS updated_at,
                        ri.resolved_at,
                        ri.resolved_by,
                        ri.solution AS resolution,
                        '' AS history_text
                    FROM resolved_issues_cache ri
                    INNER JOIN machines m ON m.machine_number = ri.machine_number
                    WHERE m.is_active = 1
                    """
                params = []
                if machine_number:
                    sql += " AND ri.machine_number = ?"
                    params.append(machine_number)
                search_sql, search_params = _search_clause(GLOBAL_RESOLVED_SEARCH_FIELDS, query)
                sql += search_sql
                params.extend(search_params)
                sql += " ORDER BY ri.resolved_at DESC, ri.id DESC"
                if result_limit is not None:
                    sql += " LIMIT ?"
                    params.append(result_limit)
                resolved_rows = conn.execute(sql, params).fetchall()
                rows.extend(self._issue_search_result_from_row(row) for row in resolved_rows)

        rows.sort(
            key=lambda row: (
                _timestamp_score(row.resolved_at or row.updated_at or row.created_at),
                1 if row.state == "open" else 0,
            ),
            reverse=True,
        )
        if result_limit is None:
            return rows
        return rows[:result_limit]

    def list_all_active_issues(
        self,
        query: str = "",
        severity: str | None = None,
        machine_number: str | None = None,
        area: str | None = None,
        cell: str | None = None,
        sort_key: str = "date_desc",
        limit: int | None = 50,
        offset: int = 0,
    ) -> list[Issue]:
        with connect(self.db_path) as conn:
            sql = """
                SELECT
                    ai.id,
                    ai.issue_id AS public_issue_id,
                    ai.machine_number,
                    ai.logged_by,
                    ai.title,
                    ai.description,
                    ai.severity,
                    ai.category,
                    ai.what_changed,
                    ai.tried_already,
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
                sql += " LIMIT ? OFFSET ?"
                params.append(max(0, int(limit)))
                params.append(max(0, int(offset)))
            rows = conn.execute(sql, params).fetchall()
        return [self._issue_from_row(row) for row in rows]

    def list_priority_issues(self, limit: int = 50) -> list[PriorityIssue]:
        started_limit = min(50, max(1, int(limit)))
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    ai.id,
                    ai.issue_id AS public_issue_id,
                    ai.machine_number,
                    ai.logged_by,
                    ai.title,
                    ai.description,
                    ai.severity,
                    ai.category,
                    ai.what_changed,
                    ai.tried_already,
                    ai.created_at,
                    ai.updated_at,
                    m.name AS machine_name,
                    m.area,
                    m.cell,
                    COALESCE(open_counts.open_count, 0) AS machine_open_count,
                    COALESCE(category_counts.category_open_count, 0) AS category_open_count
                FROM active_issues ai
                INNER JOIN machines m ON m.machine_number = ai.machine_number
                LEFT JOIN (
                    SELECT machine_number, COUNT(*) AS open_count
                    FROM active_issues
                    GROUP BY machine_number
                ) open_counts ON open_counts.machine_number = ai.machine_number
                LEFT JOIN (
                    SELECT machine_number, LOWER(TRIM(category)) AS category_key, COUNT(*) AS category_open_count
                    FROM active_issues
                    WHERE TRIM(category) <> ''
                    GROUP BY machine_number, LOWER(TRIM(category))
                ) category_counts
                    ON category_counts.machine_number = ai.machine_number
                    AND category_counts.category_key = LOWER(TRIM(ai.category))
                WHERE m.is_active = 1
                ORDER BY
                    CASE ai.severity WHEN 'Line Down' THEN 0 ELSE 1 END,
                    datetime(ai.created_at) ASC,
                    COALESCE(open_counts.open_count, 0) DESC,
                    COALESCE(category_counts.category_open_count, 0) DESC,
                    datetime(ai.updated_at) ASC,
                    ai.id ASC
                LIMIT ?
                """,
                (started_limit,),
            ).fetchall()

        priority_rows: list[PriorityIssue] = []
        for row in rows:
            issue = self._issue_from_row(row)
            age = issue_age(issue)
            machine_open_count = int(row["machine_open_count"] or 0)
            category_open_count = int(row["category_open_count"] or 0)
            priority_rows.append(
                PriorityIssue(
                    issue=issue,
                    machine_name=row["machine_name"],
                    area=row["area"],
                    cell=row["cell"],
                    machine_open_count=machine_open_count,
                    category_open_count=category_open_count,
                    priority=priority_label(issue, machine_open_count, category_open_count, age),
                    age=age,
                )
            )
        return priority_rows

    def list_known_fixes(self, machine_number: str, limit: int = 10) -> list[KnownFix]:
        history = self.list_resolved_issues(machine_number, limit=250)
        grouped: dict[str, list[ResolvedIssue]] = defaultdict(list)
        for issue in history:
            key = normalized_pattern_key(issue.title, issue.category)
            if key:
                grouped[key].append(issue)

        fixes: list[KnownFix] = []
        for issues in grouped.values():
            issues.sort(key=lambda item: _timestamp_score(item.resolved_at), reverse=True)
            latest = issues[0]
            solutions = Counter(preview(issue.solution, 140) for issue in issues if issue.solution.strip())
            common_solution = solutions.most_common(1)[0][0] if solutions else "-"
            fixes.append(
                KnownFix(
                    pattern=preview(latest.title, 90),
                    category=latest.category or "Uncategorized",
                    solution_preview=common_solution,
                    times_seen=len(issues),
                    last_used=latest.resolved_at,
                    related_issue_id=latest.id,
                )
            )
        fixes.sort(key=lambda item: (item.times_seen, _timestamp_score(item.last_used)), reverse=True)
        return fixes[: max(0, min(10, int(limit)))]

    def find_intake_suggestions(
        self,
        *,
        machine_number: str,
        query: str,
        limit: int = 5,
    ) -> list[IntakeSuggestion]:
        terms = _keywords(query)
        if not terms:
            return []
        candidates = self.list_resolved_issues(machine_number, limit=120)
        scored: list[tuple[int, ResolvedIssue]] = []
        for candidate in candidates:
            haystack = " ".join((candidate.title, candidate.description, candidate.solution, candidate.category)).casefold()
            score = sum(2 for term in terms if term in haystack)
            score += sum(1 for term in _keywords(candidate.title) & terms)
            if score:
                scored.append((score, candidate))
        scored.sort(key=lambda item: (item[0], _timestamp_score(item[1].resolved_at)), reverse=True)

        suggestions: list[IntakeSuggestion] = []
        for score, issue in scored[: max(0, min(5, int(limit)))]:
            if score >= 6:
                confidence = "High"
            elif score >= 3:
                confidence = "Medium"
            else:
                confidence = "Low"
            suggestions.append(
                IntakeSuggestion(
                    issue_id=issue.id,
                    title=issue.title,
                    category=issue.category or "Uncategorized",
                    solution_preview=preview(issue.solution, 120),
                    resolved_at=issue.resolved_at,
                    confidence=confidence,
                )
            )
        return suggestions

    def build_shift_handoff_summary(self, start_at: str, end_at: str) -> ShiftHandoffSummary:
        current_line_down = self.list_all_active_issues(severity="Line Down", sort_key="date_asc", limit=25)
        active_candidates = self.list_all_active_issues(sort_key="date_asc", limit=200)
        current_stale = [
            issue for issue in active_candidates
            if issue_age(issue).state in {"Stale", "Critical Aging"}
        ][:25]

        with connect(self.db_path) as conn:
            opened_rows = conn.execute(
                """
                SELECT
                    id,
                    issue_id AS public_issue_id,
                    machine_number,
                    logged_by,
                    title,
                    description,
                    severity,
                    category,
                    what_changed,
                    tried_already,
                    created_at,
                    updated_at
                FROM active_issues
                WHERE created_at >= ? AND created_at < ?
                ORDER BY created_at DESC, id DESC
                LIMIT 50
                """,
                (start_at, end_at),
            ).fetchall()
            resolved_rows = conn.execute(
                """
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
                    what_changed,
                    tried_already,
                    created_at,
                    resolved_at,
                    resolved_by,
                    solution,
                    archive_status,
                    archive_error
                FROM resolved_issues_cache
                WHERE resolved_at >= ? AND resolved_at < ?
                ORDER BY resolved_at DESC, id DESC
                LIMIT 50
                """,
                (start_at, end_at),
            ).fetchall()
            cluster_rows = conn.execute(
                """
                SELECT
                    m.machine_number,
                    m.name AS machine_name,
                    COUNT(ai.id) AS open_count,
                    SUM(CASE WHEN ai.severity = 'Line Down' THEN 1 ELSE 0 END) AS line_down_count
                FROM machines m
                INNER JOIN active_issues ai ON ai.machine_number = m.machine_number
                WHERE m.is_active = 1
                GROUP BY m.machine_number, m.name
                HAVING COUNT(ai.id) > 1
                ORDER BY COUNT(ai.id) DESC, m.machine_number
                LIMIT 10
                """
            ).fetchall()
            recurring_rows = conn.execute(
                """
                SELECT
                    machine_number,
                    title,
                    category,
                    COUNT(*) AS seen_count,
                    MAX(resolved_at) AS last_used,
                    MAX(id) AS related_issue_id,
                    MAX(solution) AS solution_preview
                FROM resolved_issues_cache
                WHERE resolved_at >= ? AND resolved_at < ?
                    AND TRIM(title) <> ''
                GROUP BY machine_number, LOWER(TRIM(title)), LOWER(TRIM(category))
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC, MAX(resolved_at) DESC
                LIMIT 10
                """,
                (start_at, end_at),
            ).fetchall()

        archive_counts = self.archive_status_counts()
        return ShiftHandoffSummary(
            start_at=start_at,
            end_at=end_at,
            current_line_down=current_line_down,
            current_stale=current_stale,
            opened=[self._issue_from_row(row) for row in opened_rows],
            resolved=[self._resolved_from_row(row) for row in resolved_rows],
            multiple_open=[
                MachineOpenCluster(
                    machine_number=row["machine_number"],
                    machine_name=row["machine_name"],
                    open_count=int(row["open_count"] or 0),
                    line_down_count=int(row["line_down_count"] or 0),
                )
                for row in cluster_rows
            ],
            recurring_patterns=[
                KnownFix(
                    pattern=preview(row["title"], 90),
                    category=row["category"] or "Uncategorized",
                    solution_preview=preview(row["solution_preview"], 120),
                    times_seen=int(row["seen_count"] or 0),
                    last_used=row["last_used"] or "",
                    related_issue_id=int(row["related_issue_id"] or 0),
                )
                for row in recurring_rows
            ],
            archive_pending_count=int(archive_counts.get("pending", 0)) + int(archive_counts.get("retry_pending", 0)),
            archive_failed_count=int(archive_counts.get("failed", 0)) + int(archive_counts.get("archive_error", 0)),
        )

    def build_data_health_summary(self, paths) -> DataHealthSummary:
        with connect(self.db_path) as conn:
            machine_count = int(conn.execute("SELECT COUNT(*) FROM machines WHERE is_active = 1").fetchone()[0])
            active_count = int(conn.execute("SELECT COUNT(*) FROM active_issues").fetchone()[0])
            resolved_count = int(conn.execute("SELECT COUNT(*) FROM resolved_issues_cache").fetchone()[0])
            archive_success = conn.execute(
                """
                SELECT created_at
                FROM issue_events
                WHERE event_type = 'archive_success'
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        archive_counts = self.archive_status_counts()
        latest = self.get_latest_resolved_issue()
        return DataHealthSummary(
            db_path=str(paths.db_path),
            db_exists=paths.db_path.exists(),
            runtime_config_path=str(paths.runtime_config_path),
            archive_path=str(paths.archive_path),
            archive_path_exists=paths.archive_path.exists(),
            machine_count=machine_count,
            active_issue_count=active_count,
            resolved_cache_count=resolved_count,
            archive_pending_count=int(archive_counts.get("pending", 0)) + int(archive_counts.get("retry_pending", 0)),
            archive_failed_count=int(archive_counts.get("failed", 0)) + int(archive_counts.get("archive_error", 0)),
            last_resolved_label=display_issue_id(latest) if latest else "none",
            last_archive_success=archive_success["created_at"] if archive_success else "none",
        )

    def get_latest_resolved_issue(self) -> ResolvedIssue | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
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
                    what_changed,
                    tried_already,
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

    def list_failed_archive_writes(self, limit: int = 100) -> list[ResolvedIssue]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
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
                    what_changed,
                    tried_already,
                    created_at,
                    resolved_at,
                    resolved_by,
                    solution,
                    archive_status,
                    archive_error
                FROM resolved_issues_cache
                WHERE archive_status IN ('failed', 'retry_pending')
                ORDER BY resolved_at ASC, id ASC
                LIMIT ?
                """,
                (max(0, int(limit)),),
            ).fetchall()
        return [self._resolved_from_row(row) for row in rows]

    def mark_archive_retry_pending(self, resolved_issue_ids: list[int]) -> None:
        if not resolved_issue_ids:
            return
        with connect(self.db_path) as conn:
            conn.executemany(
                """
                UPDATE resolved_issues_cache
                SET archive_status = 'retry_pending',
                    archive_error = ''
                WHERE id = ?
                    AND archive_status IN ('failed', 'retry_pending')
                """,
                [(int(issue_id),) for issue_id in resolved_issue_ids],
            )

    def trim_resolved_issue_cache(
        self,
        *,
        keep_days: int = 180,
        keep_minimum: int = 1000,
        keep_per_machine_minimum: int = 25,
        now: datetime | None = None,
    ) -> int:
        now_utc = now or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        cutoff = now_utc - timedelta(days=max(1, int(keep_days)))

        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, machine_number, resolved_at
                FROM resolved_issues_cache
                WHERE archive_status = 'archived'
                ORDER BY resolved_at DESC, id DESC
                """
            ).fetchall()
            protected: set[int] = set()
            for row in rows:
                resolved_at = _parse_iso(row["resolved_at"])
                if resolved_at is not None and resolved_at >= cutoff:
                    protected.add(int(row["id"]))

            protected.update(int(row["id"]) for row in rows[: max(0, int(keep_minimum))])

            per_machine_counts: dict[str, int] = {}
            for row in rows:
                machine_number = row["machine_number"]
                count = per_machine_counts.get(machine_number, 0)
                if count < max(0, int(keep_per_machine_minimum)):
                    protected.add(int(row["id"]))
                    per_machine_counts[machine_number] = count + 1

            delete_ids = [int(row["id"]) for row in rows if int(row["id"]) not in protected]
            if not delete_ids:
                return 0
            conn.executemany(
                "DELETE FROM resolved_issues_cache WHERE id = ? AND archive_status = 'archived'",
                [(issue_id,) for issue_id in delete_ids],
            )
            return len(delete_ids)

    def log_issue(
        self,
        *,
        machine_number: str,
        logged_by: str,
        title: str,
        description: str,
        severity: str,
        category: str = "",
        what_changed: str = "",
        tried_already: str = "",
        created_at: str | None = None,
    ) -> Issue:
        machine_number = machine_number.strip()
        logged_by = logged_by.strip()
        title = title.strip()
        description = description.strip()
        severity = severity.strip()
        category = category.strip()
        what_changed = what_changed.strip()
        tried_already = tried_already.strip()

        if not logged_by:
            raise ValueError("Logged by is required.")
        if not title:
            raise ValueError("Issue title is required.")
        if not description:
            raise ValueError("Problem description is required.")
        if severity not in ACTIVE_SEVERITIES:
            raise ValueError("Status must be Line Down or Non-Critical.")

        now = (created_at or utc_now_iso()).strip()
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            machine_exists = conn.execute(
                "SELECT 1 FROM machines WHERE machine_number = ? AND is_active = 1",
                (machine_number,),
            ).fetchone()
            if machine_exists is None:
                raise ValueError(f"Machine {machine_number} was not found.")
            public_issue_id = generate_issue_id(now, self._existing_public_issue_ids(conn))
            cursor = conn.execute(
                """
                INSERT INTO active_issues
                    (
                        issue_id,
                        machine_number,
                        logged_by,
                        title,
                        description,
                        severity,
                        category,
                        what_changed,
                        tried_already,
                        created_at,
                        updated_at
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    public_issue_id,
                    machine_number,
                    logged_by,
                    title,
                    description,
                    severity,
                    category,
                    what_changed,
                    tried_already,
                    now,
                    now,
                ),
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
                    "issue_id": public_issue_id,
                    "title": title,
                    "severity": severity,
                    "category": category,
                    "what_changed": what_changed,
                    "tried_already": tried_already,
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
                SELECT
                    id,
                    issue_id,
                    machine_number,
                    logged_by,
                    title,
                    description,
                    severity,
                    category,
                    what_changed,
                    tried_already,
                    created_at,
                    updated_at
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
                        issue_id,
                        original_issue_id,
                        machine_number,
                        logged_by,
                        title,
                        description,
                        severity,
                        category,
                        what_changed,
                        tried_already,
                        created_at,
                        resolved_at,
                        resolved_by,
                        solution,
                        archive_status
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    issue["issue_id"] or "",
                    int(issue["id"]),
                    issue["machine_number"],
                    issue["logged_by"],
                    issue["title"],
                    issue["description"],
                    issue["severity"],
                    issue["category"],
                    issue["what_changed"],
                    issue["tried_already"],
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
                    issue_id AS public_issue_id,
                    original_issue_id,
                    machine_number,
                    logged_by,
                    title,
                    description,
                    severity,
                    category,
                    what_changed,
                    tried_already,
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
        archive_status = "archived" if success else "failed"
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
        with connect(self.db_path) as conn:
            total_resolved = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM resolved_issues_cache
                    WHERE machine_number = ?
                    """,
                    (machine_number,),
                ).fetchone()[0]
            )
            if total_resolved == 0:
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

            category_row = conn.execute(
                """
                SELECT category, COUNT(*) AS issue_count
                FROM resolved_issues_cache
                WHERE machine_number = ? AND TRIM(category) <> ''
                GROUP BY category
                ORDER BY issue_count DESC, category COLLATE NOCASE ASC
                LIMIT 1
                """,
                (machine_number,),
            ).fetchone()
            title_row = conn.execute(
                """
                SELECT title, COUNT(*) AS issue_count
                FROM resolved_issues_cache
                WHERE machine_number = ? AND TRIM(title) <> ''
                GROUP BY LOWER(TRIM(title))
                ORDER BY issue_count DESC, MAX(resolved_at) DESC
                LIMIT 1
                """,
                (machine_number,),
            ).fetchone()
            latest_row = conn.execute(
                """
                SELECT title, resolved_at
                FROM resolved_issues_cache
                WHERE machine_number = ?
                ORDER BY resolved_at DESC, id DESC
                LIMIT 1
                """,
                (machine_number,),
            ).fetchone()
            average_row = conn.execute(
                """
                SELECT AVG(MAX(0, strftime('%s', resolved_at) - strftime('%s', created_at))) AS average_seconds
                FROM resolved_issues_cache
                WHERE machine_number = ?
                    AND strftime('%s', resolved_at) IS NOT NULL
                    AND strftime('%s', created_at) IS NOT NULL
                """,
                (machine_number,),
            ).fetchone()

        most_common_category = category_row["category"] if category_row is not None else ""
        most_common_title = title_row["title"] if title_row is not None else ""
        title_count = int(title_row["issue_count"] or 0) if title_row is not None else 0
        category_count = int(category_row["issue_count"] or 0) if category_row is not None else 0
        recurring_warning = ""
        if most_common_title and title_count >= 2:
            recurring_warning = f"{most_common_title} repeated {title_count} times"
        elif most_common_category and category_count >= 2:
            recurring_warning = f"{most_common_category} repeated {category_count} times"

        average_value = average_row["average_seconds"] if average_row is not None else None
        average_seconds = int(average_value) if average_value is not None else None
        return MachineResolvedStats(
            machine_number=machine_number,
            total_resolved=total_resolved,
            most_common_category=most_common_category,
            most_common_title=most_common_title,
            last_resolved_title=latest_row["title"] if latest_row is not None else "",
            last_resolved_at=latest_row["resolved_at"] if latest_row is not None else "",
            average_time_open_seconds=average_seconds,
            recurring_warning=recurring_warning,
        )

    @staticmethod
    def _existing_public_issue_ids(conn) -> list[str]:
        rows = conn.execute(
            """
            SELECT issue_id
            FROM active_issues
            WHERE issue_id <> ''
            UNION
            SELECT issue_id
            FROM resolved_issues_cache
            WHERE issue_id <> ''
            """
        ).fetchall()
        return [str(row["issue_id"]) for row in rows if row["issue_id"]]

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
            public_issue_id=row["public_issue_id"],
            what_changed=_row_value(row, "what_changed"),
            tried_already=_row_value(row, "tried_already"),
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
            public_issue_id=row["public_issue_id"],
            what_changed=_row_value(row, "what_changed"),
            tried_already=_row_value(row, "tried_already"),
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

    @staticmethod
    def _issue_search_result_from_row(row) -> IssueSearchResult:
        return IssueSearchResult(
            state=row["state"],
            issue_id=int(row["issue_id"]),
            machine_number=row["machine_number"],
            machine_name=row["machine_name"],
            machine_model=row["machine_model"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            category=row["category"],
            logged_by=row["logged_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            resolved_at=row["resolved_at"],
            resolved_by=row["resolved_by"],
            resolution=row["resolution"],
            history_text=row["history_text"],
            public_issue_id=row["public_issue_id"],
            source=row["source"],
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


def _row_value(row, key: str, default: str = "") -> str:
    try:
        if key not in row.keys():
            return default
    except AttributeError:
        return default
    value = row[key]
    return str(value or "")


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


def _keywords(value: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", value.casefold()) if len(word) >= 4}


def _issue_search_text(result: IssueSearchResult) -> str:
    return " ".join(
        str(value).casefold()
        for value in (
            result.state,
            result.public_issue_id,
            result.machine_number,
            result.machine_name,
            result.machine_model,
            result.title,
            result.description,
            result.status,
            result.category,
            result.logged_by,
            result.created_at,
            result.updated_at,
            result.resolved_at,
            result.resolved_by,
            result.resolution,
            result.history_text,
        )
        if value
    )


def _timestamp_score(value: str) -> float:
    parsed = _parse_iso(value)
    return parsed.timestamp() if parsed else 0.0
