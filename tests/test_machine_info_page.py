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
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.data.database import initialize_database
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.ui_v2.machine_details_page import MachineDetailsPage
from beeline_issue_tracker.ui_v2.main_window import FadeStackedWidget, MainWindow
from beeline_issue_tracker.ui_v2.risk_widgets import parse_risk_reasons
from beeline_issue_tracker.ui_v2.theme import ThemeManager


DEMO_MACHINES = (
    ("DEMO-101", "Demo Molder 101", "Demo Hive", "Cell A", "DEMO-ASSET-101", 10),
)


class MachineInfoPageTest(unittest.TestCase):
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
        self.theme_manager = ThemeManager(settings)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _close_window(self, window: MainWindow) -> None:
        window.stack._clear_animation()
        window.close()
        self.app.processEvents()
        window.deleteLater()
        self.app.processEvents()

    def test_risk_reason_parser_splits_scores_and_sorts_by_impact(self) -> None:
        reasons = parse_risk_reasons(
            "1 open Line Down issue(s): +35 | "
            "2 issue(s) in the last 30 days: +6 | "
            "Line Down occurred in the last 14 days: +12 | "
            "No issues in the last 60 days: -15 | "
            "Multiple open Line Down issues raise risk floor to Critical."
        )

        self.assertEqual(35, reasons[0].impact)
        self.assertEqual("1 open Line Down issue(s)", reasons[0].text)
        self.assertEqual(12, reasons[1].impact)
        self.assertEqual("Line Down occurred in the last 14 days", reasons[1].text)
        self.assertEqual(6, reasons[2].impact)
        self.assertEqual(-15, reasons[3].impact)
        self.assertIsNone(reasons[4].impact)

    def test_machine_cell_has_one_machine_info_button_that_opens_details(self) -> None:
        window = MainWindow(self.repository, self.paths, self.theme_manager)
        window.show()
        self.app.processEvents()
        window.show_machine(self.machine_number)
        self.app.processEvents()

        button_texts = [button.text() for button in window.machine_cell.findChildren(QPushButton)]
        self.assertEqual(1, button_texts.count("Machine Info"))
        self.assertNotIn("View Predictive Details", button_texts)
        self.assertNotIn("View Trends", button_texts)
        self.assertNotIn("View Related History", button_texts)

        info_button = next(button for button in window.machine_cell.findChildren(QPushButton) if button.text() == "Machine Info")
        info_button.click()
        self.app.processEvents()

        self.assertIs(window.stack.currentWidget(), window.machine_details_page)
        self.assertEqual("Machine Info", window.machine_details_page.brand_header.title_label.text())
        self.assertIn(f"Machine {self.machine_number}", window.machine_details_page.brand_header.subtitle_label.text())
        self._close_window(window)

    def test_machine_click_switches_before_repository_load(self) -> None:
        window = MainWindow(self.repository, self.paths, self.theme_manager)
        window.show()
        self.app.processEvents()

        with (
            patch.object(self.repository, "get_machine_summary", side_effect=AssertionError("machine loaded before navigation")),
            patch("beeline_issue_tracker.ui_v2.main_window.QTimer.singleShot") as single_shot,
        ):
            window.show_machine(self.machine_number)

        self.assertIs(window.stack.currentWidget(), window.machine_cell)
        self.assertEqual(f"Machine {self.machine_number}", window.machine_cell.machine_title.text())
        self.assertEqual("Loading machine details...", window.machine_cell.machine_subtitle.text())
        single_shot.assert_called_once()
        self._close_window(window)

    def test_cancel_log_issue_does_not_refresh_or_reload(self) -> None:
        window = MainWindow(self.repository, self.paths, self.theme_manager)
        window.machine_cell.load_machine(self.machine_number)
        window.stack.setCurrentWidget(window.machine_cell)
        window.show_log_issue(self.machine_number)

        with (
            patch.object(window.dashboard, "refresh") as dashboard_refresh,
            patch.object(window.machine_cell, "refresh") as machine_refresh,
            patch.object(window.open_issues_page, "refresh") as open_refresh,
        ):
            window.cancel_log_issue()

        dashboard_refresh.assert_not_called()
        machine_refresh.assert_not_called()
        open_refresh.assert_not_called()
        self.assertIs(window.stack.currentWidget(), window.machine_cell)
        self._close_window(window)

    def test_dashboard_refresh_is_deferred_until_after_navigation(self) -> None:
        window = MainWindow(self.repository, self.paths, self.theme_manager)
        window.stack.setCurrentWidget(window.machine_cell)

        with patch.object(window.dashboard, "refresh") as dashboard_refresh:
            window.show_dashboard(reason="test_return")

        dashboard_refresh.assert_not_called()
        self.assertTrue(window._dashboard_refresh_deferred)
        self.assertIs(window.stack.currentWidget(), window.dashboard)
        self._close_window(window)

    def test_open_issues_navigation_switches_before_repository_load(self) -> None:
        window = MainWindow(self.repository, self.paths, self.theme_manager)
        with (
            patch.object(self.repository, "list_machines_with_status", side_effect=AssertionError("open issues loaded before navigation")),
            patch("beeline_issue_tracker.ui_v2.main_window.QTimer.singleShot") as single_shot,
        ):
            window.show_open_issues()

        self.assertIs(window.stack.currentWidget(), window.open_issues_page)
        self.assertEqual("Loading open issues", window.open_issues_page.empty_panel.title_label.text())
        single_shot.assert_called_once()
        self._close_window(window)

    def test_predictive_navigation_switches_before_analytics_load(self) -> None:
        window = MainWindow(self.repository, self.paths, self.theme_manager)
        window.current_role = "admin"
        window._apply_role_ui()
        with (
            patch.object(
                window.predictive_service,
                "get_all_machine_risks",
                side_effect=AssertionError("predictive loaded before navigation"),
            ),
            patch("beeline_issue_tracker.ui_v2.main_window.QTimer.singleShot") as single_shot,
        ):
            window.show_predictive_maintenance()

        self.assertIs(window.stack.currentWidget(), window.predictive_page)
        self.assertEqual("-", window.predictive_page.open_total_pill.value_widget.text())
        single_shot.assert_called_once()
        self._close_window(window)

    def test_machine_details_navigation_switches_before_repository_load(self) -> None:
        window = MainWindow(self.repository, self.paths, self.theme_manager)
        with (
            patch.object(self.repository, "get_machine_summary", side_effect=AssertionError("details loaded before navigation")),
            patch("beeline_issue_tracker.ui_v2.main_window.QTimer.singleShot") as single_shot,
        ):
            window.show_machine_details(self.machine_number, "history")

        self.assertIs(window.stack.currentWidget(), window.machine_details_page)
        self.assertIn(f"Machine {self.machine_number}", window.machine_details_page.brand_header.subtitle_label.text())
        self.assertGreaterEqual(single_shot.call_count, 1)
        self._close_window(window)

    def test_issue_detail_navigation_switches_before_repository_load(self) -> None:
        issue = self.repository.log_issue(
            machine_number=self.machine_number,
            logged_by="Tester",
            title="Async detail load",
            description="Detail page should switch before repository work.",
            severity="Non-Critical",
            category="Machine",
        )
        window = MainWindow(self.repository, self.paths, self.theme_manager)
        with (
            patch.object(
                self.repository,
                "get_issue_with_machine_context",
                side_effect=AssertionError("issue detail loaded before navigation"),
            ),
            patch("beeline_issue_tracker.ui_v2.main_window.QTimer.singleShot") as single_shot,
        ):
            window.show_active_issue_detail(issue.id)

        self.assertIs(window.stack.currentWidget(), window.issue_detail_page)
        self.assertIn(str(issue.id), window.issue_detail_page.brand_header.subtitle_label.text())
        single_shot.assert_called_once()
        self._close_window(window)

    def test_dashboard_refresh_reuses_existing_card_layout(self) -> None:
        window = MainWindow(self.repository, self.paths, self.theme_manager)
        window.dashboard.refresh()

        with patch.object(window.dashboard, "_detach_grid_widgets", wraps=window.dashboard._detach_grid_widgets) as detach:
            window.dashboard.refresh()

        detach.assert_not_called()
        self.assertEqual(1, len(window.dashboard._machine_cards))
        self._close_window(window)

    def test_quick_search_does_not_touch_excel(self) -> None:
        window = MainWindow(self.repository, self.paths, self.theme_manager)
        window.dashboard.search.setText("anything")
        window.dashboard.search_mode.setCurrentIndex(window.dashboard.search_mode.findData("quick"))

        with patch("beeline_issue_tracker.data.archive_search.load_workbook") as load_workbook:
            window.dashboard._render_dashboard()

        load_workbook.assert_not_called()
        self._close_window(window)

    def test_machine_cell_refresh_uses_limited_direct_queries(self) -> None:
        window = MainWindow(self.repository, self.paths, self.theme_manager)
        window.machine_cell.machine_number = self.machine_number

        with (
            patch.object(
                window.predictive_service.repository.issue_repository,
                "list_machines_with_status",
                side_effect=AssertionError("machine page used global predictive scan"),
            ),
            patch.object(self.repository, "list_active_issues", wraps=self.repository.list_active_issues) as active,
            patch.object(self.repository, "list_resolved_issues", wraps=self.repository.list_resolved_issues) as resolved,
        ):
            window.machine_cell.refresh()

        for call in active.call_args_list:
            self.assertEqual(10, call.kwargs.get("limit"))
        for call in resolved.call_args_list:
            self.assertEqual(10, call.kwargs.get("limit"))
        self._close_window(window)

    def test_machine_info_handles_missing_predictive_service(self) -> None:
        page = MachineDetailsPage(self.repository, self.theme_manager, self.paths, predictive_service=None)
        page.load_machine(self.machine_number, "trends")
        self.app.processEvents()

        label_texts = [label.text() for label in page.findChildren(QLabel)]
        button_texts = [button.text() for button in page.findChildren(QPushButton)]
        self.assertNotIn("Predictive", button_texts)
        self.assertNotIn("Predictive Maintenance", label_texts)
        self.assertIn(
            "Not enough trend data yet. BeeLine will draw this graph as issues are logged.",
            label_texts,
        )

    def test_machine_info_does_not_load_unbounded_issue_history(self) -> None:
        page = MachineDetailsPage(self.repository, self.theme_manager, self.paths, predictive_service=None)
        with (
            patch.object(self.repository, "list_active_issues", wraps=self.repository.list_active_issues) as active,
            patch.object(self.repository, "list_resolved_issues", wraps=self.repository.list_resolved_issues) as resolved,
        ):
            page.load_machine(self.machine_number, "history")
            self.app.processEvents()

        for call in active.call_args_list:
            self.assertIsNotNone(call.kwargs.get("limit"))
        for call in resolved.call_args_list:
            self.assertIsNotNone(call.kwargs.get("limit"))

    def test_shared_page_transition_is_stronger_and_immediate(self) -> None:
        with patch.dict(os.environ, {FadeStackedWidget.REDUCED_MOTION_ENV: "0"}):
            stack = FadeStackedWidget()
            first = QLabel("Home")
            second = QLabel("Machine")
            stack.addWidget(first)
            stack.addWidget(second)
            stack.resize(480, 320)
            stack.show()
            self.app.processEvents()

            stack.set_current_widget_animated(second)
            self.app.processEvents()

            self.assertIs(stack.currentWidget(), second)
            self.assertEqual(280, stack.ENTRY_DURATION_MS)
            self.assertEqual(180, stack.EXIT_DURATION_MS)
            self.assertEqual(18, stack.ENTRY_OFFSET_PX)
            self.assertIsNotNone(stack._animation)
            self.assertIsNotNone(stack._entry_effect)
            stack._clear_animation()
            stack.close()
            self.app.processEvents()
            stack.deleteLater()
            self.app.processEvents()

    def test_reduced_motion_disables_page_transition(self) -> None:
        with patch.dict(os.environ, {FadeStackedWidget.REDUCED_MOTION_ENV: "1"}):
            stack = FadeStackedWidget()
            first = QLabel("Home")
            second = QLabel("Settings")
            stack.addWidget(first)
            stack.addWidget(second)

            stack.set_current_widget_animated(second)

            self.assertIs(stack.currentWidget(), second)
            self.assertIsNone(stack._animation)
            self.assertIsNone(second.graphicsEffect())


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
