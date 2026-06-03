from __future__ import annotations

"""Main BeeLine window and stacked-page navigation."""

import logging
import os

from PySide6.QtCore import QEasingCurve, QPoint, QParallelAnimationGroup, QPropertyAnimation, QThreadPool
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
)

from beeline_issue_tracker.analytics.predictive_service import PredictiveMaintenanceService
from beeline_issue_tracker.config import AppPaths, RuntimeConfig
from beeline_issue_tracker.data.archive_worker import ArchiveIssueTask, ArchiveRetryTask
from beeline_issue_tracker.data.analytics_repository import AnalyticsRepository
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.domain import display_issue_id
from beeline_issue_tracker.permissions import (
    can_create_issue,
    can_dismiss_predictive_alert,
    can_open_settings,
    can_resolve_issue,
)
from beeline_issue_tracker.ui.dashboard import HiveDashboardPage
from beeline_issue_tracker.ui.dialogs import LoginDialog, PinDialog, ResolveIssueDialog
from beeline_issue_tracker.ui.issue_detail_page import IssueDetailPage
from beeline_issue_tracker.ui.log_issue_page import LogIssuePage
from beeline_issue_tracker.ui.machine_cell import MachineCellPage
from beeline_issue_tracker.ui.machine_details_page import MachineDetailsPage
from beeline_issue_tracker.ui.open_issues import OpenIssuesPage
from beeline_issue_tracker.ui.predictive_maintenance_page import PredictiveMaintenancePage
from beeline_issue_tracker.ui.settings_page import SettingsPage
from beeline_issue_tracker.ui.theme import ThemeManager


logger = logging.getLogger(__name__)


class FadeStackedWidget(QStackedWidget):
    """Shared page transition shell for every internal BeeLine page."""

    ENTRY_DURATION_MS = 280
    EXIT_DURATION_MS = 180
    ENTRY_OFFSET_PX = 18
    EXIT_OFFSET_PX = -10
    REDUCED_MOTION_ENV = "BEELINE_REDUCED_MOTION"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._animation: QParallelAnimationGroup | None = None
        self._entry_effect: QGraphicsOpacityEffect | None = None
        self._exit_effect: QGraphicsOpacityEffect | None = None
        self._animated_widget = None
        self._animated_target_pos: QPoint | None = None
        self._exit_overlay: QLabel | None = None

    def set_current_widget_animated(self, widget) -> None:
        if self.currentWidget() == widget:
            return
        self._clear_animation()

        if self._reduced_motion_enabled():
            self.setCurrentWidget(widget)
            return

        # Snapshot the outgoing page so navigation remains immediate while the old page exits visually.
        exit_overlay = self._create_exit_overlay(self.currentWidget())
        self.setCurrentWidget(widget)
        start_pos = widget.pos()
        self._entry_effect = QGraphicsOpacityEffect(widget)
        self._entry_effect.setOpacity(0.0)
        widget.setGraphicsEffect(self._entry_effect)
        widget.move(start_pos + QPoint(0, self.ENTRY_OFFSET_PX))
        self._animated_widget = widget
        self._animated_target_pos = start_pos
        self._exit_overlay = exit_overlay

        fade = QPropertyAnimation(self._entry_effect, b"opacity", self)
        fade.setDuration(self.ENTRY_DURATION_MS)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        slide = QPropertyAnimation(widget, b"pos", self)
        slide.setDuration(self.ENTRY_DURATION_MS)
        slide.setStartValue(start_pos + QPoint(0, self.ENTRY_OFFSET_PX))
        slide.setEndValue(start_pos)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._animation = QParallelAnimationGroup(self)
        self._animation.addAnimation(fade)
        self._animation.addAnimation(slide)

        if exit_overlay is not None:
            self._exit_effect = QGraphicsOpacityEffect(exit_overlay)
            self._exit_effect.setOpacity(1.0)
            exit_overlay.setGraphicsEffect(self._exit_effect)

            exit_fade = QPropertyAnimation(self._exit_effect, b"opacity", self)
            exit_fade.setDuration(self.EXIT_DURATION_MS)
            exit_fade.setStartValue(1.0)
            exit_fade.setEndValue(0.0)
            exit_fade.setEasingCurve(QEasingCurve.Type.InCubic)

            exit_start = exit_overlay.pos()
            exit_slide = QPropertyAnimation(exit_overlay, b"pos", self)
            exit_slide.setDuration(self.EXIT_DURATION_MS)
            exit_slide.setStartValue(exit_start)
            exit_slide.setEndValue(exit_start + QPoint(0, self.EXIT_OFFSET_PX))
            exit_slide.setEasingCurve(QEasingCurve.Type.InCubic)

            self._animation.addAnimation(exit_fade)
            self._animation.addAnimation(exit_slide)

        self._animation.finished.connect(lambda: self._finish_animation(widget, start_pos, exit_overlay))
        self._animation.start()

    def _finish_animation(self, widget, final_pos=None, exit_overlay: QLabel | None = None) -> None:
        if final_pos is not None:
            widget.move(final_pos)
        widget.setGraphicsEffect(None)
        if exit_overlay is not None:
            exit_overlay.setGraphicsEffect(None)
            exit_overlay.deleteLater()
        self._entry_effect = None
        self._exit_effect = None
        self._animation = None
        self._animated_widget = None
        self._animated_target_pos = None
        self._exit_overlay = None

    def _clear_animation(self) -> None:
        if self._animation is not None:
            self._animation.stop()
            self._animation = None
        if self._animated_widget is not None:
            if self._animated_target_pos is not None:
                self._animated_widget.move(self._animated_target_pos)
            self._animated_widget.setGraphicsEffect(None)
        if self._exit_overlay is not None:
            self._exit_overlay.setGraphicsEffect(None)
            self._exit_overlay.deleteLater()
        current = self.currentWidget()
        if current is not None:
            current.setGraphicsEffect(None)
        self._entry_effect = None
        self._exit_effect = None
        self._animated_widget = None
        self._animated_target_pos = None
        self._exit_overlay = None

    def _create_exit_overlay(self, widget) -> QLabel | None:
        if widget is None or widget.size().isEmpty():
            return None
        pixmap = widget.grab()
        if pixmap.isNull():
            return None
        overlay = QLabel(self)
        overlay.setObjectName("pageExitOverlay")
        overlay.setPixmap(pixmap)
        overlay.setGeometry(widget.geometry())
        overlay.setScaledContents(True)
        overlay.show()
        overlay.raise_()
        return overlay

    def _reduced_motion_enabled(self) -> bool:
        env_value = os.environ.get(self.REDUCED_MOTION_ENV, "").strip().casefold()
        if env_value in {"1", "true", "yes", "on", "reduce", "reduced"}:
            return True
        if env_value in {"0", "false", "no", "off"}:
            return False

        style_hints = QApplication.styleHints()
        accessibility = style_hints.accessibility() if hasattr(style_hints, "accessibility") else None
        if accessibility is None:
            return False
        for property_name in ("reducedMotion", "reduceMotion", "prefersReducedMotion"):
            value = accessibility.property(property_name)
            if isinstance(value, bool):
                return value
        return False


class MainWindow(QMainWindow):
    def __init__(
        self,
        repository: IssueRepository,
        paths: AppPaths,
        theme_manager: ThemeManager,
        runtime_config: RuntimeConfig | None = None,
    ):
        super().__init__()
        self.repository = repository
        self.paths = paths
        self.theme_manager = theme_manager
        self.runtime_config = runtime_config or RuntimeConfig(machines=(), roles={})
        self._detail_return_context = "dashboard"
        self._machine_return_context = "dashboard"
        self._details_return_machine = ""
        self._current_detail: tuple[str, int] | None = None
        self.current_role = "viewer"
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(2)

        self.setWindowTitle("BeeLine Issue Tracker")
        self.resize(1240, 820)
        self.setMinimumSize(980, 640)

        self.stack = FadeStackedWidget()
        self.analytics_repository = AnalyticsRepository(repository.db_path)
        self.predictive_service = PredictiveMaintenanceService(
            self.analytics_repository,
            settings=self.runtime_config.analytics,
        )
        self.dashboard = HiveDashboardPage(repository, theme_manager, paths)
        self.machine_cell = MachineCellPage(repository, theme_manager, paths, self.predictive_service)
        self.machine_details_page = MachineDetailsPage(repository, theme_manager, paths, self.predictive_service)
        self.open_issues_page = OpenIssuesPage(repository, theme_manager, paths)
        self.issue_detail_page = IssueDetailPage(theme_manager, paths)
        self.log_issue_page = LogIssuePage(
            repository,
            theme_manager,
            paths,
            category_options=self.runtime_config.ui.category_options,
        )
        self.predictive_page = PredictiveMaintenancePage(self.predictive_service, theme_manager, paths)
        self.settings_page = SettingsPage(paths, self.runtime_config, theme_manager)
        self.stack.addWidget(self.dashboard)
        self.stack.addWidget(self.machine_cell)
        self.stack.addWidget(self.machine_details_page)
        self.stack.addWidget(self.open_issues_page)
        self.stack.addWidget(self.issue_detail_page)
        self.stack.addWidget(self.log_issue_page)
        self.stack.addWidget(self.predictive_page)
        self.stack.addWidget(self.settings_page)
        self.setCentralWidget(self.stack)

        self.dashboard.machine_selected.connect(self.show_machine)
        self.dashboard.issue_detail_requested.connect(
            lambda mode, issue_id: self.show_issue_detail(mode, issue_id, return_context="dashboard")
        )
        self.dashboard.open_issues_requested.connect(self.show_open_issues)
        self.dashboard.predictive_requested.connect(self.show_predictive_maintenance)
        self.machine_cell.back_requested.connect(self.return_from_machine)
        self.machine_cell.log_issue_requested.connect(self.show_log_issue)
        self.machine_cell.resolve_issue_requested.connect(self.open_resolve_issue)
        self.machine_cell.machine_details_requested.connect(self.show_machine_details)
        self.machine_cell.issue_detail_requested.connect(
            lambda issue_id, mode: self.show_issue_detail(mode, issue_id, return_context="machine")
        )
        self.machine_details_page.back_requested.connect(self.return_from_machine_details)
        self.machine_details_page.log_issue_requested.connect(self.show_log_issue)
        self.machine_details_page.resolve_issue_requested.connect(self.open_resolve_issue)
        self.machine_details_page.issue_detail_requested.connect(
            lambda issue_id, mode: self.show_issue_detail(mode, issue_id, return_context="machine_details")
        )
        self.open_issues_page.back_requested.connect(self.show_dashboard)
        self.open_issues_page.machine_requested.connect(
            lambda machine_number: self.show_machine(machine_number, return_context="open_issues")
        )
        self.open_issues_page.resolve_issue_requested.connect(self.open_resolve_issue)
        self.open_issues_page.issue_open_requested.connect(
            lambda mode, issue_id: self.show_issue_detail(mode, issue_id, return_context="open_issues")
        )
        self.issue_detail_page.back_requested.connect(self.return_from_issue_detail)
        self.issue_detail_page.machine_requested.connect(self.show_machine)
        self.issue_detail_page.resolve_requested.connect(self.open_resolve_issue)
        self.issue_detail_page.related_issue_requested.connect(
            lambda mode, issue_id: self.show_issue_detail(mode, issue_id, return_context=self._detail_return_context)
        )
        self.log_issue_page.cancel_requested.connect(self.cancel_log_issue)
        self.log_issue_page.save_requested.connect(self.save_log_issue)
        self.predictive_page.back_requested.connect(self.show_dashboard)
        self.predictive_page.machine_requested.connect(
            lambda machine_number: self.show_machine(machine_number, return_context="predictive")
        )
        self.predictive_page.dismiss_alert_requested.connect(self.dismiss_predictive_alert)
        self.settings_page.back_requested.connect(self.show_dashboard)
        self.settings_page.logout_requested.connect(self.logout)
        self.settings_page.archive_retry_requested.connect(self.retry_failed_archive_writes)

        self.role_label = QLabel()
        self.role_label.setObjectName("roleBadge")
        self.settings_button = QPushButton("Settings")
        self.settings_button.setObjectName("loginButton")
        self.settings_button.clicked.connect(self.show_settings)
        self.login_button = QPushButton("Login")
        self.login_button.setObjectName("loginButton")
        self.login_button.clicked.connect(self.open_login_dialog)
        self.statusBar().addPermanentWidget(self.role_label)
        self.statusBar().addPermanentWidget(self.settings_button)
        self.statusBar().addPermanentWidget(self.login_button)

        self.dashboard.refresh()
        self._refresh_archive_health()
        self._apply_role_ui()
        self.statusBar().showMessage(self._ready_status_text())

    def show_dashboard(self) -> None:
        self.dashboard.refresh()
        self._current_detail = None
        self.stack.set_current_widget_animated(self.dashboard)

    def show_machine(self, machine_number: str, *, return_context: str = "dashboard") -> None:
        self._machine_return_context = return_context
        self.machine_cell.load_machine(machine_number)
        self._current_detail = None
        self.stack.set_current_widget_animated(self.machine_cell)

    def return_from_machine(self) -> None:
        if self._machine_return_context == "predictive":
            self.show_predictive_maintenance()
            return
        if self._machine_return_context == "open_issues":
            self.show_open_issues()
            return
        self.show_dashboard()

    def show_open_issues(self) -> None:
        self.open_issues_page.refresh()
        self._current_detail = None
        self.stack.set_current_widget_animated(self.open_issues_page)

    def show_predictive_maintenance(self, machine_number: str | None = None) -> None:
        self.predictive_page.refresh()
        if machine_number:
            self.predictive_page.focus_machine(machine_number)
        self._current_detail = None
        self.stack.set_current_widget_animated(self.predictive_page)

    def show_machine_details(self, machine_number: str, section: str = "overview") -> None:
        self._details_return_machine = machine_number
        self.machine_details_page.load_machine(machine_number, section)
        self._current_detail = None
        self.stack.set_current_widget_animated(self.machine_details_page)

    def return_from_machine_details(self) -> None:
        if self._details_return_machine:
            self.show_machine(self._details_return_machine)
            return
        self.show_dashboard()

    def show_log_issue(self, machine_number: str) -> None:
        if not self._authorize_create_issue():
            return
        self.log_issue_page.load_machine(machine_number)
        self._current_detail = None
        self.stack.set_current_widget_animated(self.log_issue_page)

    def cancel_log_issue(self) -> None:
        if self.log_issue_page.machine_number_value:
            self.show_machine(self.log_issue_page.machine_number_value)
        else:
            self.show_dashboard()

    def save_log_issue(self, values: dict[str, str]) -> None:
        if not self._authorize_create_issue():
            return
        try:
            issue = self.repository.log_issue(**values)
        except Exception as exc:
            QMessageBox.critical(self, "Could not log issue", str(exc))
            return

        machine_number = values["machine_number"]
        self.statusBar().showMessage(f"Issue {display_issue_id(issue)} logged for machine {machine_number}", 5000)
        self.show_machine(machine_number)
        self.dashboard.refresh()
        self.open_issues_page.refresh()

    def show_issue_detail(self, mode: str, issue_id: int, *, return_context: str = "machine") -> None:
        if mode == "resolved":
            self.show_resolved_issue_detail(issue_id, return_context=return_context)
            return
        self.show_active_issue_detail(issue_id, return_context=return_context)

    def show_active_issue_detail(self, issue_id: int, return_context: str = "machine") -> None:
        context = self.repository.get_issue_with_machine_context(issue_id)
        if context is None:
            QMessageBox.information(self, "Issue not found", "This active issue is no longer available.")
            self._return_to_context(return_context)
            return
        related = self.repository.find_related_resolved_issues(context.issue)
        related_matches = self.predictive_service.get_related_issues_for_active_issue(context.issue.id)
        fix_suggestions = self.predictive_service.get_fix_suggestions_for_active_issue(context.issue.id)
        trend = self.repository.get_machine_issue_trend_summary(context.issue.machine_number)
        attachments = self.repository.list_attachments_for_issue(issue_id=context.issue.id)
        self.issue_detail_page.load_active(
            context,
            related_issues=related,
            related_matches=related_matches,
            fix_suggestions=fix_suggestions,
            trend_summary=trend,
            attachments=attachments,
        )
        self._detail_return_context = return_context
        self._current_detail = ("active", issue_id)
        self.stack.set_current_widget_animated(self.issue_detail_page)

    def show_resolved_issue_detail(self, resolved_issue_id: int, return_context: str = "machine") -> None:
        context = self.repository.get_resolved_issue_with_machine_context(resolved_issue_id)
        if context is None:
            QMessageBox.information(self, "Issue not found", "This resolved issue is no longer available.")
            self._return_to_context(return_context)
            return
        trend = self.repository.get_machine_issue_trend_summary(context.issue.machine_number)
        related_matches = self.predictive_service.get_related_issues_for_resolved_issue(context.issue.id)
        recurring_patterns = self.predictive_service.get_recurring_patterns(context.issue.machine_number)
        attachments = self.repository.list_attachments_for_issue(resolved_issue_id=context.issue.id)
        self.issue_detail_page.load_resolved(
            context,
            trend_summary=trend,
            attachments=attachments,
            related_matches=related_matches,
            recurring_patterns=recurring_patterns,
        )
        self._detail_return_context = return_context
        self._current_detail = ("resolved", resolved_issue_id)
        self.stack.set_current_widget_animated(self.issue_detail_page)

    def return_from_issue_detail(self) -> None:
        self._return_to_context(self._detail_return_context)

    def _return_to_context(self, return_context: str) -> None:
        if return_context == "open_issues":
            self.show_open_issues()
            return
        if return_context == "machine_details" and self.machine_details_page.machine_number:
            self.show_machine_details(self.machine_details_page.machine_number, "history")
            return
        if return_context == "machine" and self.machine_cell.machine_number:
            self.show_machine(self.machine_cell.machine_number)
            return
        self.show_dashboard()

    def open_resolve_issue(self, issue_id: int) -> None:
        issue = self.repository.get_active_issue(issue_id)
        if issue is None:
            QMessageBox.information(self, "Already resolved", "This issue is no longer active.")
            self.refresh_current_views()
            return

        if not self._authorize_resolve():
            return

        dialog = ResolveIssueDialog(issue.title, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        values = dialog.values()
        try:
            resolved = self.repository.resolve_issue(
                issue_id,
                solution=values["solution"],
                resolved_by=values["resolved_by"],
            )
        except Exception as exc:
            QMessageBox.critical(self, "Could not resolve issue", str(exc))
            return

        detail_return = self._detail_return_context
        resolving_from_detail = self.stack.currentWidget() == self.issue_detail_page
        logger.info("Queueing resolved issue %s for Excel archive at %s", display_issue_id(resolved), self.paths.archive_path)
        self.statusBar().showMessage(f"Issue {display_issue_id(resolved)} resolved. Excel archive queued.", 5000)
        if resolving_from_detail:
            self.show_resolved_issue_detail(resolved.id, return_context=detail_return)
        else:
            self.refresh_current_views()

        cache = self.runtime_config.archive_cache
        task = ArchiveIssueTask(
            self.paths.archive_path,
            self.repository,
            resolved,
            cache_keep_days=cache.keep_days,
            cache_keep_minimum=cache.keep_minimum,
            cache_keep_per_machine_minimum=cache.keep_per_machine_minimum,
        )
        task.signals.finished.connect(self.on_archive_finished)
        self.thread_pool.start(task)

    def _authorize_resolve(self) -> bool:
        if can_resolve_issue(self.current_role):
            return True
        QMessageBox.warning(self, "Login required", "Resolve requires technician or admin PIN.")
        return False

    def _authorize_create_issue(self) -> bool:
        if can_create_issue(self.current_role):
            return True
        QMessageBox.warning(self, "Cannot create issue", "Cannot create issue for the current user.")
        return False

    def _authorize_pin_for_technician_or_admin(self, prompt: str) -> bool:
        if not self.runtime_config.resolve_requires_pin():
            return True
        dialog = PinDialog(prompt, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return False
        if self.runtime_config.verify_pin_for_roles(dialog.value(), ("technician", "admin")):
            return True
        QMessageBox.warning(self, "PIN rejected", "That PIN is not authorized for this action.")
        return False

    def dismiss_predictive_alert(self, alert_id: int) -> None:
        if not can_dismiss_predictive_alert(self.current_role):
            QMessageBox.warning(self, "Login required", "Dismiss alert requires technician or admin PIN.")
            return
        self.predictive_service.dismiss_alert(alert_id)
        self.predictive_page.refresh()
        self.statusBar().showMessage(f"Predictive alert {alert_id} dismissed locally.", 5000)

    def refresh_current_views(self) -> None:
        self.dashboard.refresh()
        self.machine_cell.refresh()
        if self.machine_details_page.machine_number:
            self.machine_details_page.load_machine(self.machine_details_page.machine_number, "overview")
        self.open_issues_page.refresh()
        self.predictive_page.refresh()

    def on_archive_finished(self, resolved_issue_id: int, success: bool, message: str) -> None:
        resolved = self.repository.get_resolved_issue(resolved_issue_id)
        label = display_issue_id(resolved) if resolved is not None else str(resolved_issue_id)
        if success:
            self.statusBar().showMessage(f"Resolved issue {label} archived. {message}", 7000)
        else:
            self.statusBar().showMessage(f"Archive failed for issue {label}: {message}", 8000)
        self.machine_cell.refresh()
        self.open_issues_page.refresh()
        if self.stack.currentWidget() == self.issue_detail_page and self._current_detail == ("resolved", resolved_issue_id):
            self.show_resolved_issue_detail(resolved_issue_id, return_context=self._detail_return_context)
        self._refresh_archive_health()

    def retry_failed_archive_writes(self) -> None:
        cache = self.runtime_config.archive_cache
        task = ArchiveRetryTask(
            self.paths.archive_path,
            self.repository,
            cache_keep_days=cache.keep_days,
            cache_keep_minimum=cache.keep_minimum,
            cache_keep_per_machine_minimum=cache.keep_per_machine_minimum,
        )
        task.signals.finished.connect(self.on_archive_retry_finished)
        self.statusBar().showMessage("Retrying failed archive writes...", 5000)
        self.thread_pool.start(task)

    def on_archive_retry_finished(self, success_count: int, failed_count: int, message: str) -> None:
        self.statusBar().showMessage(message, 8000)
        self._refresh_archive_health()
        if success_count or failed_count:
            self.refresh_current_views()

    def open_login_dialog(self) -> None:
        if self.current_role != "viewer":
            self.logout()
            return
        dialog = LoginDialog(self.runtime_config, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self.current_role = dialog.selected_role()
        self._apply_role_ui()
        self.statusBar().showMessage(f"Logged in as {self._role_label_text()}", 4000)

    def logout(self) -> None:
        self.current_role = "viewer"
        self._apply_role_ui()
        self.show_dashboard()
        self.statusBar().showMessage("Logged out. Viewer access active.", 4000)

    def show_settings(self) -> None:
        if not can_open_settings(self.current_role):
            QMessageBox.warning(self, "Admin required", "Settings are available after Admin login.")
            return
        self._refresh_archive_health()
        self._current_detail = None
        self.stack.set_current_widget_animated(self.settings_page)

    def _apply_role_ui(self) -> None:
        self.role_label.setText(f"Role: {self._role_label_text()}")
        self.login_button.setText("Logout" if self.current_role != "viewer" else "Login")
        self.settings_button.setVisible(can_open_settings(self.current_role))
        self.machine_cell.set_can_report(can_create_issue(self.current_role))
        self.machine_details_page.set_can_report(can_create_issue(self.current_role))

    def _role_label_text(self) -> str:
        return {
            "admin": "Admin",
            "technician": "Technician",
            "viewer": "Viewer",
        }.get(self.current_role, "Viewer")

    def _ready_status_text(self) -> str:
        connected = self.paths.archive_path.exists()
        return f"Ready | Excel archive {'connected' if connected else 'not connected'}"

    def _refresh_archive_health(self) -> None:
        self.settings_page.set_archive_health(self.repository.archive_status_counts())
