from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from beeline_issue_tracker.domain import Issue, ResolvedIssue
from beeline_issue_tracker.ui.issue_list_model import (
    DATE_ASC,
    DATE_DESC,
    ISSUE_ID_ASC,
    ISSUE_ID_DESC,
    LATEST_OPTIONS,
    TITLE_ASC,
    TITLE_DESC,
    format_duration_between,
    prepare_issue_rows,
)


def active_issue(
    issue_id: int,
    *,
    title: str,
    created_at: str,
    description: str = "General issue",
    logged_by: str = "Operator",
    severity: str = "Non-Critical",
    category: str = "",
    machine_number: str = "M-101",
    public_issue_id: str = "",
) -> Issue:
    return Issue(
        id=issue_id,
        machine_number=machine_number,
        logged_by=logged_by,
        title=title,
        description=description,
        severity=severity,
        category=category,
        created_at=created_at,
        updated_at=created_at,
        public_issue_id=public_issue_id,
    )


def resolved_issue(
    issue_id: int,
    *,
    title: str,
    created_at: str,
    resolved_at: str,
    solution: str = "Fixed",
    resolved_by: str = "Maintenance",
    description: str = "General issue",
    severity: str = "Non-Critical",
    category: str = "",
    machine_number: str = "M-101",
    public_issue_id: str = "",
) -> ResolvedIssue:
    return ResolvedIssue(
        id=issue_id,
        original_issue_id=issue_id,
        machine_number=machine_number,
        logged_by="Operator",
        title=title,
        description=description,
        severity=severity,
        category=category,
        created_at=created_at,
        resolved_at=resolved_at,
        resolved_by=resolved_by,
        solution=solution,
        archive_status="archived",
        archive_error="",
        public_issue_id=public_issue_id,
    )


class IssueListModelTest(unittest.TestCase):
    def test_active_search_matches_useful_fields_and_limits_after_sort(self) -> None:
        issues = [
            active_issue(
                1,
                title="Sensor drift",
                description="Nozzle temperature sensor is wandering",
                logged_by="Alex",
                category="Sensor",
                created_at="2026-06-03T13:00:00+00:00",
            ),
            active_issue(
                2,
                title="Guard switch open",
                description="Press stopped at the safety gate",
                logged_by="Jordan",
                severity="Line Down",
                category="Safety",
                created_at="2026-06-03T14:00:00+00:00",
            ),
            active_issue(
                3,
                title="Oil weep",
                description="Small leak under clamp side",
                logged_by="Casey",
                category="Hydraulic",
                created_at="2026-06-03T12:00:00+00:00",
                machine_number="M-202",
            ),
        ]

        sensor_rows = prepare_issue_rows(issues, query="sensor alex", sort_key=DATE_DESC, latest_limit=10)
        self.assertEqual([1], [issue.id for issue in sensor_rows])

        latest_two = prepare_issue_rows(issues, sort_key=DATE_DESC, latest_limit=2)
        self.assertEqual([2, 1], [issue.id for issue in latest_two])

        machine_rows = prepare_issue_rows(issues, query="m-202", sort_key=DATE_DESC, latest_limit=10)
        self.assertEqual([3], [issue.id for issue in machine_rows])

    def test_title_sorting_supports_both_directions(self) -> None:
        issues = [
            active_issue(1, title="Zebra alarm", created_at="2026-06-03T13:00:00+00:00"),
            active_issue(2, title="Alpha alarm", created_at="2026-06-03T14:00:00+00:00"),
        ]

        ascending = prepare_issue_rows(issues, sort_key=TITLE_ASC, latest_limit=None)
        descending = prepare_issue_rows(issues, sort_key=TITLE_DESC, latest_limit=None)

        self.assertEqual([2, 1], [issue.id for issue in ascending])
        self.assertEqual([1, 2], [issue.id for issue in descending])

    def test_issue_id_search_and_sorting_uses_public_id(self) -> None:
        issues = [
            active_issue(1, title="First", created_at="2026-06-03T13:00:00+00:00", public_issue_id="ISS-20260603-002"),
            active_issue(2, title="Second", created_at="2026-06-03T14:00:00+00:00", public_issue_id="ISS-20260603-001"),
            active_issue(3, title="Third", created_at="2026-06-04T08:00:00+00:00", public_issue_id="ISS-20260604-001"),
        ]

        matched = prepare_issue_rows(issues, query="20260603-001", sort_key=DATE_DESC, latest_limit=None)
        ascending = prepare_issue_rows(issues, sort_key=ISSUE_ID_ASC, latest_limit=None)
        descending = prepare_issue_rows(issues, sort_key=ISSUE_ID_DESC, latest_limit=None)

        self.assertEqual([2], [issue.id for issue in matched])
        self.assertEqual([2, 1, 3], [issue.id for issue in ascending])
        self.assertEqual([3, 1, 2], [issue.id for issue in descending])

    def test_resolved_search_and_date_sort_use_resolved_fields(self) -> None:
        issues = [
            resolved_issue(
                1,
                title="Older close",
                created_at="2026-06-01T10:00:00+00:00",
                resolved_at="2026-06-01T11:00:00+00:00",
                solution="Replaced worn bearing",
                resolved_by="Taylor",
            ),
            resolved_issue(
                2,
                title="Newer close",
                created_at="2026-05-30T10:00:00+00:00",
                resolved_at="2026-06-03T11:00:00+00:00",
                solution="Reset controller",
                resolved_by="Morgan",
            ),
        ]

        resolved_search = prepare_issue_rows(
            issues,
            query="bearing taylor",
            sort_key=DATE_DESC,
            latest_limit=10,
            include_resolved_fields=True,
        )
        self.assertEqual([1], [issue.id for issue in resolved_search])

        newest_resolved = prepare_issue_rows(
            issues,
            sort_key=DATE_DESC,
            latest_limit=None,
            include_resolved_fields=True,
        )
        oldest_resolved = prepare_issue_rows(
            issues,
            sort_key=DATE_ASC,
            latest_limit=None,
            include_resolved_fields=True,
        )
        self.assertEqual([2, 1], [issue.id for issue in newest_resolved])
        self.assertEqual([1, 2], [issue.id for issue in oldest_resolved])

    def test_time_open_format_is_compact(self) -> None:
        self.assertEqual(
            "2h 15m",
            format_duration_between("2026-06-03T10:00:00+00:00", "2026-06-03T12:15:00+00:00"),
        )

    def test_latest_options_are_bounded(self) -> None:
        self.assertNotIn(None, [value for _label, value in LATEST_OPTIONS])
        self.assertLessEqual(max(value for _label, value in LATEST_OPTIONS), 100)


if __name__ == "__main__":
    unittest.main()
