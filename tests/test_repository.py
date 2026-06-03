from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from beeline_issue_tracker.data.database import initialize_database
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.domain import LINE_DOWN, NON_CRITICAL, display_issue_id


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

    def test_creating_first_issue_of_day_generates_public_issue_id(self) -> None:
        issue = self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Alex",
            title="Sensor drift",
            description="Nozzle temperature sensor is wandering.",
            severity=NON_CRITICAL,
            category="Sensor",
            created_at="2026-06-03T08:15:00+00:00",
        )

        self.assertEqual("ISS-20260603-001", issue.public_issue_id)
        self.assertEqual("ISS-20260603-001", display_issue_id(issue))

    def test_creating_multiple_issues_on_same_day_increments_sequence(self) -> None:
        first = self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Alex",
            title="Sensor drift",
            description="Nozzle temperature sensor is wandering.",
            severity=NON_CRITICAL,
            category="Sensor",
            created_at="2026-06-03T08:15:00+00:00",
        )
        second = self.repository.log_issue(
            machine_number="DEMO-202",
            logged_by="Jordan",
            title="Guard switch open",
            description="Press stopped at the safety gate.",
            severity=LINE_DOWN,
            category="Safety",
            created_at="2026-06-03T11:30:00+00:00",
        )

        self.assertEqual("ISS-20260603-001", first.public_issue_id)
        self.assertEqual("ISS-20260603-002", second.public_issue_id)

    def test_creating_issues_on_different_days_resets_sequence(self) -> None:
        first = self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Alex",
            title="Sensor drift",
            description="Nozzle temperature sensor is wandering.",
            severity=NON_CRITICAL,
            category="Sensor",
            created_at="2026-06-03T08:15:00+00:00",
        )
        next_day = self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Alex",
            title="Oil weep",
            description="Small leak under clamp side.",
            severity=NON_CRITICAL,
            category="Hydraulic",
            created_at="2026-06-04T08:15:00+00:00",
        )

        self.assertEqual("ISS-20260603-001", first.public_issue_id)
        self.assertEqual("ISS-20260604-001", next_day.public_issue_id)

    def test_old_numeric_issue_ids_are_preserved_for_display(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                """
                INSERT INTO active_issues
                    (machine_number, logged_by, title, description, severity, category, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "DEMO-101",
                    "Legacy Operator",
                    "Legacy numeric issue",
                    "Old issue before public IDs existed.",
                    NON_CRITICAL,
                    "Legacy",
                    "2026-06-02T10:00:00+00:00",
                    "2026-06-02T10:00:00+00:00",
                ),
            )
            legacy_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()

        issue = self.repository.get_active_issue(legacy_id)

        self.assertIsNotNone(issue)
        assert issue is not None
        self.assertEqual(str(legacy_id), display_issue_id(issue))

    def test_generated_issue_ids_do_not_duplicate_resolved_history(self) -> None:
        first = self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Alex",
            title="Sensor drift",
            description="Nozzle temperature sensor is wandering.",
            severity=NON_CRITICAL,
            category="Sensor",
            created_at="2026-06-03T08:15:00+00:00",
        )
        self.repository.resolve_issue(first.id, solution="Reset sensor.", resolved_by="Taylor")

        second = self.repository.log_issue(
            machine_number="DEMO-202",
            logged_by="Jordan",
            title="Guard switch open",
            description="Press stopped at the safety gate.",
            severity=LINE_DOWN,
            category="Safety",
            created_at="2026-06-03T11:30:00+00:00",
        )

        self.assertEqual("ISS-20260603-002", second.public_issue_id)

    def test_search_finds_new_issue_id_full_date_and_sequence(self) -> None:
        issue = self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Alex",
            title="Sensor drift",
            description="Nozzle temperature sensor is wandering.",
            severity=NON_CRITICAL,
            category="Sensor",
            created_at="2026-06-03T08:15:00+00:00",
        )

        by_full_id = self.repository.search_issues("ISS-20260603-001")
        by_date = self.repository.search_issues("20260603")
        by_sequence = self.repository.search_issues("001")
        machine_list = self.repository.list_active_issues("DEMO-101", query="ISS-20260603")

        self.assertEqual([issue.id], [result.issue_id for result in by_full_id])
        self.assertEqual([issue.id], [result.issue_id for result in by_date])
        self.assertEqual([issue.id], [result.issue_id for result in by_sequence])
        self.assertEqual([issue.id], [row.id for row in machine_list])

    def test_repository_sorting_by_issue_id_is_chronological_for_new_ids(self) -> None:
        newer_day = self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Alex",
            title="Newer day",
            description="Issue logged on the newer day.",
            severity=NON_CRITICAL,
            category="Test",
            created_at="2026-06-04T08:15:00+00:00",
        )
        older_day = self.repository.log_issue(
            machine_number="DEMO-202",
            logged_by="Jordan",
            title="Older day",
            description="Issue logged on the older day.",
            severity=NON_CRITICAL,
            category="Test",
            created_at="2026-06-03T08:15:00+00:00",
        )

        ascending = self.repository.list_all_active_issues(sort_key="issue_id_asc", limit=None)
        descending = self.repository.list_all_active_issues(sort_key="issue_id_desc", limit=None)

        self.assertEqual([older_day.id, newer_day.id], [issue.id for issue in ascending])
        self.assertEqual([newer_day.id, older_day.id], [issue.id for issue in descending])

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

        second_page = self.repository.list_active_issues("DEMO-101", sort_key="title_desc", limit=1, offset=1)
        self.assertEqual(["Guard switch open"], [issue.title for issue in second_page])
        self.assertEqual(2, self.repository.count_active_issues_matching("DEMO-101"))
        self.assertEqual(1, self.repository.count_active_issues_matching("DEMO-101", "guard safety"))

        global_line_down = self.repository.list_all_active_issues(severity=LINE_DOWN)
        self.assertEqual(["Guard switch open"], [issue.title for issue in global_line_down])

        cell_b = self.repository.list_all_active_issues(area="Demo Hive", cell="Cell B")
        self.assertEqual(["Oil weep"], [issue.title for issue in cell_b])

    def test_dashboard_issue_search_includes_open_and_resolved_history(self) -> None:
        active = self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Alex",
            title="Robot vacuum fault",
            description="Robot does not see vacuum made.",
            severity=NON_CRITICAL,
            category="Automation",
        )
        to_resolve = self.repository.log_issue(
            machine_number="DEMO-202",
            logged_by="Jordan",
            title="Clamp alarm",
            description="Clamp alarm on startup.",
            severity=LINE_DOWN,
            category="Machine",
        )
        resolved = self.repository.resolve_issue(
            to_resolve.id,
            solution="Reset clamp transducer and verified startup.",
            resolved_by="Taylor",
        )

        all_results = self.repository.search_issues("demo molder robot", state_filter="all")
        self.assertEqual([active.id], [result.issue_id for result in all_results])
        self.assertEqual("open", all_results[0].state)

        resolved_results = self.repository.search_issues("transducer taylor", state_filter="resolved")
        self.assertEqual([resolved.id], [result.issue_id for result in resolved_results])
        self.assertEqual("resolved", resolved_results[0].state)
        self.assertEqual("Recent Archive", resolved_results[0].source)

        open_only = self.repository.search_issues("clamp", state_filter="open")
        self.assertEqual([], open_only)

    def test_quick_search_uses_sqlite_without_excel_archive(self) -> None:
        issue = self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Alex",
            title="Vacuum sensor fault",
            description="Robot vacuum sensor did not make.",
            severity=NON_CRITICAL,
            category="Automation",
        )

        results = self.repository.search_issues("vacuum sensor", state_filter="all", limit=10)

        self.assertEqual([issue.id], [result.issue_id for result in results])
        self.assertEqual("Open Issue", results[0].source)

    def test_machine_metadata_columns_are_supported(self) -> None:
        metadata_db = self.root / "metadata.sqlite3"
        initialize_database(
            metadata_db,
            (
                (
                    "S01",
                    "Engel e-victory 80/28",
                    "Royalton P7",
                    "Silicones",
                    "IMM Serial 166303",
                    10,
                    "Engel",
                    "e-victory 80/28",
                    "166303",
                    "Fanuc",
                    "LR Mate 200iC/5C",
                    "R08900890",
                ),
            ),
        )
        repo = IssueRepository(metadata_db)

        machine = repo.get_machine("S01")

        self.assertIsNotNone(machine)
        assert machine is not None
        self.assertEqual("Engel", machine.manufacturer)
        self.assertEqual("LR Mate 200iC/5C", machine.robot_model)

    def test_machine_summary_uses_direct_lookup(self) -> None:
        issue = self.repository.log_issue(
            machine_number="DEMO-101",
            logged_by="Alex",
            title="Line stopped",
            description="Robot fault stopped the cell.",
            severity=LINE_DOWN,
            category="Automation",
        )

        with patch.object(self.repository, "list_machines_with_status", side_effect=AssertionError):
            summary = self.repository.get_machine_summary(issue.machine_number)

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual("DEMO-101", summary.machine_number)
        self.assertEqual(LINE_DOWN, summary.calculated_status)
        self.assertEqual(1, summary.open_issue_count)

    def test_recent_resolved_history_clamps_missing_limit_by_default(self) -> None:
        with patch.object(self.repository, "list_resolved_issues", return_value=[]) as list_resolved:
            self.repository.list_recent_resolved_issues("DEMO-101", limit=None)

        list_resolved.assert_called_once_with("DEMO-101", limit=50)

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

        next_page = self.repository.list_resolved_issues("DEMO-101", sort_key="date_desc", limit=1, offset=2)
        self.assertEqual([first.id], [issue.id for issue in next_page])
        self.assertEqual(3, self.repository.count_total_resolved_issues("DEMO-101"))
        self.assertEqual(2, self.repository.count_resolved_issues_matching("DEMO-101", "heater band"))

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
