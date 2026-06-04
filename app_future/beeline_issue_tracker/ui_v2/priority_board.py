from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
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
from beeline_issue_tracker.future_features import PriorityIssue
from beeline_issue_tracker.perf import elapsed_ms, log as perf_log, now as perf_now
from beeline_issue_tracker.ui_v2.issue_list_model import preview_text
from beeline_issue_tracker.ui_v2.theme import ThemeManager
from beeline_issue_tracker.ui_v2.widgets import BrandHeader, EmptyStatePanel, HoneycombBackground, StatusBadge
from beeline_issue_tracker.domain import display_issue_id


@dataclass(frozen=True)
class PriorityBoardSnapshot:
    rows: list[PriorityIssue]


def load_priority_board_snapshot(repository: IssueRepository) -> PriorityBoardSnapshot:
    started_at = perf_now()
    rows = repository.list_priority_issues(limit=50)
    perf_log("priority_board.load", rows=len(rows), limit=50, elapsed_ms=elapsed_ms(started_at))
    return PriorityBoardSnapshot(rows=rows)


class PriorityBoardPage(HoneycombBackground):
    back_requested = Signal()
    refresh_requested = Signal()
    issue_open_requested = Signal(str, int)
    machine_requested = Signal(str)

    COLUMNS = (
        "Priority",
        "Issue ID",
        "Machine",
        "Severity",
        "Age",
        "Flag",
        "Category",
        "Title",
        "Actions",
    )

    def __init__(self, theme_manager: ThemeManager, paths: AppPaths, parent=None):
        super().__init__(theme_manager, parent)
        self.theme_manager = theme_manager
        self.paths = paths
        self._rows: list[PriorityIssue] = []

        page = QVBoxLayout(self)
        page.setContentsMargins(24, 22, 24, 22)
        page.setSpacing(16)

        header = QHBoxLayout()
        back = QPushButton("Back")
        back.setObjectName("quietButton")
        back.clicked.connect(self.back_requested.emit)
        header.addWidget(back)
        header.addWidget(
            BrandHeader("Priority Board", "Most urgent active issues", paths.logo_path(), theme_manager),
            1,
        )
        refresh = QPushButton("Refresh")
        refresh.setObjectName("secondaryButton")
        refresh.clicked.connect(self.refresh_requested.emit)
        header.addWidget(refresh)
        page.addLayout(header)

        note = QLabel("Limited to 50 active issues. Loads only when opened or refreshed.")
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        page.addWidget(note)

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

    def show_loading(self) -> None:
        self._rows = []
        self.empty_panel.setVisible(True)
        self.empty_panel.set_text("Loading priority board", "BeeLine Future is ranking active issues.")
        self.table.setVisible(False)
        self.table.setRowCount(0)

    def apply_snapshot(self, snapshot: PriorityBoardSnapshot) -> None:
        self._rows = list(snapshot.rows)
        self._populate_table(self._rows)

    def _configure_table(self) -> None:
        widths = (82, 150, 190, 126, 82, 132, 120, 320, 220)
        header = self.table.horizontalHeader()
        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)

    def _populate_table(self, rows: list[PriorityIssue]) -> None:
        started_at = perf_now()
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            self.empty_panel.setVisible(not rows)
            self.table.setVisible(bool(rows))
            if not rows:
                self.empty_panel.set_text("No active issues", "There is nothing waiting for attention right now.")
                return

            self.table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                issue = row.issue
                machine_label = f"{issue.machine_number}\n{row.machine_name}" if row.machine_name else issue.machine_number
                self.table.setItem(row_index, 0, self._item(row.priority))
                self.table.setItem(row_index, 1, self._item(display_issue_id(issue)))
                self.table.setItem(row_index, 2, self._item(machine_label))
                self.table.setCellWidget(row_index, 3, self._centered_widget(StatusBadge(issue.severity)))
                self.table.setItem(row_index, 4, self._item(row.age.label))
                self.table.setItem(row_index, 5, self._item(row.age.state))
                self.table.setItem(row_index, 6, self._item(issue.category or "-"))
                self.table.setItem(row_index, 7, self._item(preview_text(issue.title, 100), issue.title))
                self.table.setCellWidget(row_index, 8, self._actions_widget(issue.id, issue.machine_number))
                self.table.setRowHeight(row_index, 58)
            self.table.clearSelection()
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
            perf_log("priority_board.render", rows=len(rows), elapsed_ms=elapsed_ms(started_at))

    def _actions_widget(self, issue_id: int, machine_number: str) -> QWidget:
        host = QWidget()
        host.setObjectName("transparentHost")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        open_button = QPushButton("Open Issue")
        open_button.setObjectName("tableActionButton")
        open_button.clicked.connect(lambda _checked=False, value=issue_id: self.issue_open_requested.emit("active", value))
        machine_button = QPushButton("Machine")
        machine_button.setObjectName("tableActionButton")
        machine_button.clicked.connect(lambda _checked=False, value=machine_number: self.machine_requested.emit(value))
        layout.addWidget(open_button)
        layout.addWidget(machine_button)
        return host

    def _open_table_item(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if row < 0 or row >= len(self._rows):
            return
        priority_issue = self._rows[row]
        if item.column() == 2:
            self.machine_requested.emit(priority_issue.issue.machine_number)
            return
        self.issue_open_requested.emit("active", priority_issue.issue.id)

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
