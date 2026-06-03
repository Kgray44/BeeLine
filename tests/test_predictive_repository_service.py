from __future__ import annotations

"""Integration tests for predictive analytics repository and service behavior."""

from datetime import datetime, timedelta, timezone
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

from beeline_issue_tracker.analytics.predictive_service import PredictiveMaintenanceService
from beeline_issue_tracker.data.analytics_repository import AnalyticsRepository
from beeline_issue_tracker.data.database import initialize_database
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.domain import LINE_DOWN, NON_CRITICAL


DEMO_MACHINES = (
    ("DEMO-101", "Demo Molder 101", "Demo Hive", "Cell A", "DEMO-ASSET-101", 10),
    ("DEMO-202", "Demo Press 202", "Demo Hive", "Cell B", "DEMO-ASSET-202", 20),
)


class PredictiveRepositoryServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "beeline.sqlite3"
        initialize_database(self.db_path, DEMO_MACHINES)
        self.issue_repository = IssueRepository(self.db_path)
        self.analytics_repository = AnalyticsRepository(self.db_path)
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.service = PredictiveMaintenanceService(self.analytics_repository, now_provider=lambda: self.now)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_empty_database_analytics_methods_are_graceful(self) -> None:
        self.assertEqual({}, self.analytics_repository.get_category_counts())
        self.assertEqual({}, self.analytics_repository.get_severity_counts())
        self.assertEqual([], self.analytics_repository.get_resolution_time_samples())
        self.assertEqual(2, len(self.analytics_repository.get_all_machine_risk_inputs()))

    def test_repository_counts_breakdowns_and_resolution_samples(self) -> None:
        self._log_active("DEMO-101", "Sensor drift", NON_CRITICAL, "Sensor", self.now - timedelta(days=1))
        self._resolve(
            "DEMO-101",
            "Guard switch open",
            LINE_DOWN,
            "Safety",
            self.now - timedelta(days=2, hours=2),
            self.now - timedelta(days=2),
            "Closed guard and verified switch.",
        )

        counts = self.analytics_repository.get_machine_activity_counts("DEMO-101", days=30)
        self.assertEqual(2, counts["total"])
        self.assertEqual(1, counts["active"])
        self.assertEqual(1, counts["resolved"])
        self.assertEqual({"Sensor": 1, "Safety": 1}, self.analytics_repository.get_category_counts("DEMO-101", 30))
        self.assertEqual(1, self.analytics_repository.get_line_down_counts("DEMO-101", 30))
        self.assertEqual([120], self.analytics_repository.get_resolution_time_samples("DEMO-101"))

    def test_service_sorts_risks_generates_alerts_and_trends(self) -> None:
        self._log_active("DEMO-101", "Guard switch open", LINE_DOWN, "Safety", self.now - timedelta(hours=1))
        self._log_active("DEMO-202", "Minor sensor drift", NON_CRITICAL, "Sensor", self.now - timedelta(days=1))

        risks = self.service.get_all_machine_risks()
        self.assertEqual("DEMO-101", risks[0].machine_number)
        self.assertGreaterEqual(risks[0].risk_score, risks[1].risk_score)

        alerts = self.service.get_predictive_alerts(limit=10)
        self.assertTrue(any(alert.machine_number == "DEMO-101" for alert in alerts))
        machine_trend = self.service.get_machine_trend("DEMO-101", periods=4)
        global_trend = self.service.get_global_trend(periods=4)
        self.assertEqual(4, len(machine_trend))
        self.assertEqual(4, len(global_trend))
        self.assertGreaterEqual(sum(point.open_count for point in global_trend), 1)

    def test_recurring_patterns_related_issues_and_fix_suggestions(self) -> None:
        resolved_records = []
        for offset in (2, 5, 8):
            resolved_records.append(self._resolve(
                "DEMO-101",
                "Nozzle heater drift",
                NON_CRITICAL,
                "Process",
                self.now - timedelta(days=offset, hours=1),
                self.now - timedelta(days=offset),
                "Replaced heater band.",
            ))
        active = self._log_active(
            "DEMO-101",
            "Nozzle heater drift",
            NON_CRITICAL,
            "Process",
            self.now - timedelta(hours=2),
        )

        patterns = self.service.get_recurring_patterns("DEMO-101", days=30)
        self.assertTrue(patterns)
        related = self.service.get_related_issues_for_active_issue(active.id)
        suggestions = self.service.get_fix_suggestions_for_active_issue(active.id)
        self.assertTrue(related)
        self.assertTrue(self.service.get_related_issues_for_resolved_issue(resolved_records[0].id))
        self.assertEqual("Replaced heater band.", suggestions[0].suggestion)

    def test_alerts_do_not_duplicate_and_dismissal_persists_until_risk_worsens(self) -> None:
        self._log_active("DEMO-101", "Guard switch open", LINE_DOWN, "Safety", self.now - timedelta(hours=1))
        first = self.service.get_predictive_alerts(limit=10)
        second = self.service.get_predictive_alerts(limit=10)
        self.assertEqual([alert.id for alert in first], [alert.id for alert in second])
        self.assertEqual(1, len(self.analytics_repository.list_predictive_alerts()))

        assert first[0].id is not None
        self.service.dismiss_alert(first[0].id, dismissed_by="Synthetic Tech")
        self.assertEqual([], self.service.get_predictive_alerts(limit=10))

        self._log_active("DEMO-101", "Second guard switch open", LINE_DOWN, "Safety", self.now - timedelta(minutes=30))
        worsened = self.service.get_predictive_alerts(limit=10)
        self.assertTrue(any(alert.risk_level == "Critical" for alert in worsened))

    def _log_active(
        self,
        machine_number: str,
        title: str,
        severity: str,
        category: str,
        created_at: datetime,
    ):
        issue = self.issue_repository.log_issue(
            machine_number=machine_number,
            logged_by="Synthetic Operator",
            title=title,
            description=f"{title} synthetic description",
            severity=severity,
            category=category,
        )
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE active_issues SET created_at = ?, updated_at = ? WHERE id = ?",
                (created_at.isoformat(), created_at.isoformat(), issue.id),
            )
            conn.commit()
        finally:
            conn.close()
        updated = self.issue_repository.get_active_issue(issue.id)
        assert updated is not None
        return updated

    def _resolve(
        self,
        machine_number: str,
        title: str,
        severity: str,
        category: str,
        created_at: datetime,
        resolved_at: datetime,
        solution: str,
    ):
        active = self._log_active(machine_number, title, severity, category, created_at)
        resolved = self.issue_repository.resolve_issue(
            active.id,
            solution=solution,
            resolved_by="Synthetic Tech",
        )
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                UPDATE resolved_issues_cache
                SET created_at = ?, resolved_at = ?
                WHERE id = ?
                """,
                (created_at.isoformat(), resolved_at.isoformat(), resolved.id),
            )
            conn.commit()
        finally:
            conn.close()
        updated = self.issue_repository.get_resolved_issue(resolved.id)
        assert updated is not None
        return updated


if __name__ == "__main__":
    unittest.main()
