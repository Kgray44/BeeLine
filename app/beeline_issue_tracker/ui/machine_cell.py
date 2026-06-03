from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from beeline_issue_tracker.analytics.predictive_service import PredictiveMaintenanceService
from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.ui.charts import RiskScoreBar
from beeline_issue_tracker.ui.theme import ThemeManager, repolish, status_state
from beeline_issue_tracker.ui.widgets import (
    BrandHeader,
    HoneycombBackground,
    IssueListView,
    MetricPill,
    StatusBadge,
)


logger = logging.getLogger(__name__)


class MachineCellPage(HoneycombBackground):
    back_requested = Signal()
    log_issue_requested = Signal(str)
    resolve_issue_requested = Signal(int)
    issue_detail_requested = Signal(int, str)
    machine_details_requested = Signal(str, str)

    def __init__(
        self,
        repository: IssueRepository,
        theme_manager: ThemeManager,
        paths: AppPaths,
        predictive_service: PredictiveMaintenanceService | None = None,
        parent=None,
    ):
        super().__init__(theme_manager, parent)
        self.repository = repository
        self.theme_manager = theme_manager
        self.paths = paths
        self.predictive_service = predictive_service
        self.machine_number: str | None = None

        page = QVBoxLayout(self)
        page.setContentsMargins(24, 22, 24, 22)
        page.setSpacing(16)

        nav = QHBoxLayout()
        self.back_button = QPushButton("Back to Hive Dashboard")
        self.back_button.clicked.connect(self.back_requested.emit)
        nav.addWidget(self.back_button)
        nav.addWidget(BrandHeader("BeeLine Issue Tracker", "Machine Cell", paths.logo_path(), theme_manager), 1)
        page.addLayout(nav)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("transparentHost")
        body = QVBoxLayout(self.content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        self.scroll.setWidget(self.content)
        page.addWidget(self.scroll, 1)

        self.machine_header = QFrame()
        self.machine_header.setObjectName("machineHeader")
        header_layout = QVBoxLayout(self.machine_header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setSpacing(14)
        title_text = QVBoxLayout()
        title_text.setContentsMargins(0, 0, 0, 0)
        title_text.setSpacing(2)
        self.machine_title = QLabel("Machine")
        self.machine_title.setObjectName("machineNumber")
        self.machine_subtitle = QLabel("")
        self.machine_subtitle.setObjectName("subtitleLabel")
        self.machine_meta = QLabel("")
        self.machine_meta.setObjectName("mutedLabel")
        self.machine_meta.setWordWrap(True)
        title_text.addWidget(self.machine_title)
        title_text.addWidget(self.machine_subtitle)
        title_text.addWidget(self.machine_meta)
        title_row.addLayout(title_text, 1)
        self.status_badge = StatusBadge("Unknown/Error")
        title_row.addWidget(self.status_badge)
        header_layout.addLayout(title_row)

        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        self.area_pill = MetricPill("Area")
        self.cell_pill = MetricPill("Cell")
        self.asset_pill = MetricPill("Asset Tag")
        self.open_issue_pill = MetricPill("Open Issues")
        self.recent_resolved_pill = MetricPill("Recent Resolved")
        for pill in (
            self.area_pill,
            self.cell_pill,
            self.asset_pill,
            self.open_issue_pill,
            self.recent_resolved_pill,
        ):
            metrics.addWidget(pill)
        metrics.addStretch(1)
        header_layout.addLayout(metrics)
        body.addWidget(self.machine_header)

        self.intelligence_panel = QFrame()
        self.intelligence_panel.setObjectName("infoPanel")
        intelligence_layout = QVBoxLayout(self.intelligence_panel)
        intelligence_layout.setContentsMargins(16, 12, 16, 12)
        intelligence_layout.setSpacing(8)
        intelligence_title = QLabel("Maintenance Intelligence")
        intelligence_title.setObjectName("sectionTitle")
        intelligence_layout.addWidget(intelligence_title)
        intelligence_grid = QGridLayout()
        intelligence_grid.setHorizontalSpacing(12)
        intelligence_grid.setVerticalSpacing(6)
        self.risk_score_bar = RiskScoreBar(theme_manager)
        intelligence_grid.addWidget(self.risk_score_bar, 0, 0, 1, 4)
        self.intelligence_confidence = QLabel()
        self.intelligence_confidence.setObjectName("mutedLabel")
        self.intelligence_predicted_problem = QLabel()
        self.intelligence_predicted_problem.setWordWrap(True)
        self.intelligence_suggested_action = QLabel()
        self.intelligence_suggested_action.setWordWrap(True)
        self.intelligence_reasons = QLabel()
        self.intelligence_reasons.setObjectName("mutedLabel")
        self.intelligence_reasons.setWordWrap(True)
        self.intelligence_recurring = QLabel()
        self.intelligence_recurring.setObjectName("mutedLabel")
        self.intelligence_last_issue = QLabel()
        self.intelligence_last_issue.setObjectName("mutedLabel")
        intelligence_grid.addWidget(QLabel("Confidence"), 1, 0)
        intelligence_grid.addWidget(self.intelligence_confidence, 1, 1)
        intelligence_grid.addWidget(QLabel("Recurring"), 1, 2)
        intelligence_grid.addWidget(self.intelligence_recurring, 1, 3)
        intelligence_grid.addWidget(QLabel("Predicted Problem"), 2, 0)
        intelligence_grid.addWidget(self.intelligence_predicted_problem, 2, 1, 1, 3)
        intelligence_grid.addWidget(QLabel("Suggested Action"), 3, 0)
        intelligence_grid.addWidget(self.intelligence_suggested_action, 3, 1, 1, 3)
        intelligence_grid.addWidget(QLabel("Risk Reasons"), 4, 0)
        intelligence_grid.addWidget(self.intelligence_reasons, 4, 1, 1, 3)
        intelligence_grid.addWidget(QLabel("Last Issue"), 5, 0)
        intelligence_grid.addWidget(self.intelligence_last_issue, 5, 1, 1, 3)
        intelligence_layout.addLayout(intelligence_grid)
        intelligence_buttons = QHBoxLayout()
        info_button = QPushButton("Machine Info")
        info_button.setObjectName("tableActionButton")
        info_button.clicked.connect(lambda _checked=False: self._request_machine_details("overview"))
        intelligence_buttons.addWidget(info_button)
        intelligence_buttons.addStretch(1)
        intelligence_layout.addLayout(intelligence_buttons)
        body.addWidget(self.intelligence_panel)

        self.active_list = IssueListView(
            "active",
            "Active/Open Issues",
            "Search active issues...",
            show_log_action=True,
        )
        self.active_list.resolve_requested.connect(self.resolve_issue_requested.emit)
        self.active_list.log_issue_requested.connect(self._request_log_issue)
        self.active_list.detail_requested.connect(self.issue_detail_requested.emit)
        self.active_list.criteria_changed.connect(self.refresh)
        body.addWidget(self.active_list)

        self.resolved_list = IssueListView(
            "resolved",
            "Recent Resolved",
            "Search resolved issues...",
        )
        self.resolved_list.detail_requested.connect(self.issue_detail_requested.emit)
        self.resolved_list.criteria_changed.connect(self.refresh)
        body.addWidget(self.resolved_list)

        self.memory_panel = QFrame()
        self.memory_panel.setObjectName("infoPanel")
        memory_layout = QVBoxLayout(self.memory_panel)
        memory_layout.setContentsMargins(16, 12, 16, 12)
        memory_layout.setSpacing(6)
        memory_title = QLabel("Troubleshooting Memory")
        memory_title.setObjectName("sectionTitle")
        self.memory_summary = QLabel()
        self.memory_summary.setObjectName("mutedLabel")
        self.memory_summary.setWordWrap(True)
        memory_layout.addWidget(memory_title)
        memory_layout.addWidget(self.memory_summary)
        body.addWidget(self.memory_panel)
        body.addStretch(1)

    def load_machine(self, machine_number: str) -> None:
        self.machine_number = machine_number
        self.refresh()

    def set_can_report(self, enabled: bool) -> None:
        self.active_list.set_log_action_enabled(enabled)

    def refresh(self) -> None:
        if not self.machine_number:
            return

        summary = self.repository.get_machine_summary(self.machine_number)
        if summary is None:
            self.machine_title.setText("Machine not found")
            self.machine_subtitle.setText("")
            self.machine_meta.setText("")
            self.status_badge.set_status("Unknown/Error")
            self.machine_header.setProperty("statusState", "unknown")
            repolish(self.machine_header)
            self.area_pill.set_value("-")
            self.cell_pill.set_value("-")
            self.asset_pill.set_value("-")
            self.open_issue_pill.set_value("0")
            self.recent_resolved_pill.set_value("0")
            self.memory_summary.setText("No resolved history yet.")
            self._set_intelligence_empty()
            self.active_list.set_issues([])
            self.resolved_list.set_issues([])
            return

        self.machine_title.setText(f"Machine {summary.machine_number}")
        self.machine_subtitle.setText(summary.name)
        self.machine_meta.setText(_machine_meta_text(summary))
        self.status_badge.set_status(summary.calculated_status)
        self.machine_header.setProperty("statusState", status_state(summary.calculated_status))
        repolish(self.machine_header)

        active_query, active_sort, active_limit, active_offset = self.active_list.criteria()
        resolved_query, resolved_sort, resolved_limit, resolved_offset = self.resolved_list.criteria()
        active_issues = self.repository.list_active_issues(
            summary.machine_number,
            query=active_query,
            sort_key=active_sort,
            limit=active_limit,
            offset=active_offset,
        )
        recent_resolved = self.repository.list_resolved_issues(
            summary.machine_number,
            query=resolved_query,
            sort_key=resolved_sort,
            limit=resolved_limit,
            offset=resolved_offset,
        )
        active_matched = self.repository.count_active_issues_matching(summary.machine_number, active_query)
        resolved_matched = self.repository.count_resolved_issues_matching(summary.machine_number, resolved_query)
        stats = self.repository.get_machine_resolved_stats(summary.machine_number)

        self.area_pill.set_value(summary.area)
        self.cell_pill.set_value(summary.cell)
        self.asset_pill.set_value(summary.asset_tag)
        self.open_issue_pill.set_value(str(summary.open_issue_count))
        self.recent_resolved_pill.set_value(str(stats.total_resolved))
        self.memory_summary.setText(_memory_text(stats))
        self._update_intelligence(summary.machine_number)
        self.active_list.set_query_result(
            active_issues,
            matched=active_matched,
            total=summary.open_issue_count,
        )
        self.resolved_list.set_query_result(
            recent_resolved,
            matched=resolved_matched,
            total=stats.total_resolved,
        )

    def _request_log_issue(self) -> None:
        if self.machine_number:
            logger.debug("Add Issue clicked for machine %s", self.machine_number)
            self.log_issue_requested.emit(self.machine_number)

    def _request_machine_details(self, section: str) -> None:
        if self.machine_number:
            self.machine_details_requested.emit(self.machine_number, section)

    def _update_intelligence(self, machine_number: str) -> None:
        if self.predictive_service is None:
            self._set_intelligence_empty()
            return
        risk = self.predictive_service.get_machine_risk(machine_number)
        if risk is None:
            self._set_intelligence_empty()
            return
        self.risk_score_bar.set_score(risk.risk_score, risk.risk_level)
        self.intelligence_confidence.setText(risk.confidence)
        self.intelligence_predicted_problem.setText(risk.predicted_problem)
        self.intelligence_suggested_action.setText(risk.suggested_action)
        self.intelligence_reasons.setText(" | ".join(risk.risk_reasons[:3]))
        self.intelligence_recurring.setText(str(risk.recurring_issue_count))
        avg = _format_minutes(risk.average_time_open_minutes)
        last_issue = risk.last_issue_at or "-"
        self.intelligence_last_issue.setText(f"{last_issue} | Avg open: {avg}")

    def _set_intelligence_empty(self) -> None:
        self.risk_score_bar.set_score(0, "Unknown")
        self.intelligence_confidence.setText("Unknown")
        self.intelligence_predicted_problem.setText("No clear recurring problem")
        self.intelligence_suggested_action.setText("No action needed beyond normal checks.")
        self.intelligence_reasons.setText("Not enough issue history yet.")
        self.intelligence_recurring.setText("0")
        self.intelligence_last_issue.setText("-")


def _memory_text(stats) -> str:
    if stats.total_resolved == 0:
        return "No resolved history yet."
    avg = _format_seconds(stats.average_time_open_seconds)
    last_fix = stats.last_resolved_title or "-"
    parts = [
        f"Resolved: {stats.total_resolved}",
        f"Most common category: {stats.most_common_category or '-'}",
        f"Average time open: {avg}",
        f"Recurring: {stats.recurring_warning or 'None'}",
        f"Last fix: {last_fix}",
    ]
    return " | ".join(parts)


def _machine_meta_text(machine) -> str:
    parts = [
        " / ".join(part for part in (machine.area, machine.cell) if part),
        f"Asset {machine.asset_tag}" if machine.asset_tag else "",
        f"{machine.manufacturer} {machine.model}".strip(),
        f"IMM Serial {machine.imm_serial}" if machine.imm_serial else "",
        f"Robot {machine.robot_type} {machine.robot_model}".strip()
        if machine.robot_type or machine.robot_model
        else "",
    ]
    return " | ".join(part for part in parts if part)


def _format_seconds(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24
    if days:
        return f"{days}d {hours % 24}h"
    if hours:
        return f"{hours}h {minutes % 60}m"
    return f"{minutes}m"


def _format_minutes(minutes: int | None) -> str:
    if minutes is None:
        return "-"
    hours = minutes // 60
    days = hours // 24
    if days:
        return f"{days}d {hours % 24}h"
    if hours:
        return f"{hours}h {minutes % 60}m"
    return f"{minutes}m"
