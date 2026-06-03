from __future__ import annotations

import logging

from PySide6.QtCore import QEasingCurve, QPoint, QParallelAnimationGroup, QPropertyAnimation, QThreadPool
from PySide6.QtWidgets import QGraphicsOpacityEffect, QMainWindow, QMessageBox, QStackedWidget

from beeline_issue_tracker.config import AppPaths, RuntimeConfig
from beeline_issue_tracker.data.archive_worker import ArchiveIssueTask
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.ui.dashboard import HiveDashboardPage
from beeline_issue_tracker.ui.dialogs import PinDialog, ResolveIssueDialog
from beeline_issue_tracker.ui.issue_detail_page import IssueDetailPage
from beeline_issue_tracker.ui.log_issue_page import LogIssuePage
from beeline_issue_tracker.ui.machine_cell import MachineCellPage
from beeline_issue_tracker.ui.open_issues import OpenIssuesPage
from beeline_issue_tracker.ui.theme import ThemeManager


logger = logging.getLogger(__name__)


class FadeStackedWidget(QStackedWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._animation: QParallelAnimationGroup | None = None
        self._effect: QGraphicsOpacityEffect | None = None
        self._animated_widget = None
        self._animated_target_pos: QPoint | None = None

    def set_current_widget_animated(self, widget) -> None:
        if self.currentWidget() == widget:
            return
        self._clear_animation()
        self.setCurrentWidget(widget)
        start_pos = widget.pos()
        self._effect = QGraphicsOpacityEffect(widget)
        self._effect.setOpacity(0.0)
        widget.setGraphicsEffect(self._effect)
        widget.move(start_pos + QPoint(0, 10))
        self._animated_widget = widget
        self._animated_target_pos = start_pos

        fade = QPropertyAnimation(self._effect, b"opacity", self)
        fade.setDuration(190)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        slide = QPropertyAnimation(widget, b"pos", self)
        slide.setDuration(190)
        slide.setStartValue(start_pos + QPoint(0, 10))
        slide.setEndValue(start_pos)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._animation = QParallelAnimationGroup(self)
        self._animation.addAnimation(fade)
        self._animation.addAnimation(slide)
        self._animation.finished.connect(lambda: self._finish_animation(widget, start_pos))
        self._animation.start()

    def _finish_animation(self, widget, final_pos=None) -> None:
        if final_pos is not None:
            widget.move(final_pos)
        widget.setGraphicsEffect(None)
        self._effect = None
        self._animation = None
        self._animated_widget = None
        self._animated_target_pos = None

    def _clear_animation(self) -> None:
        if self._animation is not None:
            self._animation.stop()
            self._animation = None
        if self._animated_widget is not None:
            if self._animated_target_pos is not None:
                self._animated_widget.move(self._animated_target_pos)
            self._animated_widget.setGraphicsEffect(None)
        current = self.currentWidget()
        if current is not None:
            current.setGraphicsEffect(None)
        self._effect = None
        self._animated_widget = None
        self._animated_target_pos = None


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
        self._current_detail: tuple[str, int] | None = None
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(2)

        self.setWindowTitle("BeeLine Issue Tracker")
        self.resize(1240, 820)
        self.setMinimumSize(980, 640)

        self.stack = FadeStackedWidget()
        self.dashboard = HiveDashboardPage(repository, theme_manager, paths)
        self.machine_cell = MachineCellPage(repository, theme_manager, paths)
        self.open_issues_page = OpenIssuesPage(repository, theme_manager, paths)
        self.issue_detail_page = IssueDetailPage(theme_manager, paths)
        self.log_issue_page = LogIssuePage(repository, theme_manager, paths)
        self.stack.addWidget(self.dashboard)
        self.stack.addWidget(self.machine_cell)
        self.stack.addWidget(self.open_issues_page)
        self.stack.addWidget(self.issue_detail_page)
        self.stack.addWidget(self.log_issue_page)
        self.setCentralWidget(self.stack)

        self.dashboard.machine_selected.connect(self.show_machine)
        self.dashboard.open_issues_requested.connect(self.show_open_issues)
        self.machine_cell.back_requested.connect(self.show_dashboard)
        self.machine_cell.log_issue_requested.connect(self.show_log_issue)
        self.machine_cell.resolve_issue_requested.connect(self.open_resolve_issue)
        self.machine_cell.issue_detail_requested.connect(
            lambda issue_id, mode: self.show_issue_detail(mode, issue_id, return_context="machine")
        )
        self.open_issues_page.back_requested.connect(self.show_dashboard)
        self.open_issues_page.machine_requested.connect(self.show_machine)
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

        self.dashboard.refresh()
        self.statusBar().showMessage(f"Ready | Excel archive: {self.paths.archive_path}")

    def show_dashboard(self) -> None:
        self.dashboard.refresh()
        self._current_detail = None
        self.stack.set_current_widget_animated(self.dashboard)

    def show_machine(self, machine_number: str) -> None:
        self.machine_cell.load_machine(machine_number)
        self._current_detail = None
        self.stack.set_current_widget_animated(self.machine_cell)

    def show_open_issues(self) -> None:
        self.open_issues_page.refresh()
        self._current_detail = None
        self.stack.set_current_widget_animated(self.open_issues_page)

    def show_log_issue(self, machine_number: str) -> None:
        self.log_issue_page.load_machine(machine_number)
        self._current_detail = None
        self.stack.set_current_widget_animated(self.log_issue_page)

    def cancel_log_issue(self) -> None:
        if self.log_issue_page.machine_number_value:
            self.show_machine(self.log_issue_page.machine_number_value)
        else:
            self.show_dashboard()

    def save_log_issue(self, values: dict[str, str]) -> None:
        try:
            self.repository.log_issue(**values)
        except Exception as exc:
            QMessageBox.critical(self, "Could not log issue", str(exc))
            return

        machine_number = values["machine_number"]
        self.statusBar().showMessage(f"Issue logged for machine {machine_number}", 5000)
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
        trend = self.repository.get_machine_issue_trend_summary(context.issue.machine_number)
        attachments = self.repository.list_attachments_for_issue(issue_id=context.issue.id)
        self.issue_detail_page.load_active(
            context,
            related_issues=related,
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
        attachments = self.repository.list_attachments_for_issue(resolved_issue_id=context.issue.id)
        self.issue_detail_page.load_resolved(context, trend_summary=trend, attachments=attachments)
        self._detail_return_context = return_context
        self._current_detail = ("resolved", resolved_issue_id)
        self.stack.set_current_widget_animated(self.issue_detail_page)

    def return_from_issue_detail(self) -> None:
        self._return_to_context(self._detail_return_context)

    def _return_to_context(self, return_context: str) -> None:
        if return_context == "open_issues":
            self.show_open_issues()
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
        logger.info("Queueing resolved issue %s for Excel archive at %s", resolved.id, self.paths.archive_path)
        self.statusBar().showMessage(f"Issue resolved. Excel archive queued: {self.paths.archive_path}", 5000)
        if resolving_from_detail:
            self.show_resolved_issue_detail(resolved.id, return_context=detail_return)
        else:
            self.refresh_current_views()

        task = ArchiveIssueTask(self.paths.archive_path, self.repository, resolved)
        task.signals.finished.connect(self.on_archive_finished)
        self.thread_pool.start(task)

    def _authorize_resolve(self) -> bool:
        if not self.runtime_config.resolve_requires_pin():
            return True
        dialog = PinDialog("Resolve requires technician or admin PIN.", self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return False
        if self.runtime_config.verify_pin_for_roles(dialog.value(), ("technician", "admin")):
            return True
        QMessageBox.warning(self, "PIN rejected", "That PIN is not authorized to resolve issues.")
        return False

    def refresh_current_views(self) -> None:
        self.dashboard.refresh()
        self.machine_cell.refresh()
        self.open_issues_page.refresh()

    def on_archive_finished(self, resolved_issue_id: int, success: bool, message: str) -> None:
        if success:
            self.statusBar().showMessage(f"Resolved issue {resolved_issue_id} archived. {message}", 7000)
        else:
            self.statusBar().showMessage(f"Archive failed for issue {resolved_issue_id}: {message}", 8000)
        self.machine_cell.refresh()
        self.open_issues_page.refresh()
        if self.stack.currentWidget() == self.issue_detail_page and self._current_detail == ("resolved", resolved_issue_id):
            self.show_resolved_issue_detail(resolved_issue_id, return_context=self._detail_return_context)
