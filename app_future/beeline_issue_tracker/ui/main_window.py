from __future__ import annotations

"""Main BeeLine window and stacked-page navigation."""

import logging
import os

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QRunnable,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
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
from beeline_issue_tracker.perf import elapsed_ms, log as perf_log, now as perf_now
from beeline_issue_tracker.permissions import (
    can_create_issue,
    can_dismiss_predictive_alert,
    can_open_predictive_maintenance,
    can_open_settings,
    can_resolve_issue,
)
from beeline_issue_tracker.ui.dashboard import HiveDashboardPage
from beeline_issue_tracker.ui.dialogs import LoginDialog, PinDialog, ResolveIssueDialog
from beeline_issue_tracker.ui.issue_detail_page import IssueDetailPage
from beeline_issue_tracker.ui.log_issue_page import LogIssuePage
from beeline_issue_tracker.ui.machine_cell import MachineCellPage, MachineCellQuery, load_machine_cell_snapshot
from beeline_issue_tracker.ui.machine_details_page import MachineDetailsPage, load_machine_details_snapshot
from beeline_issue_tracker.ui.open_issues import OpenIssuesPage, load_open_issues_snapshot
from beeline_issue_tracker.ui.predictive_maintenance_page import (
    PredictiveMaintenancePage,
    load_predictive_page_snapshot,
)
from beeline_issue_tracker.ui.settings_page import SettingsPage
from beeline_issue_tracker.ui.theme import ThemeManager


logger = logging.getLogger(__name__)


def _safe_emit(signal, *args) -> None:
    try:
        signal.emit(*args)
    except RuntimeError:
        pass


class MachineLoadSignals(QObject):
    finished = Signal(int, object)
    failed = Signal(int, str, str)


class MachineLoadTask(QRunnable):
    def __init__(
        self,
        request_id: int,
        repository: IssueRepository,
        predictive_service: PredictiveMaintenanceService | None,
        machine_number: str,
        criteria: MachineCellQuery,
    ):
        super().__init__()
        self.request_id = request_id
        self.repository = repository
        self.predictive_service = predictive_service
        self.machine_number = machine_number
        self.criteria = criteria
        self.signals = MachineLoadSignals()

    @Slot()
    def run(self) -> None:
        started_at = perf_now()
        try:
            snapshot = load_machine_cell_snapshot(
                self.repository,
                self.predictive_service,
                self.machine_number,
                self.criteria,
            )
        except Exception as exc:
            logger.exception("Could not load machine %s", self.machine_number)
            _safe_emit(self.signals.failed, self.request_id, self.machine_number, str(exc))
            return
        perf_log("machine.load_task", machine=self.machine_number, elapsed_ms=elapsed_ms(started_at))
        _safe_emit(self.signals.finished, self.request_id, snapshot)


class OpenIssuesLoadTask(QRunnable):
    def __init__(self, request_id: int, repository: IssueRepository, query: dict[str, object]):
        super().__init__()
        self.request_id = request_id
        self.repository = repository
        self.query = query
        self.signals = MachineLoadSignals()

    @Slot()
    def run(self) -> None:
        try:
            snapshot = load_open_issues_snapshot(self.repository, **self.query)
        except Exception as exc:
            logger.exception("Could not load open issues")
            _safe_emit(self.signals.failed, self.request_id, "open_issues", str(exc))
            return
        _safe_emit(self.signals.finished, self.request_id, snapshot)


class PredictiveLoadTask(QRunnable):
    def __init__(self, request_id: int, service: PredictiveMaintenanceService):
        super().__init__()
        self.request_id = request_id
        self.service = service
        self.signals = MachineLoadSignals()

    @Slot()
    def run(self) -> None:
        try:
            snapshot = load_predictive_page_snapshot(self.service)
        except Exception as exc:
            logger.exception("Could not load predictive maintenance")
            _safe_emit(self.signals.failed, self.request_id, "predictive", str(exc))
            return
        _safe_emit(self.signals.finished, self.request_id, snapshot)


class MachineDetailsLoadTask(QRunnable):
    def __init__(
        self,
        request_id: int,
        repository: IssueRepository,
        predictive_service: PredictiveMaintenanceService | None,
        machine_number: str,
        section: str,
    ):
        super().__init__()
        self.request_id = request_id
        self.repository = repository
        self.predictive_service = predictive_service
        self.machine_number = machine_number
        self.section = section
        self.signals = MachineLoadSignals()

    @Slot()
    def run(self) -> None:
        try:
            snapshot = load_machine_details_snapshot(
                self.repository,
                self.predictive_service,
                self.machine_number,
                self.section,
            )
        except Exception as exc:
            logger.exception("Could not load machine details for %s", self.machine_number)
            _safe_emit(self.signals.failed, self.request_id, self.machine_number, str(exc))
            return
        _safe_emit(self.signals.finished, self.request_id, snapshot)


class IssueDetailLoadTask(QRunnable):
    def __init__(
        self,
        request_id: int,
        repository: IssueRepository,
        predictive_service: PredictiveMaintenanceService,
        mode: str,
        issue_id: int,
        return_context: str,
    ):
        super().__init__()
        self.request_id = request_id
        self.repository = repository
        self.predictive_service = predictive_service
        self.mode = mode
        self.issue_id = issue_id
        self.return_context = return_context
        self.signals = MachineLoadSignals()

    @Slot()
    def run(self) -> None:
        started_at = perf_now()
        try:
            if self.mode == "resolved":
                context = self.repository.get_resolved_issue_with_machine_context(self.issue_id)
                if context is None:
                    snapshot = {"mode": self.mode, "issue_id": self.issue_id, "missing": True, "return_context": self.return_context}
                else:
                    snapshot = {
                        "mode": self.mode,
                        "issue_id": self.issue_id,
                        "missing": False,
                        "return_context": self.return_context,
                        "context": context,
                        "trend": self.repository.get_machine_issue_trend_summary(context.issue.machine_number),
                        "related_matches": self.predictive_service.get_related_issues_for_resolved_issue(context.issue.id),
                        "recurring_patterns": self.predictive_service.get_recurring_patterns(context.issue.machine_number),
                        "attachments": self.repository.list_attachments_for_issue(resolved_issue_id=context.issue.id),
                    }
            else:
                context = self.repository.get_issue_with_machine_context(self.issue_id)
                if context is None:
                    snapshot = {"mode": self.mode, "issue_id": self.issue_id, "missing": True, "return_context": self.return_context}
                else:
                    snapshot = {
                        "mode": self.mode,
                        "issue_id": self.issue_id,
                        "missing": False,
                        "return_context": self.return_context,
                        "context": context,
                        "related_issues": self.repository.find_related_resolved_issues(context.issue),
                        "related_matches": self.predictive_service.get_related_issues_for_active_issue(context.issue.id),
                        "fix_suggestions": self.predictive_service.get_fix_suggestions_for_active_issue(context.issue.id),
                        "trend": self.repository.get_machine_issue_trend_summary(context.issue.machine_number),
                        "attachments": self.repository.list_attachments_for_issue(issue_id=context.issue.id),
                    }
        except Exception as exc:
            logger.exception("Could not load %s issue detail %s", self.mode, self.issue_id)
            _safe_emit(self.signals.failed, self.request_id, f"{self.mode} issue {self.issue_id}", str(exc))
            return
        perf_log("issue_detail.load_task", mode=self.mode, issue_id=self.issue_id, elapsed_ms=elapsed_ms(started_at))
        _safe_emit(self.signals.finished, self.request_id, snapshot)


class FadeStackedWidget(QStackedWidget):
    """Shared page transition shell for every internal BeeLine page."""

    transition_started = Signal(object)
    transition_finished = Signal(object)

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
        started_at = perf_now()
        target_name = widget.objectName() or widget.__class__.__name__
        perf_log("transition.start", target=target_name)
        self.transition_started.emit(widget)

        if self._reduced_motion_enabled():
            self.setCurrentWidget(widget)
            perf_log("transition.finish", target=target_name, reduced_motion=True, elapsed_ms=elapsed_ms(started_at))
            self.transition_finished.emit(widget)
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

        self._animation.finished.connect(lambda: self._finish_animation(widget, start_pos, exit_overlay, started_at))
        self._animation.start()

    def _finish_animation(
        self,
        widget,
        final_pos=None,
        exit_overlay: QLabel | None = None,
        started_at: float | None = None,
    ) -> None:
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
        target_name = widget.objectName() or widget.__class__.__name__
        perf_log("transition.finish", target=target_name, elapsed_ms=elapsed_ms(started_at or perf_now()))
        self.transition_finished.emit(widget)

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
        self._log_return_widget = None
        self._dashboard_refresh_deferred = False
        self._dashboard_refresh_reason = ""
        self._machine_load_request_id = 0
        self._open_issues_request_id = 0
        self._predictive_request_id = 0
        self._details_request_id = 0
        self._issue_detail_request_id = 0
        self._pending_predictive_focus = ""
        self._closing = False
        self._current_detail: tuple[str, int] | None = None
        self.current_role = "viewer"
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(2)
        self.machine_load_pool = QThreadPool(self)
        self.machine_load_pool.setMaxThreadCount(1)
        self.page_load_pool = QThreadPool(self)
        self.page_load_pool.setMaxThreadCount(2)

        self.setWindowTitle("BeeLine Issue Tracker")
        self.resize(1240, 820)
        self.setMinimumSize(980, 640)

        self.stack = FadeStackedWidget()
        self.stack.transition_finished.connect(self._handle_transition_finished)
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

        self._refresh_dashboard("startup")
        self._refresh_archive_health()
        self._apply_role_ui()
        self.statusBar().showMessage(self._ready_status_text())

    def show_dashboard(self, *, refresh: bool = True, defer_refresh: bool = True, reason: str = "navigation") -> None:
        started_at = perf_now()
        self._current_detail = None
        if self.stack.currentWidget() == self.dashboard:
            if refresh:
                self._refresh_dashboard(reason)
            perf_log("navigation.show_dashboard", already_current=True, elapsed_ms=elapsed_ms(started_at))
            return
        if refresh and defer_refresh:
            self._queue_dashboard_refresh(reason)
        self.stack.set_current_widget_animated(self.dashboard)
        if refresh and not defer_refresh:
            self._refresh_dashboard(reason)
        perf_log(
            "navigation.show_dashboard",
            queued_refresh=refresh and defer_refresh,
            elapsed_ms=elapsed_ms(started_at),
        )

    def show_machine(self, machine_number: str, *, return_context: str = "dashboard") -> None:
        started_at = perf_now()
        self._machine_return_context = return_context
        self._machine_load_request_id += 1
        request_id = self._machine_load_request_id
        self.machine_cell.show_loading(machine_number)
        criteria = self.machine_cell.current_query()
        self._current_detail = None
        self.stack.set_current_widget_animated(self.machine_cell)
        task = MachineLoadTask(
            request_id,
            self.repository,
            self.predictive_service,
            machine_number,
            criteria,
        )
        task.signals.finished.connect(self._apply_machine_snapshot)
        task.signals.failed.connect(self._handle_machine_load_failed)
        QTimer.singleShot(0, lambda request_id=request_id, task=task: self._start_machine_load_task(request_id, task))
        perf_log(
            "navigation.show_machine",
            machine=machine_number,
            request_id=request_id,
            elapsed_ms=elapsed_ms(started_at),
        )

    def return_from_machine(self) -> None:
        if self._machine_return_context == "predictive":
            self.show_predictive_maintenance()
            return
        if self._machine_return_context == "open_issues":
            self.show_open_issues()
            return
        self.show_dashboard(reason="machine_back")

    def show_open_issues(self) -> None:
        started_at = perf_now()
        self._open_issues_request_id += 1
        request_id = self._open_issues_request_id
        self.open_issues_page.show_loading()
        query = self.open_issues_page.current_query()
        self._current_detail = None
        self.stack.set_current_widget_animated(self.open_issues_page)
        task = OpenIssuesLoadTask(request_id, self.repository, query)
        task.signals.finished.connect(self._apply_open_issues_snapshot)
        task.signals.failed.connect(self._handle_page_load_failed)
        QTimer.singleShot(0, lambda request_id=request_id, task=task: self._start_open_issues_load_task(request_id, task))
        perf_log("navigation.show_open_issues", request_id=request_id, elapsed_ms=elapsed_ms(started_at))

    def show_predictive_maintenance(self, machine_number: str | None = None) -> None:
        if not can_open_predictive_maintenance(self.current_role):
            QMessageBox.warning(self, "Admin required", "Predictive Maintenance is available after Admin login.")
            if self.stack.currentWidget() == self.predictive_page:
                self.show_dashboard()
            return
        started_at = perf_now()
        self._predictive_request_id += 1
        request_id = self._predictive_request_id
        self._pending_predictive_focus = machine_number or ""
        self.predictive_page.show_loading()
        self._current_detail = None
        self.stack.set_current_widget_animated(self.predictive_page)
        task = PredictiveLoadTask(request_id, self.predictive_service)
        task.signals.finished.connect(self._apply_predictive_snapshot)
        task.signals.failed.connect(self._handle_page_load_failed)
        QTimer.singleShot(0, lambda request_id=request_id, task=task: self._start_predictive_load_task(request_id, task))
        perf_log(
            "navigation.show_predictive",
            request_id=request_id,
            focus=machine_number or "",
            elapsed_ms=elapsed_ms(started_at),
        )

    def show_machine_details(self, machine_number: str, section: str = "overview") -> None:
        started_at = perf_now()
        self._details_return_machine = machine_number
        self._details_request_id += 1
        request_id = self._details_request_id
        self.machine_details_page.show_loading(machine_number, section)
        self._current_detail = None
        self.stack.set_current_widget_animated(self.machine_details_page)
        task = MachineDetailsLoadTask(
            request_id,
            self.repository,
            self.predictive_service,
            machine_number,
            section,
        )
        task.signals.finished.connect(self._apply_machine_details_snapshot)
        task.signals.failed.connect(self._handle_page_load_failed)
        QTimer.singleShot(0, lambda request_id=request_id, task=task: self._start_details_load_task(request_id, task))
        perf_log(
            "navigation.show_machine_details",
            machine=machine_number,
            section=section,
            request_id=request_id,
            elapsed_ms=elapsed_ms(started_at),
        )

    def return_from_machine_details(self) -> None:
        if self._details_return_machine:
            self.show_machine(self._details_return_machine)
            return
        self.show_dashboard()

    def show_log_issue(self, machine_number: str) -> None:
        if not self._authorize_create_issue():
            return
        self._log_return_widget = self.stack.currentWidget()
        self.log_issue_page.load_machine(machine_number)
        self._current_detail = None
        self.stack.set_current_widget_animated(self.log_issue_page)

    def cancel_log_issue(self) -> None:
        started_at = perf_now()
        self._current_detail = None
        return_widget = self._log_return_widget
        if return_widget is not None and return_widget is not self.log_issue_page:
            self.stack.set_current_widget_animated(return_widget)
            target = return_widget.__class__.__name__
        elif self.log_issue_page.machine_number_value:
            self.stack.set_current_widget_animated(self.machine_cell)
            target = "MachineCellPage"
        else:
            self.show_dashboard(refresh=False, reason="cancel_log_issue")
            target = "HiveDashboardPage"
        perf_log("navigation.cancel_log_issue", target=target, elapsed_ms=elapsed_ms(started_at))

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
        self._queue_dashboard_refresh("issue_saved")

    def show_issue_detail(self, mode: str, issue_id: int, *, return_context: str = "machine") -> None:
        if mode == "resolved":
            self.show_resolved_issue_detail(issue_id, return_context=return_context)
            return
        self.show_active_issue_detail(issue_id, return_context=return_context)

    def show_active_issue_detail(self, issue_id: int, return_context: str = "machine") -> None:
        self._issue_detail_request_id += 1
        request_id = self._issue_detail_request_id
        self._detail_return_context = return_context
        self._current_detail = ("active", issue_id)
        self.issue_detail_page.show_loading("active", issue_id)
        self.stack.set_current_widget_animated(self.issue_detail_page)
        task = IssueDetailLoadTask(
            request_id,
            self.repository,
            self.predictive_service,
            "active",
            issue_id,
            return_context,
        )
        task.signals.finished.connect(self._apply_issue_detail_snapshot)
        task.signals.failed.connect(self._handle_page_load_failed)
        QTimer.singleShot(0, lambda request_id=request_id, task=task: self._start_issue_detail_load_task(request_id, task))

    def show_resolved_issue_detail(self, resolved_issue_id: int, return_context: str = "machine") -> None:
        self._issue_detail_request_id += 1
        request_id = self._issue_detail_request_id
        self._detail_return_context = return_context
        self._current_detail = ("resolved", resolved_issue_id)
        self.issue_detail_page.show_loading("resolved", resolved_issue_id)
        self.stack.set_current_widget_animated(self.issue_detail_page)
        task = IssueDetailLoadTask(
            request_id,
            self.repository,
            self.predictive_service,
            "resolved",
            resolved_issue_id,
            return_context,
        )
        task.signals.finished.connect(self._apply_issue_detail_snapshot)
        task.signals.failed.connect(self._handle_page_load_failed)
        QTimer.singleShot(0, lambda request_id=request_id, task=task: self._start_issue_detail_load_task(request_id, task))

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
        self.show_predictive_maintenance()
        self.statusBar().showMessage(f"Predictive alert {alert_id} dismissed locally.", 5000)

    def _queue_dashboard_refresh(self, reason: str) -> None:
        self._dashboard_refresh_deferred = True
        self._dashboard_refresh_reason = reason
        perf_log("dashboard.refresh_deferred", reason=reason)

    def _handle_transition_finished(self, widget) -> None:
        if self._closing:
            return
        if widget == self.dashboard and self._dashboard_refresh_deferred:
            QTimer.singleShot(0, self._run_deferred_dashboard_refresh)

    def _run_deferred_dashboard_refresh(self) -> None:
        if not self._dashboard_refresh_deferred:
            return
        if self.stack.currentWidget() != self.dashboard:
            return
        reason = self._dashboard_refresh_reason or "deferred"
        self._refresh_dashboard(reason)

    def _refresh_dashboard(self, reason: str) -> None:
        started_at = perf_now()
        self._dashboard_refresh_deferred = False
        self._dashboard_refresh_reason = ""
        self.dashboard.refresh()
        perf_log("dashboard.refresh", reason=reason, elapsed_ms=elapsed_ms(started_at))

    def _start_machine_load_task(self, request_id: int, task: QRunnable) -> None:
        if not self._closing and request_id == self._machine_load_request_id:
            self.machine_load_pool.start(task)

    def _start_open_issues_load_task(self, request_id: int, task: QRunnable) -> None:
        if not self._closing and request_id == self._open_issues_request_id:
            self.page_load_pool.start(task)

    def _start_predictive_load_task(self, request_id: int, task: QRunnable) -> None:
        if not self._closing and request_id == self._predictive_request_id:
            self.page_load_pool.start(task)

    def _start_details_load_task(self, request_id: int, task: QRunnable) -> None:
        if not self._closing and request_id == self._details_request_id:
            self.page_load_pool.start(task)

    def _start_issue_detail_load_task(self, request_id: int, task: QRunnable) -> None:
        if not self._closing and request_id == self._issue_detail_request_id:
            self.page_load_pool.start(task)

    def _apply_machine_snapshot(self, request_id: int, snapshot) -> None:
        if request_id != self._machine_load_request_id:
            perf_log("machine.snapshot_ignored", request_id=request_id, current_request=self._machine_load_request_id)
            return
        if self.stack.currentWidget() != self.machine_cell:
            perf_log("machine.snapshot_ignored", request_id=request_id, reason="machine_page_not_visible")
            return
        started_at = perf_now()
        self.machine_cell.apply_snapshot(snapshot)
        perf_log(
            "machine.apply_snapshot",
            machine=getattr(snapshot, "machine_number", ""),
            request_id=request_id,
            elapsed_ms=elapsed_ms(started_at),
        )

    def _handle_machine_load_failed(self, request_id: int, machine_number: str, message: str) -> None:
        if request_id != self._machine_load_request_id:
            return
        self.machine_cell.machine_subtitle.setText("Could not load machine details.")
        self.machine_cell.memory_summary.setText(message)
        self.statusBar().showMessage(f"Could not load machine {machine_number}: {message}", 8000)

    def _apply_open_issues_snapshot(self, request_id: int, snapshot) -> None:
        if request_id != self._open_issues_request_id or self.stack.currentWidget() != self.open_issues_page:
            perf_log("open_issues.snapshot_ignored", request_id=request_id)
            return
        started_at = perf_now()
        self.open_issues_page.apply_snapshot(snapshot)
        perf_log("open_issues.apply_snapshot", request_id=request_id, elapsed_ms=elapsed_ms(started_at))

    def _apply_predictive_snapshot(self, request_id: int, snapshot) -> None:
        if request_id != self._predictive_request_id or self.stack.currentWidget() != self.predictive_page:
            perf_log("predictive.snapshot_ignored", request_id=request_id)
            return
        started_at = perf_now()
        self.predictive_page.apply_snapshot(snapshot)
        if self._pending_predictive_focus:
            self.predictive_page.focus_machine(self._pending_predictive_focus)
            self._pending_predictive_focus = ""
        perf_log("predictive.apply_snapshot", request_id=request_id, elapsed_ms=elapsed_ms(started_at))

    def _apply_machine_details_snapshot(self, request_id: int, snapshot) -> None:
        if request_id != self._details_request_id or self.stack.currentWidget() != self.machine_details_page:
            perf_log("details.snapshot_ignored", request_id=request_id)
            return
        started_at = perf_now()
        self.machine_details_page.apply_snapshot(snapshot)
        perf_log(
            "details.apply_snapshot",
            request_id=request_id,
            machine=getattr(snapshot, "machine_number", ""),
            elapsed_ms=elapsed_ms(started_at),
        )

    def _apply_issue_detail_snapshot(self, request_id: int, snapshot) -> None:
        if request_id != self._issue_detail_request_id or self.stack.currentWidget() != self.issue_detail_page:
            perf_log("issue_detail.snapshot_ignored", request_id=request_id)
            return
        if snapshot.get("missing"):
            QMessageBox.information(self, "Issue not found", "This issue is no longer available.")
            self._return_to_context(snapshot.get("return_context", self._detail_return_context))
            return
        started_at = perf_now()
        mode = snapshot.get("mode")
        if mode == "resolved":
            self.issue_detail_page.load_resolved(
                snapshot["context"],
                trend_summary=snapshot.get("trend") or {},
                attachments=snapshot.get("attachments") or [],
                related_matches=snapshot.get("related_matches") or [],
                recurring_patterns=snapshot.get("recurring_patterns") or [],
            )
        else:
            self.issue_detail_page.load_active(
                snapshot["context"],
                related_issues=snapshot.get("related_issues") or [],
                related_matches=snapshot.get("related_matches") or [],
                fix_suggestions=snapshot.get("fix_suggestions") or [],
                trend_summary=snapshot.get("trend") or {},
                attachments=snapshot.get("attachments") or [],
            )
        perf_log(
            "issue_detail.apply_snapshot",
            request_id=request_id,
            mode=mode,
            issue_id=snapshot.get("issue_id"),
            elapsed_ms=elapsed_ms(started_at),
        )

    def _handle_page_load_failed(self, request_id: int, context: str, message: str) -> None:
        self.statusBar().showMessage(f"Could not load {context}: {message}", 8000)

    def refresh_current_views(self) -> None:
        current = self.stack.currentWidget()
        if current == self.dashboard:
            self._refresh_dashboard("refresh_current_views")
        else:
            self._queue_dashboard_refresh("refresh_current_views")
        if current == self.machine_cell and self.machine_cell.machine_number:
            self.show_machine(self.machine_cell.machine_number, return_context=self._machine_return_context)
        if current == self.machine_details_page and self.machine_details_page.machine_number:
            self.show_machine_details(self.machine_details_page.machine_number, "overview")
        if current == self.open_issues_page:
            self.show_open_issues()
        if current == self.predictive_page and can_open_predictive_maintenance(self.current_role):
            self.show_predictive_maintenance()

    def on_archive_finished(self, resolved_issue_id: int, success: bool, message: str) -> None:
        resolved = self.repository.get_resolved_issue(resolved_issue_id)
        label = display_issue_id(resolved) if resolved is not None else str(resolved_issue_id)
        if success:
            self.statusBar().showMessage(f"Resolved issue {label} archived. {message}", 7000)
        else:
            self.statusBar().showMessage(f"Archive failed for issue {label}: {message}", 8000)
        current = self.stack.currentWidget()
        if current == self.machine_cell and self.machine_cell.machine_number:
            self.show_machine(self.machine_cell.machine_number, return_context=self._machine_return_context)
        if current == self.open_issues_page:
            self.show_open_issues()
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
        self._current_detail = None
        self.stack.set_current_widget_animated(self.settings_page)
        QTimer.singleShot(0, self._refresh_archive_health)

    def _apply_role_ui(self) -> None:
        self.role_label.setText(f"Role: {self._role_label_text()}")
        self.login_button.setText("Logout" if self.current_role != "viewer" else "Login")
        self.settings_button.setVisible(can_open_settings(self.current_role))
        self.dashboard.set_can_open_predictive_maintenance(can_open_predictive_maintenance(self.current_role))
        self.machine_cell.set_can_report(can_create_issue(self.current_role))
        self.machine_details_page.set_can_report(can_create_issue(self.current_role))

    def _role_label_text(self) -> str:
        return {
            "admin": "Admin",
            "technician": "Technician",
            "viewer": "Viewer",
        }.get(self.current_role, "Viewer")

    def _ready_status_text(self) -> str:
        return "Ready | SQLite live cache active"

    def _refresh_archive_health(self) -> None:
        if self._closing:
            return
        self.settings_page.set_archive_health(self.repository.archive_status_counts())

    def closeEvent(self, event) -> None:
        self._closing = True
        self._machine_load_request_id += 1
        self._open_issues_request_id += 1
        self._predictive_request_id += 1
        self._details_request_id += 1
        self._issue_detail_request_id += 1
        self.dashboard._resize_timer.stop()
        self.dashboard._search_timer.stop()
        self.open_issues_page._search_timer.stop()
        self.predictive_page._render_timer.stop()
        self.machine_load_pool.waitForDone(3000)
        self.page_load_pool.waitForDone(5000)
        super().closeEvent(event)
