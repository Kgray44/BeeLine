from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.ui.theme import ThemeManager
from beeline_issue_tracker.ui.widgets import BrandHeader, HoneycombBackground, MachineCard, ThemeToggleButton


class HiveDashboardPage(HoneycombBackground):
    machine_selected = Signal(str)

    def __init__(self, repository: IssueRepository, theme_manager: ThemeManager, paths: AppPaths, parent=None):
        super().__init__(theme_manager, parent)
        self.repository = repository
        self.theme_manager = theme_manager
        self.paths = paths

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(24, 22, 24, 22)
        page_layout.setSpacing(18)

        header = QHBoxLayout()
        header.addWidget(BrandHeader("BeeLine Issue Tracker", "Hive Dashboard", paths.logo_path()))
        header.addStretch(1)
        header.addWidget(ThemeToggleButton(theme_manager))
        page_layout.addLayout(header)

        self.summary_panel = QFrame()
        self.summary_panel.setObjectName("infoPanel")
        summary_layout = QHBoxLayout(self.summary_panel)
        summary_layout.setContentsMargins(18, 14, 18, 14)
        summary_layout.setSpacing(22)
        self.summary_title = QLabel("Hive Health")
        self.summary_title.setObjectName("sectionTitle")
        self.summary = QLabel()
        self.summary.setObjectName("mutedLabel")
        summary_layout.addWidget(self.summary_title)
        summary_layout.addWidget(self.summary, 1)
        page_layout.addWidget(self.summary_panel)

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
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        machines = self.repository.list_machines_with_status()
        open_total = sum(machine.open_issue_count for machine in machines)
        line_down_total = sum(1 for machine in machines if machine.calculated_status == "Line Down")
        self.summary.setText(
            f"{len(machines)} machines | {open_total} open issues | {line_down_total} line down"
        )

        columns = 4
        for index, machine in enumerate(machines):
            card = MachineCard(machine)
            card.clicked.connect(self.machine_selected.emit)
            self.grid.addWidget(card, index // columns, index % columns)
        self.grid.setRowStretch((len(machines) // columns) + 1, 1)
