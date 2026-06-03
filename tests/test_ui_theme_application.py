from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
import sys

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
from beeline_issue_tracker.ui.theme import DARK_THEME, LIGHT_THEME, ThemeManager


DEMO_MACHINES = (
    ("DEMO-101", "Demo Molder 101", "Demo Hive", "Cell A", "DEMO-ASSET-101", 10),
)


class UiThemeApplicationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_major_pages_accept_dark_and_light_styles_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = AppPaths(
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
                placeholder_logo_path=root / "assets" / "branding" / "nolato_logo_placeholder.png",
            )
            paths.ensure_directories()
            initialize_database(paths.db_path, DEMO_MACHINES)
            repository = IssueRepository(paths.db_path)
            machine_number = repository.list_machines_with_status()[0].machine_number
            active_issue = repository.log_issue(
                machine_number=machine_number,
                logged_by="UI Test",
                title="Sensor drift",
                description="Sensor value is drifting.",
                severity=NON_CRITICAL,
                category="Sensor",
            )
            to_resolve = repository.log_issue(
                machine_number=machine_number,
                logged_by="UI Test",
                title="Guard switch open",
                description="Guard switch is open.",
                severity=NON_CRITICAL,
                category="Safety",
            )
            resolved_issue = repository.resolve_issue(
                to_resolve.id,
                solution="Closed guard and verified switch.",
                resolved_by="UI Test",
            )
            settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
            theme_manager = ThemeManager(settings)
            window = MainWindow(repository, paths, theme_manager)

            for theme_name in (DARK_THEME, LIGHT_THEME):
                theme_manager.set_theme(theme_name)
                self.app.setStyleSheet(theme_manager.build_stylesheet())
                window.show_dashboard()
                window.show_open_issues()
                window.show_machine(machine_number)
                window.show_active_issue_detail(active_issue.id, return_context="machine")
                window.show_resolved_issue_detail(resolved_issue.id, return_context="machine")
                window.show_log_issue(machine_number)

            window.close()


if __name__ == "__main__":
    unittest.main()
