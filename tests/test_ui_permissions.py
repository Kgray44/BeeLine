from __future__ import annotations

import os
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

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.data.database import initialize_database
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.domain import NON_CRITICAL
from beeline_issue_tracker.ui.main_window import MainWindow
from beeline_issue_tracker.ui.theme import ThemeManager


DEMO_MACHINES = (
    ("DEMO-101", "Demo Molder 101", "Demo Hive", "Cell A", "DEMO-ASSET-101", 10),
)


class UiPermissionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.paths = _paths(self.root)
        self.paths.ensure_directories()
        initialize_database(self.paths.db_path, DEMO_MACHINES)
        self.repository = IssueRepository(self.paths.db_path)
        self.machine_number = self.repository.list_machines_with_status()[0].machine_number
        settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.window = MainWindow(self.repository, self.paths, ThemeManager(settings))
        self.window.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.close()
        self.tmp.cleanup()

    def test_all_roles_can_open_and_submit_new_issue(self) -> None:
        roles = ("viewer", "basic", "operator", "technician", "admin")
        for role in roles:
            with self.subTest(role=role):
                title = f"{role} reported issue"
                self.window.current_role = role
                self.window._apply_role_ui()
                self.window.show_machine(self.machine_number)
                self.app.processEvents()

                log_button = self.window.machine_cell.active_list.toolbar.log_button
                self.assertIsNotNone(log_button)
                assert log_button is not None
                self.assertTrue(log_button.isVisibleTo(self.window))
                self.assertTrue(log_button.isEnabled())

                log_button.click()
                self.app.processEvents()
                self.assertIs(self.window.stack.currentWidget(), self.window.log_issue_page)

                self.window.save_log_issue(
                    {
                        "machine_number": self.machine_number,
                        "logged_by": f"{role} user",
                        "title": title,
                        "description": "Submitted through the UI permission path.",
                        "severity": NON_CRITICAL,
                        "category": "Machine",
                    }
                )
                self.app.processEvents()

                titles = [issue.title for issue in self.repository.list_active_issues(self.machine_number, limit=None)]
                self.assertIn(title, titles)
                self.assertIs(self.window.stack.currentWidget(), self.window.machine_cell)

    def test_non_privileged_roles_still_cannot_use_restricted_actions(self) -> None:
        issue = self.repository.log_issue(
            machine_number=self.machine_number,
            logged_by="Test Operator",
            title="Resolve should stay restricted",
            description="Viewer should not be able to resolve this.",
            severity=NON_CRITICAL,
            category="Machine",
        )
        for role in ("viewer", "basic", "operator"):
            with self.subTest(role=role):
                self.window.current_role = role
                self.window._apply_role_ui()
                with patch("beeline_issue_tracker.ui.main_window.QMessageBox.warning") as warning:
                    self.window.open_resolve_issue(issue.id)
                warning.assert_called()
                self.assertIsNotNone(self.repository.get_active_issue(issue.id))

                with patch("beeline_issue_tracker.ui.main_window.QMessageBox.warning") as warning:
                    self.window.show_settings()
                warning.assert_called()
                self.assertIsNot(self.window.stack.currentWidget(), self.window.settings_page)

                with (
                    patch("beeline_issue_tracker.ui.main_window.QMessageBox.warning") as warning,
                    patch.object(self.window.predictive_service, "dismiss_alert") as dismiss_alert,
                ):
                    self.window.dismiss_predictive_alert(123)
                warning.assert_called()
                dismiss_alert.assert_not_called()


def _paths(root: Path) -> AppPaths:
    return AppPaths(
        root_dir=root,
        template_dir=root / "templates",
        config_dir=root / "config",
        data_dir=root,
        archive_dir=root / "archive",
        logs_dir=root / "logs",
        backups_dir=root / "backups",
        attachments_dir=root / "data" / "attachments",
        branding_dir=root / "assets" / "branding",
        config_template_path=root / "templates" / "beeline_config.template.json",
        db_template_path=root / "templates" / "beeline.template.sqlite",
        archive_template_path=root / "templates" / "beeline_archive.template.xlsx",
        runtime_config_path=root / "config" / "beeline_config.json",
        db_path=root / "beeline.sqlite3",
        archive_path=root / ".archive" / "beeline_resolved_archive.xlsx",
        approved_logo_path=root / "assets" / "branding" / "nolato_logo.png",
        approved_logo_jpg_path=root / "assets" / "branding" / "nolato_logo.jpg",
        placeholder_logo_path=root / "assets" / "branding" / "nolato_logo_placeholder.png",
        placeholder_logo_jpg_path=root / "assets" / "branding" / "nolato_logo_placeholder.jpg",
    )


if __name__ == "__main__":
    unittest.main()
