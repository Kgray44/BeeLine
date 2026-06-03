from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
from beeline_issue_tracker.domain import ACTIVE_SEVERITIES, Issue, MachineSummary
from beeline_issue_tracker.ui.issue_list_model import DATE_DESC, format_duration_between, format_timestamp, preview_text
from beeline_issue_tracker.ui.theme import ThemeManager
from beeline_issue_tracker.ui.widgets import BrandHeader, HoneycombBackground, LatestCountDropdown, SearchBox, StatusBadge, ThemeToggleButton


class OpenIssuesPage(HoneycombBackground):
    back_requested = Signal()
    machine_requested = Signal(str)
    resolve_issue_requested = Signal(int)
    issue_open_requested = Signal(str, int)

    COLUMNS = (
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

        page = QVBoxLayout(self)
        page.setContentsMargins(24, 22, 24, 22)
        page.setSpacing(16)

        header = QHBoxLayout()
        back = QPushButton("Back to Dashboard")
        back.clicked.connect(self.back_requested.emit)
        header.addWidget(back)
        header.addWidget(BrandHeader("Open Issues", "All active issues across the hive", paths.logo_path()), 1)
        header.addWidget(ThemeToggleButton(theme_manager))
        page.addLayout(header)

        controls_panel = QFrame()
        controls_panel.setObjectName("infoPanel")
        controls = QHBoxLayout(controls_panel)
        controls.setContentsMargins(14, 12, 14, 12)
        controls.setSpacing(9)
        self.search = SearchBox("Search open issues...")
        self.search.textChanged.connect(self.refresh)
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

        self.empty_label = QLabel()
        self.empty_label.setObjectName("mutedLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        page.addWidget(self.empty_label)

        self.table = QTableWidget()
        self.table.setObjectName("issueTable")
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.itemDoubleClicked.connect(self._open_table_item)
        self.table.itemActivated.connect(self._open_table_item)
        page.addWidget(self.table, 1)
        self._configure_table()

    def refresh(self) -> None:
        self._machines = self.repository.list_machines_with_status()
        self._machine_map = {machine.machine_number: machine for machine in self._machines}
        self._update_filter_options()
        issues = self.repository.list_all_active_issues(
            query=self.search.text(),
            severity=self.severity.currentData() or None,
            machine_number=self.machine_filter.currentData() or None,
            area=self.area_filter.currentData() or None,
            cell=self.cell_filter.currentData() or None,
            sort_key=self.sort.currentData() or DATE_DESC,
            limit=self.latest.currentData(),
        )
        self._populate_table(issues)

    def _configure_table(self) -> None:
        header = self.table.horizontalHeader()
        widths = (155, 210, 126, 280, 120, 145, 82, 110, 190)
        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

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

    def _populate_table(self, issues: list[Issue]) -> None:
        self._visible_issues = issues
        self.table.setRowCount(0)
        self.empty_label.setVisible(not issues)
        self.table.setVisible(bool(issues))
        if not issues:
            self.empty_label.setText("No open issues match the current filters.")
            return
        self.table.setRowCount(len(issues))
        for row, issue in enumerate(issues):
            machine = self._machine_map.get(issue.machine_number)
            machine_label = issue.machine_number if machine is None else f"{issue.machine_number} | {machine.name}"
            self.table.setItem(row, 0, self._item(machine_label))
            self.table.setItem(row, 1, self._item(preview_text(issue.title, 64), issue.title))
            self.table.setCellWidget(row, 2, self._centered_widget(StatusBadge(issue.severity)))
            self.table.setItem(row, 3, self._item(preview_text(issue.description, 92), issue.description))
            self.table.setItem(row, 4, self._item(issue.logged_by))
            self.table.setItem(row, 5, self._item(format_timestamp(issue.created_at), issue.created_at))
            self.table.setItem(row, 6, self._item(format_duration_between(issue.created_at)))
            self.table.setItem(row, 7, self._item(issue.category or "-"))
            self.table.setCellWidget(row, 8, self._actions_widget(issue))
            self.table.setRowHeight(row, 54)
        self.table.clearSelection()

    def _actions_widget(self, issue: Issue) -> QWidget:
        host = QWidget()
        host.setObjectName("transparentHost")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(5)
        open_button = QPushButton("Open")
        open_button.setObjectName("tableActionButton")
        open_button.clicked.connect(lambda _checked=False, issue_id=issue.id: self.issue_open_requested.emit("active", issue_id))
        machine_button = QPushButton("Machine")
        machine_button.setObjectName("tableActionButton")
        machine_button.clicked.connect(lambda _checked=False, machine_number=issue.machine_number: self.machine_requested.emit(machine_number))
        resolve_button = QPushButton("Resolve")
        resolve_button.setObjectName("tableActionButton")
        resolve_button.clicked.connect(lambda _checked=False, issue_id=issue.id: self.resolve_issue_requested.emit(issue_id))
        layout.addWidget(open_button)
        layout.addWidget(machine_button)
        layout.addWidget(resolve_button)
        return host

    def _open_table_item(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if row < 0 or row >= len(self._visible_issues):
            return
        self.issue_open_requested.emit("active", self._visible_issues[row].id)

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

