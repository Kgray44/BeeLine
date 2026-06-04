from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FUTURE_APP = ROOT / "app_future"


class AppFutureFeatureTests(unittest.TestCase):
    def run_future_python(self, code: str, *, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(FUTURE_APP)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-c", textwrap.dedent(code)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_future_repository_feature_queries(self) -> None:
        code = """
        from pathlib import Path
        import tempfile

        from beeline_issue_tracker.data.database import initialize_database
        from beeline_issue_tracker.data.repository import IssueRepository
        from beeline_issue_tracker.domain import LINE_DOWN, NON_CRITICAL

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "future.sqlite"
            initialize_database(
                db_path,
                (
                    ("M1", "Press 1", "Molding", "Cell A", "Asset-1", 10, "", "", "", "", "", "", 1),
                    ("M2", "Press 2", "Molding", "Cell B", "Asset-2", 20, "", "", "", "", "", "", 1),
                ),
            )
            repo = IssueRepository(db_path)

            first = repo.log_issue(
                machine_number="M1",
                logged_by="Tech",
                title="Nozzle leak",
                description="Material leaking around nozzle",
                severity=NON_CRITICAL,
                category="Machine",
                created_at="2026-06-04T08:00:00+00:00",
            )
            repo.resolve_issue(first.id, solution="Tightened nozzle clamp", resolved_by="Tech")
            second = repo.log_issue(
                machine_number="M1",
                logged_by="Tech",
                title="Nozzle leak",
                description="Nozzle leaking again",
                severity=NON_CRITICAL,
                category="Machine",
                created_at="2026-06-04T09:00:00+00:00",
            )
            repo.resolve_issue(second.id, solution="Tightened nozzle clamp", resolved_by="Tech")

            active = repo.log_issue(
                machine_number="M1",
                logged_by="Operator",
                title="Nozzle leak",
                description="Leak returned during startup",
                severity=LINE_DOWN,
                category="Machine",
                what_changed="New mold installed",
                tried_already="Cycled power",
                created_at="2026-06-04T10:00:00+00:00",
            )
            assert active.what_changed == "New mold installed"
            assert active.tried_already == "Cycled power"

            priority = repo.list_priority_issues(limit=50)
            assert priority
            assert priority[0].issue.id == active.id
            assert priority[0].priority in {"P1", "P2"}

            suggestions = repo.find_intake_suggestions(machine_number="M1", query="nozzle leak", limit=5)
            assert suggestions
            assert suggestions[0].solution_preview

            fixes = repo.list_known_fixes("M1", limit=10)
            assert fixes
            assert fixes[0].times_seen >= 2

            resolved = repo.resolve_issue(active.id, solution="Replaced nozzle seal", resolved_by="Tech")
            assert resolved.what_changed == "New mold installed"
            assert resolved.tried_already == "Cycled power"

            handoff = repo.build_shift_handoff_summary("2026-06-04T00:00:00+00:00", "2999-01-01T00:00:00+00:00")
            assert handoff.resolved
            assert handoff.archive_pending_count >= 1
        """
        result = self.run_future_python(code)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_future_launcher_check_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            env = {
                "BEELINE_ROOT_DIR": str(temp_root),
                "BEELINE_TEMPLATE_DIR": str(ROOT / "templates"),
                "BEELINE_CONFIG_DIR": str(temp_root / "config"),
                "BEELINE_DATA_DIR": str(temp_root / "data"),
                "BEELINE_ARCHIVE_DIR": str(temp_root / "archive"),
                "BEELINE_LOG_DIR": str(temp_root / "logs"),
                "BEELINE_BACKUP_DIR": str(temp_root / "backups"),
                "BEELINE_PI_MODE": "1",
            }
            result = subprocess.run(
                [sys.executable, "run_beeline_future.py", "--check"],
                cwd=ROOT,
                env={**os.environ.copy(), **env},
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("BeeLine Future Issue Tracker: database ready", result.stdout)


if __name__ == "__main__":
    unittest.main()
