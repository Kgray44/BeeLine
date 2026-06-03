from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.ui.theme import ThemeManager
from beeline_issue_tracker.ui.widgets import (
    BrandHeader,
    HoneycombBackground,
    InfoRow,
    IssueCard,
    ResolvedIssueCard,
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

        header = QHBoxLayout()
        self.back_button = QPushButton("Back to Hive Dashboard")
        self.back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back_button)
        header.addStretch(1)
        self.log_button = QPushButton("Log Issue")
        self.log_button.setObjectName("primaryButton")
        self.log_button.clicked.connect(self._request_log_issue)
        header.addWidget(self.log_button)
        header.addWidget(ThemeToggleButton(theme_manager))
        page.addLayout(header)

        title_row = QHBoxLayout()
        self.brand_header = BrandHeader("Machine", "", paths.logo_path())
        title_row.addWidget(self.brand_header, 1)
        self.status_badge = StatusBadge("Unknown/Error")
        title_row.addWidget(self.status_badge)
        page.addLayout(title_row)

        self.info_panel = QFrame()
        self.info_panel.setObjectName("infoPanel")
        self.info_layout = QVBoxLayout(self.info_panel)
        self.info_layout.setContentsMargins(16, 14, 16, 14)
        self.info_layout.setSpacing(8)
        page.addWidget(self.info_panel)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_active_section())
        splitter.addWidget(self._build_resolved_section())
        splitter.setSizes([680, 440])
        page.addWidget(splitter, 1)

    def _build_active_section(self) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        title = QLabel("Active/Open Issues")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.active_empty = QLabel("No active issues.")
        self.active_empty.setObjectName("mutedLabel")
        layout.addWidget(self.active_empty)

        self.active_scroll = QScrollArea()
        self.active_scroll.setWidgetResizable(True)
        self.active_host = QWidget()
        self.active_host.setObjectName("transparentHost")
        self.active_layout = QVBoxLayout(self.active_host)
        self.active_layout.setContentsMargins(0, 0, 0, 0)
        self.active_layout.setSpacing(12)
        self.active_layout.addStretch(1)
        self.active_scroll.setWidget(self.active_host)
        layout.addWidget(self.active_scroll, 1)
        return section

    def _build_resolved_section(self) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        title = QLabel("Recent Resolved")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.resolved_empty = QLabel("No recently resolved issues.")
        self.resolved_empty.setObjectName("mutedLabel")
        layout.addWidget(self.resolved_empty)

        self.resolved_scroll = QScrollArea()
        self.resolved_scroll.setWidgetResizable(True)
        self.resolved_host = QWidget()
        self.resolved_host.setObjectName("transparentHost")
        self.resolved_layout = QVBoxLayout(self.resolved_host)
        self.resolved_layout.setContentsMargins(0, 0, 0, 0)
        self.resolved_layout.setSpacing(12)
        self.resolved_layout.addStretch(1)
        self.resolved_scroll.setWidget(self.resolved_host)
        layout.addWidget(self.resolved_scroll, 1)
        return section

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
            return

        self.brand_header.set_title(f"Machine {summary.machine_number}")
        self.brand_header.set_subtitle(f"{summary.name} | {summary.area} | {summary.cell}")
        self.status_badge.set_status(summary.calculated_status)

        self._clear_layout(self.info_layout)
        self.info_layout.addWidget(InfoRow("Machine", summary.machine_number))
        self.info_layout.addWidget(InfoRow("Name", summary.name))
        self.info_layout.addWidget(InfoRow("Area", summary.area))
        self.info_layout.addWidget(InfoRow("Cell", summary.cell))
        self.info_layout.addWidget(InfoRow("Asset tag", summary.asset_tag))
        self.info_layout.addWidget(InfoRow("Status", summary.calculated_status))
        self.info_layout.addWidget(InfoRow("Open issues", str(summary.open_issue_count)))

        active_issues = self.repository.list_active_issues(summary.machine_number)
        self._populate_active(active_issues)

        recent_resolved = self.repository.list_recent_resolved_issues(summary.machine_number)
        self._populate_resolved(recent_resolved)

    def _populate_active(self, issues) -> None:
        self._clear_layout(self.active_layout)
        self.active_empty.setVisible(len(issues) == 0)
        for issue in issues:
            card = IssueCard(issue)
            card.resolve_requested.connect(self.resolve_issue_requested.emit)
            self.active_layout.addWidget(card)
        self.active_layout.addStretch(1)

    def _populate_resolved(self, issues) -> None:
        self._clear_layout(self.resolved_layout)
        self.resolved_empty.setVisible(len(issues) == 0)
        for issue in issues:
            self.resolved_layout.addWidget(ResolvedIssueCard(issue))
        self.resolved_layout.addStretch(1)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _request_log_issue(self) -> None:
        if self.machine_number:
            self.log_issue_requested.emit(self.machine_number)
