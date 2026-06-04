from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.domain import ACTIVE_SEVERITIES, LINE_DOWN, NON_CRITICAL, Issue, MachineSummary, display_issue_id
from beeline_issue_tracker.perf import elapsed_ms, log as perf_log, now as perf_now
from beeline_issue_tracker.ui_v2.issue_list_model import DATE_DESC, format_duration_between, format_timestamp, preview_text
from beeline_issue_tracker.ui_v2.theme import ThemeManager
from beeline_issue_tracker.ui_v2.widgets import (
    BrandHeader,
    EmptyStatePanel,
    HoneycombBackground,
    LatestCountDropdown,
    MetricPill,
    SearchBox,
    StatusBadge,
)


@dataclass(frozen=True)
class OpenIssuesSnapshot:
    machines: list[MachineSummary]
    issues: list[Issue]


def load_open_issues_snapshot(
    repository: IssueRepository,
    *,
    query: str = "",
    severity: str | None = None,
    machine_number: str | None = None,
    area: str | None = None,
    cell: str | None = None,
    sort_key: str = DATE_DESC,
    limit: int | None = 50,
) -> OpenIssuesSnapshot:
    started_at = perf_now()
    call_started = perf_now()
    machines = repository.list_machines_with_status()
    perf_log("open_issues.list_machines", count=len(machines), elapsed_ms=elapsed_ms(call_started))
    call_started = perf_now()
    issues = repository.list_all_active_issues(
        query=query,
        severity=severity,
        machine_number=machine_number,
        area=area,
        cell=cell,
        sort_key=sort_key,
        limit=limit,
    )
    perf_log("open_issues.list_active", count=len(issues), limit=limit, elapsed_ms=elapsed_ms(call_started))
    perf_log("open_issues.snapshot", elapsed_ms=elapsed_ms(started_at))
    return OpenIssuesSnapshot(machines=machines, issues=issues)


class OpenIssuesPage(HoneycombBackground):
    back_requested = Signal()
    machine_requested = Signal(str)
    resolve_issue_requested = Signal(int)
    issue_open_requested = Signal(str, int)

    COLUMNS = (
        "Issue ID",
        "Machine",
        "Issue Title",
        "Severity",
        "Description",
        "Logged By",
        "Created",
        "Age",
        "Category",
        "Actions",
    )

    def __init__(self, repository: IssueRepository, theme_manager: ThemeManager, paths: AppPaths, parent=None):
        super().__init__(theme_manager, parent)
        self.repository = repository
        self.theme_manager = theme_manager
        self.paths = paths
        self._machines: list[MachineSummary] = []
        self._machine_map: dict[str, MachineSummary] = {}
        self._visible_issues: list[Issue] = []
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self.refresh)

        page = QVBoxLayout(self)
        page.setContentsMargins(24, 22, 24, 22)
        page.setSpacing(16)

        header = QHBoxLayout()
        back = QPushButton("Back to Dashboard")
        back.setObjectName("quietButton")
        back.clicked.connect(self.back_requested.emit)
        header.addWidget(back)
        header.addWidget(BrandHeader("Open Issues", "All active issues across the hive", paths.logo_path(), theme_manager), 1)
        page.addLayout(header)

        controls_panel = QFrame()
        controls_panel.setObjectName("infoPanel")
        controls = QHBoxLayout(controls_panel)
        controls.setContentsMargins(14, 12, 14, 12)
        controls.setSpacing(9)
        self.search = SearchBox("Search open issues...")
        self.search.textChanged.connect(self._queue_search_refresh)
        self.severity = QComboBox()
        self.severity.setObjectName("compactDropdown")
        self.severity.addItem("All Severity", "")
        for severity in ACTIVE_SEVERITIES:
            self.severity.addItem(severity, severity)
        self.severity.currentIndexChanged.connect(self.refresh)
        self.machine_filter = QComboBox()
        self.machine_filter.setObjectName("compactDropdown")
        self.machine_filter.currentIndexChanged.connect(self.refresh)
        self.area_label = QLabel("Area")
        self.area_filter = QComboBox()
        self.area_filter.setObjectName("compactDropdown")
        self.area_filter.currentIndexChanged.connect(self.refresh)
        self.cell_label = QLabel("Cell")
        self.cell_filter = QComboBox()
        self.cell_filter.setObjectName("compactDropdown")
        self.cell_filter.currentIndexChanged.connect(self.refresh)
        self.sort = QComboBox()
        self.sort.setObjectName("compactDropdown")
        for label, value in (
            ("Newest First", "date_desc"),
            ("Oldest First", "date_asc"),
            ("Issue ID A-Z", "issue_id_asc"),
            ("Issue ID Z-A", "issue_id_desc"),
            ("Title A-Z", "title_asc"),
            ("Title Z-A", "title_desc"),
            ("Severity", "severity"),
        ):
            self.sort.addItem(label, value)
        self.sort.setCurrentIndex(self.sort.findData(DATE_DESC))
        self.sort.currentIndexChanged.connect(self.refresh)
        self.latest = LatestCountDropdown(50)
        self.latest.currentIndexChanged.connect(self.refresh)

        controls.addWidget(self.search, 1)
        controls.addWidget(self.severity)
        controls.addWidget(self.machine_filter)
        controls.addWidget(self.area_label)
        controls.addWidget(self.area_filter)
        controls.addWidget(self.cell_label)
        controls.addWidget(self.cell_filter)
        controls.addWidget(self.sort)
        controls.addWidget(self.latest)
        page.addWidget(controls_panel)

        self.summary_panel = QFrame()
        self.summary_panel.setObjectName("infoPanel")
        summary = QHBoxLayout(self.summary_panel)
        summary.setContentsMargins(14, 12, 14, 12)
        summary.setSpacing(10)
        self.total_open_pill = MetricPill("Total Open")
        self.line_down_pill = MetricPill("Line Down")
        self.non_critical_pill = MetricPill("Non-Critical")
        self.machines_affected_pill = MetricPill("Machines Affected")
        self.oldest_open_pill = MetricPill("Oldest Open")
        for pill in (
            self.total_open_pill,
            self.line_down_pill,
            self.non_critical_pill,
            self.machines_affected_pill,
            self.oldest_open_pill,
        ):
            summary.addWidget(pill)
        summary.addStretch(1)
        page.addWidget(self.summary_panel)

        self.empty_panel = EmptyStatePanel()
        page.addWidget(self.empty_panel)

        self.table = QTableWidget()
        self.table.setObjectName("issueTable")
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.itemDoubleClicked.connect(self._open_table_item)
        self.table.itemActivated.connect(self._open_table_item)
        page.addWidget(self.table, 1)
        self._configure_table()

    def refresh(self) -> None:
        self.apply_snapshot(load_open_issues_snapshot(self.repository, **self.current_query()))

    def show_loading(self) -> None:
        self.empty_panel.setVisible(True)
        self.empty_panel.set_text("Loading open issues", "BeeLine is fetching the current active issue list.")
        self.table.setVisible(False)
        self._adjust_table_height(0)
        self._visible_issues = []

    def current_query(self) -> dict[str, object]:
        return {
            "query": self.search.text(),
            "severity": self.severity.currentData() or None,
            "machine_number": self.machine_filter.currentData() or None,
            "area": self.area_filter.currentData() or None,
            "cell": self.cell_filter.currentData() or None,
            "sort_key": self.sort.currentData() or DATE_DESC,
            "limit": self.latest.currentData(),
        }

    def apply_snapshot(self, snapshot: OpenIssuesSnapshot) -> None:
        self._machines = list(snapshot.machines)
        self._machine_map = {machine.machine_number: machine for machine in self._machines}
        self._update_filter_options()
        issues = list(snapshot.issues)
        self._update_summary(issues)
        self._populate_table(issues)

    def _configure_table(self) -> None:
        header = self.table.horizontalHeader()
        widths = (150, 190, 210, 126, 280, 120, 145, 82, 110, 240)
        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

    def _update_filter_options(self) -> None:
        self._set_combo_options(
            self.machine_filter,
            [(f"{m.machine_number} | {m.name}", m.machine_number) for m in self._machines],
            "All Machines",
        )
        self._set_combo_options(
            self.area_filter,
            [(value, value) for value in sorted({m.area for m in self._machines if m.area})],
            "All",
        )
        self._set_combo_options(
            self.cell_filter,
            [(value, value) for value in sorted({m.cell for m in self._machines if m.cell})],
            "All",
        )
        self.area_label.setVisible(self.area_filter.count() > 1)
        self.area_filter.setVisible(self.area_filter.count() > 1)
        self.cell_label.setVisible(self.cell_filter.count() > 1)
        self.cell_filter.setVisible(self.cell_filter.count() > 1)

    def _set_combo_options(self, combo: QComboBox, values: list[tuple[str, str]], all_label: str) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(all_label, "")
        for label, value in values:
            combo.addItem(label, value)
        next_index = combo.findData(current)
        combo.setCurrentIndex(next_index if next_index >= 0 else 0)
        combo.blockSignals(False)

    def _update_summary(self, issues: list[Issue]) -> None:
        self.total_open_pill.set_value(str(len(issues)))
        self.line_down_pill.set_value(str(sum(1 for issue in issues if issue.severity == LINE_DOWN)))
        self.non_critical_pill.set_value(str(sum(1 for issue in issues if issue.severity == NON_CRITICAL)))
        self.machines_affected_pill.set_value(str(len({issue.machine_number for issue in issues})))
        oldest = min((issue.created_at for issue in issues if issue.created_at), default="")
        self.oldest_open_pill.set_value(format_duration_between(oldest) if oldest else "-")

    def _populate_table(self, issues: list[Issue]) -> None:
        started_at = perf_now()
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self._visible_issues = issues
            self.table.setRowCount(0)
            self.empty_panel.setVisible(not issues)
            self.table.setVisible(bool(issues))
            if not issues:
                if self.search.text().strip():
                    self.empty_panel.set_text(
                        "No matching issues found",
                        "Try a different keyword, machine number, category, or status.",
                    )
                else:
                    self.empty_panel.set_text("No open issues", "The hive is clear right now.")
                self._adjust_table_height(0)
                return
            self.table.setRowCount(len(issues))
            for row, issue in enumerate(issues):
                machine = self._machine_map.get(issue.machine_number)
                machine_label = issue.machine_number if machine is None else f"{issue.machine_number}\n{machine.name}"
                machine_tooltip = issue.machine_number if machine is None else f"{issue.machine_number} | {machine.name}"
                self.table.setItem(row, 0, self._item(display_issue_id(issue)))
                self.table.setItem(row, 1, self._item(machine_label, machine_tooltip))
                self.table.setItem(row, 2, self._item(preview_text(issue.title, 64), issue.title))
                self.table.setCellWidget(row, 3, self._centered_widget(StatusBadge(issue.severity)))
                self.table.setItem(row, 4, self._item(preview_text(issue.description, 92), issue.description))
                self.table.setItem(row, 5, self._item(issue.logged_by))
                self.table.setItem(row, 6, self._item(format_timestamp(issue.created_at), issue.created_at))
                self.table.setItem(row, 7, self._item(format_duration_between(issue.created_at)))
                self.table.setItem(row, 8, self._item(issue.category or "-", issue.category or None))
                self.table.setCellWidget(row, 9, self._actions_widget(issue))
                self.table.setRowHeight(row, 60)
            self.table.clearSelection()
            self._adjust_table_height(len(issues))
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
            perf_log("open_issues.render_table", rows=len(issues), elapsed_ms=elapsed_ms(started_at))

    def _adjust_table_height(self, visible_count: int) -> None:
        if visible_count <= 0:
            self.table.setMinimumHeight(0)
            self.table.setMaximumHeight(0)
            return
        header_height = self.table.horizontalHeader().height() or 38
        row_height = 60
        padding = 14
        visible_rows = min(visible_count, 6)
        height = header_height + visible_rows * row_height + padding
        self.table.setMinimumHeight(height)
        self.table.setMaximumHeight(height if visible_count <= 3 else 16777215)

    def _queue_search_refresh(self) -> None:
        self._search_timer.start()

    def _actions_widget(self, issue: Issue) -> QWidget:
        host = QWidget()
        host.setObjectName("transparentHost")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(5)
        open_button = QPushButton("Open")
        open_button.setObjectName("tableActionButton")
        open_button.clicked.connect(lambda _checked=False, issue_id=issue.id: self.issue_open_requested.emit("active", issue_id))
        resolve_button = QPushButton("Resolve")
        resolve_button.setObjectName("tableActionButton")
        resolve_button.clicked.connect(lambda _checked=False, issue_id=issue.id: self.resolve_issue_requested.emit(issue_id))
        layout.addWidget(open_button)
        layout.addWidget(resolve_button)
        return host

    def _open_table_item(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if row < 0 or row >= len(self._visible_issues):
            return
        issue = self._visible_issues[row]
        if item.column() == 1:
            self.machine_requested.emit(issue.machine_number)
            return
        self.issue_open_requested.emit("active", issue.id)

    @staticmethod
    def _item(text: str, tooltip: str | None = None) -> QTableWidgetItem:
        item = QTableWidgetItem(text or "-")
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if tooltip:
            item.setToolTip(tooltip)
        return item

    @staticmethod
    def _centered_widget(widget: QWidget) -> QWidget:
        host = QWidget()
        host.setObjectName("transparentHost")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.addStretch(1)
        layout.addWidget(widget)
        layout.addStretch(1)
        return host
