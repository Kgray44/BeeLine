from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.domain import LINE_DOWN, NON_CRITICAL, NO_ISSUES, STATUS_ORDER, MachineSummary
from beeline_issue_tracker.ui.theme import ThemeManager
from beeline_issue_tracker.ui.widgets import BrandHeader, HoneycombBackground, MachineCard, MetricPill, SearchBox, ThemeToggleButton


MIN_CARD_WIDTH = 265


class HiveDashboardPage(HoneycombBackground):
    machine_selected = Signal(str)
    open_issues_requested = Signal()
    predictive_requested = Signal()

    def __init__(self, repository: IssueRepository, theme_manager: ThemeManager, paths: AppPaths, parent=None):
        super().__init__(theme_manager, parent)
        self.repository = repository
        self.theme_manager = theme_manager
        self.paths = paths
        self._machines: list[MachineSummary] = []
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(110)
        self._resize_timer.timeout.connect(self._render_cards)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(24, 22, 24, 22)
        page_layout.setSpacing(18)

        header = QHBoxLayout()
        header.addWidget(BrandHeader("BeeLine Issue Tracker", "Hive Dashboard", paths.logo_path()))
        header.addStretch(1)
        open_issues = QPushButton("View All Open Issues")
        open_issues.setObjectName("primaryButton")
        open_issues.clicked.connect(self.open_issues_requested.emit)
        header.addWidget(open_issues)
        predictive = QPushButton("Predictive Maintenance")
        predictive.setObjectName("primaryButton")
        predictive.clicked.connect(self.predictive_requested.emit)
        header.addWidget(predictive)
        header.addWidget(ThemeToggleButton(theme_manager))
        page_layout.addLayout(header)

        self.summary_panel = QFrame()
        self.summary_panel.setObjectName("infoPanel")
        summary_layout = QHBoxLayout(self.summary_panel)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(10)
        self.total_pill = MetricPill("Total Machines")
        self.open_pill = MetricPill("Open Issues")
        self.line_down_pill = MetricPill("Line Down")
        self.non_critical_pill = MetricPill("Non-Critical")
        self.no_issues_pill = MetricPill("No Issues")
        for pill in (
            self.total_pill,
            self.open_pill,
            self.line_down_pill,
            self.non_critical_pill,
            self.no_issues_pill,
        ):
            summary_layout.addWidget(pill)
        summary_layout.addStretch(1)
        page_layout.addWidget(self.summary_panel)

        controls_panel = QFrame()
        controls_panel.setObjectName("infoPanel")
        controls = QHBoxLayout(controls_panel)
        controls.setContentsMargins(14, 12, 14, 12)
        controls.setSpacing(10)
        self.search = SearchBox("Search machines...")
        self.search.textChanged.connect(self._render_cards)
        self.sort = QComboBox()
        self.sort.setObjectName("compactDropdown")
        for label, value in (
            ("Plant Layout", "plant"),
            ("Severity", "severity"),
            ("Open Issues", "open_issues"),
            ("Machine A-Z", "machine_asc"),
            ("Machine Z-A", "machine_desc"),
        ):
            self.sort.addItem(label, value)
        self.sort.currentIndexChanged.connect(self._render_cards)
        self.area_filter = QComboBox()
        self.area_filter.setObjectName("compactDropdown")
        self.area_filter.currentIndexChanged.connect(self._render_cards)
        self.cell_filter = QComboBox()
        self.cell_filter.setObjectName("compactDropdown")
        self.cell_filter.currentIndexChanged.connect(self._render_cards)
        controls.addWidget(self.search, 1)
        controls.addWidget(QLabel("Sort"))
        controls.addWidget(self.sort)
        controls.addWidget(QLabel("Area"))
        controls.addWidget(self.area_filter)
        controls.addWidget(QLabel("Cell"))
        controls.addWidget(self.cell_filter)
        page_layout.addWidget(controls_panel)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("transparentHost")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(18)
        self.scroll.setWidget(self.grid_host)
        page_layout.addWidget(self.scroll, 1)

    def refresh(self) -> None:
        self._machines = self.repository.list_machines_with_status()
        self._update_summary()
        self._update_filter_options()
        self._render_cards()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_timer.start()

    def _update_summary(self) -> None:
        machines = self._machines
        open_total = sum(machine.open_issue_count for machine in machines)
        line_down_total = sum(1 for machine in machines if machine.calculated_status == LINE_DOWN)
        non_critical_total = sum(1 for machine in machines if machine.calculated_status == NON_CRITICAL)
        no_issues_total = sum(1 for machine in machines if machine.calculated_status == NO_ISSUES)
        self.total_pill.set_value(str(len(machines)))
        self.open_pill.set_value(str(open_total))
        self.line_down_pill.set_value(str(line_down_total))
        self.non_critical_pill.set_value(str(non_critical_total))
        self.no_issues_pill.set_value(str(no_issues_total))

    def _update_filter_options(self) -> None:
        self._set_filter_options(self.area_filter, sorted({m.area for m in self._machines if m.area}))
        self._set_filter_options(self.cell_filter, sorted({m.cell for m in self._machines if m.cell}))

    def _set_filter_options(self, combo: QComboBox, values: list[str]) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("All", "")
        for value in values:
            combo.addItem(value, value)
        next_index = combo.findData(current)
        combo.setCurrentIndex(next_index if next_index >= 0 else 0)
        combo.setVisible(bool(values))
        combo.blockSignals(False)

    def _render_cards(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        machines = self._filtered_machines()
        columns = self._column_count()
        for index, machine in enumerate(machines):
            card = MachineCard(machine)
            card.clicked.connect(self.machine_selected.emit)
            self.grid.addWidget(card, index // columns, index % columns)
        self.grid.setRowStretch((len(machines) // columns) + 1, 1)

    def _filtered_machines(self) -> list[MachineSummary]:
        query = " ".join(self.search.text().casefold().split())
        area = self.area_filter.currentData() or ""
        cell = self.cell_filter.currentData() or ""
        machines = []
        for machine in self._machines:
            if area and machine.area != area:
                continue
            if cell and machine.cell != cell:
                continue
            haystack = " ".join(
                (
                    machine.machine_number,
                    machine.name,
                    machine.area,
                    machine.cell,
                    machine.calculated_status,
                )
            ).casefold()
            if query and not all(term in haystack for term in query.split(" ")):
                continue
            machines.append(machine)

        sort_key = self.sort.currentData() or "plant"
        if sort_key == "severity":
            order = {status: index for index, status in enumerate(STATUS_ORDER)}
            return sorted(machines, key=lambda m: (order.get(m.calculated_status, 99), -m.open_issue_count, m.display_order))
        if sort_key == "open_issues":
            return sorted(machines, key=lambda m: (-m.open_issue_count, m.display_order, m.machine_number))
        if sort_key == "machine_asc":
            return sorted(machines, key=lambda m: m.machine_number.casefold())
        if sort_key == "machine_desc":
            return sorted(machines, key=lambda m: m.machine_number.casefold(), reverse=True)
        return sorted(machines, key=lambda m: (m.display_order, m.machine_number.casefold()))

    def _column_count(self) -> int:
        available = max(1, self.scroll.viewport().width())
        return max(1, available // MIN_CARD_WIDTH)
