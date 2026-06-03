from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QVBoxLayout,
)

from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.ui.theme import ThemeManager, repolish, status_state
from beeline_issue_tracker.ui.widgets import (
    BrandHeader,
    HoneycombBackground,
    IssueListView,
    MetricPill,
    PrimaryActionButton,
    StatusBadge,
    ThemeToggleButton,
)


class MachineCellPage(HoneycombBackground):
    back_requested = Signal()
    log_issue_requested = Signal(str)
    resolve_issue_requested = Signal(int)

    def __init__(self, repository: IssueRepository, theme_manager: ThemeManager, paths: AppPaths, parent=None):
        super().__init__(theme_manager, parent)
        self.repository = repository
        self.theme_manager = theme_manager
        self.paths = paths
        self.machine_number: str | None = None

        page = QVBoxLayout(self)
        page.setContentsMargins(24, 22, 24, 22)
        page.setSpacing(16)

        nav = QHBoxLayout()
        self.back_button = QPushButton("Back to Hive Dashboard")
        self.back_button.clicked.connect(self.back_requested.emit)
        nav.addWidget(self.back_button)
        nav.addStretch(1)
        nav.addWidget(ThemeToggleButton(theme_manager))
        page.addLayout(nav)

        self.machine_header = QFrame()
        self.machine_header.setObjectName("machineHeader")
        header_layout = QVBoxLayout(self.machine_header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setSpacing(14)
        self.brand_header = BrandHeader("Machine", "", paths.logo_path())
        title_row.addWidget(self.brand_header, 1)
        self.status_badge = StatusBadge("Unknown/Error")
        title_row.addWidget(self.status_badge)
        self.log_button = PrimaryActionButton("+ Log Issue")
        self.log_button.clicked.connect(self._request_log_issue)
        title_row.addWidget(self.log_button)
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
        page.addWidget(self.machine_header)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.active_list = IssueListView(
            "active",
            "Active/Open Issues",
            "Search active issues...",
            show_log_action=True,
        )
        self.active_list.resolve_requested.connect(self.resolve_issue_requested.emit)
        self.active_list.log_issue_requested.connect(self._request_log_issue)
        splitter.addWidget(self.active_list)

        self.resolved_list = IssueListView(
            "resolved",
            "Recent Resolved",
            "Search resolved issues...",
        )
        splitter.addWidget(self.resolved_list)
        splitter.setSizes([420, 300])
        page.addWidget(splitter, 1)

    def load_machine(self, machine_number: str) -> None:
        self.machine_number = machine_number
        self.refresh()

    def refresh(self) -> None:
        if not self.machine_number:
            return

        summary = self.repository.get_machine_summary(self.machine_number)
        if summary is None:
            self.brand_header.set_title("Machine not found")
            self.brand_header.set_subtitle("")
            self.status_badge.set_status("Unknown/Error")
            self.machine_header.setProperty("statusState", "unknown")
            repolish(self.machine_header)
            self.area_pill.set_value("-")
            self.cell_pill.set_value("-")
            self.asset_pill.set_value("-")
            self.open_issue_pill.set_value("0")
            self.recent_resolved_pill.set_value("0")
            self.active_list.set_issues([])
            self.resolved_list.set_issues([])
            return

        self.brand_header.set_title(f"Machine {summary.machine_number}")
        self.brand_header.set_subtitle(summary.name)
        self.status_badge.set_status(summary.calculated_status)
        self.machine_header.setProperty("statusState", status_state(summary.calculated_status))
        repolish(self.machine_header)

        active_issues = self.repository.list_active_issues(summary.machine_number)
        recent_resolved = self.repository.list_recent_resolved_issues(summary.machine_number, limit=None)

        self.area_pill.set_value(summary.area)
        self.cell_pill.set_value(summary.cell)
        self.asset_pill.set_value(summary.asset_tag)
        self.open_issue_pill.set_value(str(summary.open_issue_count))
        self.recent_resolved_pill.set_value(str(len(recent_resolved)))
        self.active_list.set_issues(active_issues)
        self.resolved_list.set_issues(recent_resolved)

    def _request_log_issue(self) -> None:
        if self.machine_number:
            self.log_issue_requested.emit(self.machine_number)
