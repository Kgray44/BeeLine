from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from beeline_issue_tracker.data.database import initialize_database
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.domain import LINE_DOWN, NON_CRITICAL


DEMO_MACHINES = (
    ("DEMO-101", "Demo Molder 101", "Demo Hive", "Cell A", "DEMO-ASSET-101", 10),
    ("DEMO-202", "Demo Press 202", "Demo Hive", "Cell B", "DEMO-ASSET-202", 20),
    ("PACK-303", "Demo Packer 303", "Packing", "Cell C", "DEMO-ASSET-303", 30),
)


class RepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "beeline.sqlite3"
        initialize_database(self.db_path, DEMO_MACHINES)
        self.repository = IssueRepository(self.db_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_issue_created_resolved_and_archive_events_are_written(self) -> None:
        issue = self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Test Operator",
            title="Nozzle heater drift",
            description="Nozzle temperature is wandering.",
            severity=NON_CRITICAL,
            category="Process",
        )
        created_events = self.repository.list_events_for_issue(issue.id)
        self.assertEqual(["issue_created"], [event.event_type for event in created_events])
        self.assertEqual("Test Operator", created_events[0].actor)
        self.assertEqual("Nozzle heater drift", json.loads(created_events[0].details_json)["title"])

        resolved = self.repository.resolve_issue(
            issue.id,
            solution="Tightened thermocouple connection.",
            resolved_by="Test Tech",
        )
        self.repository.mark_archive_result(resolved.id, success=True)
        events = self.repository.list_events_for_issue(issue.id)
        self.assertEqual(["issue_created", "issue_resolved", "archive_success"], [event.event_type for event in events])
        self.assertEqual("BeeLine Archive Worker", events[-1].actor)

        self.repository.mark_archive_result(resolved.id, success=False, error="fake archive failure")
        latest = self.repository.list_issue_events(machine_number="DEMO-101", limit=1)[0]
        self.assertEqual("archive_failure", latest.event_type)
        self.assertEqual("fake archive failure", json.loads(latest.details_json)["error"])

    def test_active_issue_search_sort_limit_and_global_filters(self) -> None:
        self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Alex",
            title="Sensor drift",
            description="Nozzle temperature sensor is wandering",
            severity=NON_CRITICAL,
            category="Sensor",
        )
        self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Jordan",
            title="Guard switch open",
            description="Press stopped at the safety gate",
            severity=LINE_DOWN,
            category="Safety",
        )
        self.repository.log_issue(
            machine_number="DEMO-202",
            logged_by="Casey",
            title="Oil weep",
            description="Small leak under clamp side",
            severity=NON_CRITICAL,
            category="Hydraulic",
        )

        sensor = self.repository.list_active_issues("DEMO-101", query="sensor alex")
        self.assertEqual(["Sensor drift"], [issue.title for issue in sensor])

        title_desc = self.repository.list_active_issues("DEMO-101", sort_key="title_desc", limit=1)
        self.assertEqual(["Sensor drift"], [issue.title for issue in title_desc])

        global_line_down = self.repository.list_all_active_issues(severity=LINE_DOWN)
        self.assertEqual(["Guard switch open"], [issue.title for issue in global_line_down])

        cell_b = self.repository.list_all_active_issues(area="Demo Hive", cell="Cell B")
        self.assertEqual(["Oil weep"], [issue.title for issue in cell_b])

    def test_resolved_search_sort_limit_context_and_stats(self) -> None:
        first = self._resolve("Nozzle heater drift", "Adjusted heater band.", "Process")
        second = self._resolve("Nozzle heater drift", "Replaced heater band.", "Process")
        third = self._resolve("Robot ready fault", "Reset robot controller.", "Automation")
        self._set_resolved_times(first.id, "2026-06-01T10:00:00+00:00", "2026-06-01T11:30:00+00:00")
        self._set_resolved_times(second.id, "2026-06-02T10:00:00+00:00", "2026-06-02T11:00:00+00:00")
        self._set_resolved_times(third.id, "2026-06-03T10:00:00+00:00", "2026-06-03T10:30:00+00:00")

        heater = self.repository.list_resolved_issues("DEMO-101", query="heater band", sort_key="title_asc", limit=10)
        self.assertEqual([second.id, first.id], [issue.id for issue in heater])

        limited = self.repository.list_resolved_issues("DEMO-101", sort_key="date_desc", limit=2)
        self.assertEqual([third.id, second.id], [issue.id for issue in limited])

        context = self.repository.get_resolved_issue_with_machine_context(second.id)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual("Demo Molder 101", context.machine.name if context.machine else "")

        stats = self.repository.get_machine_resolved_stats("DEMO-101")
        self.assertEqual(3, stats.total_resolved)
        self.assertEqual("Process", stats.most_common_category)
        self.assertEqual("Nozzle heater drift", stats.most_common_title)
        self.assertEqual(3600, stats.average_time_open_seconds)
        self.assertIn("repeated 2 times", stats.recurring_warning)

        active = self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Alex",
            title="Nozzle heater cold",
            description="Heater is not reaching setpoint.",
            severity=NON_CRITICAL,
            category="Process",
        )
        active_context = self.repository.get_issue_with_machine_context(active.id)
        self.assertIsNotNone(active_context)
        related = self.repository.find_related_resolved_issues(active, limit=2)
        self.assertEqual([second.id, first.id], [issue.id for issue in related])
        trend = self.repository.get_machine_issue_trend_summary("DEMO-101")
        self.assertEqual(1, trend["active"])
        self.assertEqual(3, trend["resolved"])

    def test_stats_with_no_resolved_data_is_empty(self) -> None:
        stats = self.repository.get_machine_resolved_stats("PACK-303")
        self.assertEqual(0, stats.total_resolved)
        self.assertIsNone(stats.average_time_open_seconds)
        self.assertEqual("", stats.recurring_warning)

    def _resolve(self, title: str, solution: str, category: str):
        issue = self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Test Operator",
            title=title,
            description=f"{title} description.",
            severity=NON_CRITICAL,
            category=category,
        )
        return self.repository.resolve_issue(issue.id, solution=solution, resolved_by="Test Tech")

    def _set_resolved_times(self, resolved_id: int, created_at: str, resolved_at: str) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                UPDATE resolved_issues_cache
                SET created_at = ?, resolved_at = ?
                WHERE id = ?
                """,
                (created_at, resolved_at, resolved_id),
            )
            conn.commit()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
