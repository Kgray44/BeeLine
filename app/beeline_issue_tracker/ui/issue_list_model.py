from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Iterable, TypeVar

from beeline_issue_tracker.domain import Issue, ResolvedIssue, display_issue_id, issue_id_sort_key


TITLE_ASC = "title_asc"
TITLE_DESC = "title_desc"
DATE_DESC = "date_desc"
DATE_ASC = "date_asc"
ISSUE_ID_ASC = "issue_id_asc"
ISSUE_ID_DESC = "issue_id_desc"

SORT_OPTIONS = (
    ("Newest First", DATE_DESC),
    ("Oldest First", DATE_ASC),
    ("Issue ID A-Z", ISSUE_ID_ASC),
    ("Issue ID Z-A", ISSUE_ID_DESC),
    ("Title A-Z", TITLE_ASC),
    ("Title Z-A", TITLE_DESC),
)

LATEST_OPTIONS = (
    ("Latest 1", 1),
    ("Latest 5", 5),
    ("Latest 10", 10),
    ("Latest 20", 20),
    ("Latest 50", 50),
    ("Latest 100", 100),
)

IssueLike = TypeVar("IssueLike", Issue, ResolvedIssue)


def prepare_issue_rows(
    issues: Iterable[IssueLike],
    *,
    query: str = "",
    sort_key: str = DATE_DESC,
    latest_limit: int | None = 10,
    include_resolved_fields: bool = False,
) -> list[IssueLike]:
    matching = filter_issues(
        issues,
        query=query,
        include_resolved_fields=include_resolved_fields,
    )
    ordered = sort_issues(
        matching,
        sort_key=sort_key,
        date_field="resolved_at" if include_resolved_fields else "created_at",
    )
    return limit_issues(ordered, latest_limit)


def filter_issues(
    issues: Iterable[IssueLike],
    *,
    query: str = "",
    include_resolved_fields: bool = False,
) -> list[IssueLike]:
    normalized_query = " ".join(query.casefold().split())
    if not normalized_query:
        return list(issues)

    terms = normalized_query.split(" ")
    return [
        issue
        for issue in issues
        if all(term in issue_search_text(issue, include_resolved_fields=include_resolved_fields) for term in terms)
    ]


def sort_issues(
    issues: Iterable[IssueLike],
    *,
    sort_key: str = DATE_DESC,
    date_field: str = "created_at",
) -> list[IssueLike]:
    rows = list(issues)
    if sort_key == TITLE_ASC:
        return sorted(rows, key=lambda issue: issue.title.casefold())
    if sort_key == TITLE_DESC:
        return sorted(rows, key=lambda issue: issue.title.casefold(), reverse=True)
    if sort_key == ISSUE_ID_ASC:
        return sorted(rows, key=issue_id_sort_key)
    if sort_key == ISSUE_ID_DESC:
        return sorted(rows, key=issue_id_sort_key, reverse=True)
    if sort_key == DATE_ASC:
        return sorted(rows, key=lambda issue: parse_timestamp(str(getattr(issue, date_field, ""))))
    return sorted(rows, key=lambda issue: parse_timestamp(str(getattr(issue, date_field, ""))), reverse=True)


def limit_issues(issues: Iterable[IssueLike], latest_limit: int | None) -> list[IssueLike]:
    rows = list(issues)
    if latest_limit is None:
        return rows
    return rows[: max(0, int(latest_limit))]


def issue_search_text(issue: Issue | ResolvedIssue, *, include_resolved_fields: bool = False) -> str:
    fields = [
        display_issue_id(issue),
        issue.title,
        issue.description,
        issue.logged_by,
        issue.severity,
        issue.category,
        issue.machine_number,
    ]
    if include_resolved_fields and isinstance(issue, ResolvedIssue):
        fields.extend([issue.solution, issue.resolved_by, issue.archive_status])
    return " ".join(str(field).casefold() for field in fields if field)


@lru_cache(maxsize=20000)
def parse_timestamp(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def format_timestamp(value: str) -> str:
    timestamp = parse_timestamp(value)
    if timestamp == datetime.min.replace(tzinfo=timezone.utc):
        return "-"
    return timestamp.astimezone().strftime("%Y-%m-%d %H:%M")


def format_duration_between(start_value: str, end_value: str | None = None) -> str:
    start = parse_timestamp(start_value)
    end = parse_timestamp(end_value) if end_value else datetime.now(timezone.utc)
    total_seconds = max(0, int((end - start).total_seconds()))
    minutes = total_seconds // 60
    hours = minutes // 60
    days = hours // 24

    if days:
        return f"{days}d {hours % 24}h"
    if hours:
        return f"{hours}h {minutes % 60}m"
    if minutes:
        return f"{minutes}m"
    return "<1m"


def preview_text(value: str, max_length: int = 96) -> str:
    normalized = " ".join((value or "").split())
    if len(normalized) <= max_length:
        return normalized or "-"
    return normalized[: max_length - 3].rstrip() + "..."
