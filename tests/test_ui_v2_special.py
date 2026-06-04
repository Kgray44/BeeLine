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
os.environ.setdefault("BEELINE_REDUCED_MOTION", "1")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.data.database import initialize_database
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.ui_v2.main_window import MainWindow
from beeline_issue_tracker.ui_v2.theme import ThemeManager


DEMO_MACHINES = (
    ("DEMO-101", "Demo Molder 101", "Demo Hive", "Cell A", "DEMO-ASSET-101", 10),
)


class UiV2SpecialAccessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_special_access_pin_lock_and_force_testing_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            paths.ensure_directories()
            initialize_database(paths.db_path, DEMO_MACHINES)
            repository = IssueRepository(paths.db_path)
            settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
            window = MainWindow(repository, paths, ThemeManager(settings))
            window.show()
            self.app.processEvents()
            try:
                self.assertFalse(window.special_button.isVisibleTo(window))
                with patch("beeline_issue_tracker.ui_v2.main_window.QMessageBox.warning") as warning:
                    window.show_special()
                warning.assert_called_once()
                self.assertIsNot(window.stack.currentWidget(), window.special_page)

                window.current_role = "admin"
                window._apply_role_ui()
                self.app.processEvents()
                self.assertTrue(window.special_button.isVisibleTo(window))

                with (
                    patch("beeline_issue_tracker.ui_v2.main_window.PinDialog", lambda *_args, **_kwargs: _PinDialog("000000")),
                    patch("beeline_issue_tracker.ui_v2.main_window.QMessageBox.warning") as warning,
                ):
                    window.show_special()
                warning.assert_called_once()
                self.assertIsNot(window.stack.currentWidget(), window.special_page)

                fake = _CountingPinDialog("041924")
                with patch("beeline_issue_tracker.ui_v2.main_window.PinDialog", lambda *_args, **_kwargs: fake):
                    window.show_special()
                    self.app.processEvents()
                    self.assertIs(window.stack.currentWidget(), window.special_page)

                    window.show_dashboard(refresh=False)
                    self.app.processEvents()
                    self.assertIs(window.stack.currentWidget(), window.dashboard)

                    window.show_special()
                    self.app.processEvents()
                self.assertEqual(2, fake.exec_count)
                self.assertIs(window.stack.currentWidget(), window.special_page)

                self.assertFalse(window.dashboard.special_state.effect_active)
                window.special_page.force_test.setChecked(True)
                window.special_page.test_intensity.setValue(4)
                self.app.processEvents()
                self.assertTrue(window.dashboard.special_state.effect_active)
                self.assertEqual(4, window.dashboard.special_state.intensity_level)
            finally:
                window.close()
                self.app.processEvents()
                window.deleteLater()
                self.app.processEvents()


class _PinDialog:
    DialogCode = QDialog.DialogCode

    def __init__(self, pin: str):
        self.pin = pin

    def exec(self):
        return self.DialogCode.Accepted

    def value(self) -> str:
        return self.pin


class _CountingPinDialog(_PinDialog):
    def __init__(self, pin: str):
        super().__init__(pin)
        self.exec_count = 0

    def exec(self):
        self.exec_count += 1
        return super().exec()


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
