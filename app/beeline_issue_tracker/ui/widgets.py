from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from beeline_issue_tracker.domain import Issue, MachineSummary, ResolvedIssue
from beeline_issue_tracker.ui.issue_list_model import (
    DATE_DESC,
    LATEST_OPTIONS,
    SORT_OPTIONS,
    filter_issues,
    format_duration_between,
    format_timestamp,
    prepare_issue_rows,
    preview_text,
)
from beeline_issue_tracker.ui.theme import DARK_THEME, ThemeManager, repolish, status_state, theme_from_name


class BrandHeader(QWidget):
    def __init__(self, title: str, subtitle: str, logo_path: Path | None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        logo = QLabel("BeeLine")
        logo.setObjectName("brandText")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setMinimumSize(88, 46)
        logo.setMaximumHeight(52)
        if logo_path is not None:
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                logo.setText("")
                logo.setPixmap(
                    pixmap.scaled(
                        120,
                        46,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        layout.addWidget(logo)

        text_block = QVBoxLayout()
        text_block.setContentsMargins(0, 0, 0, 0)
        text_block.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("pageTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("subtitleLabel")
        text_block.addWidget(self.title_label)
        text_block.addWidget(self.subtitle_label)
        layout.addLayout(text_block)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        self.subtitle_label.setText(subtitle)


class HoneycombBackground(QWidget):
    def __init__(self, theme_manager: ThemeManager | None = None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        if self.theme_manager is not None:
            self.theme_manager.theme_changed.connect(lambda _theme: self.update())

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        theme = (
            self.theme_manager.current_theme
            if self.theme_manager is not None
            else theme_from_name(DARK_THEME)
        )
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(theme.accent)
        accent.setAlpha(theme.honeycomb_alpha)
        pen = QPen(accent, 1)
        painter.setPen(pen)

        radius = 34
        width = math.sqrt(3) * radius
        height = 2 * radius
        row_gap = height * 0.75

        clusters = (
            (self.width() - 250, 42, 4, 5),
            (-72, max(180, self.height() - 250), 4, 4),
        )
        for origin_x, origin_y, rows, cols in clusters:
            for row in range(rows):
                y = origin_y + row * row_gap
                x_offset = 0 if row % 2 == 0 else width / 2
                for col in range(cols):
                    x = origin_x + col * width + x_offset
                    if (row + col) % 2 == 0:
                        self._draw_hexagon(painter, x, y, radius)

    @staticmethod
    def _draw_hexagon(painter: QPainter, cx: float, cy: float, radius: int) -> None:
        points = []
        for index in range(6):
            angle = math.radians(60 * index - 30)
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        for start, end in zip(points, points[1:] + points[:1]):
            painter.drawLine(int(start[0]), int(start[1]), int(end[0]), int(end[1]))


class StatusBadge(QLabel):
    def __init__(self, status: str, parent=None):
        super().__init__(status, parent)
        self.setObjectName("statusBadge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(30)
        self.set_status(status)

    def set_status(self, status: str) -> None:
        self.setText(status)
        self.setProperty("statusState", status_state(status))
        repolish(self)


class ThemeToggleButton(QPushButton):
    def __init__(self, theme_manager: ThemeManager, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.setObjectName("themeToggleButton")
        self.clicked.connect(self.theme_manager.toggle_theme)
        self.theme_manager.theme_changed.connect(lambda _theme: self._refresh_label())
        self._refresh_label()

    def _refresh_label(self) -> None:
        next_theme = "Light Mode" if self.theme_manager.current_theme_name == DARK_THEME else "Dark Mode"
        self.setText(next_theme)


class MachineCard(QFrame):
    clicked = Signal(str)

    def __init__(self, machine: MachineSummary, parent=None):
        super().__init__(parent)
        self.machine = machine
        self.setObjectName("machineCard")
        self.setProperty("statusState", status_state(machine.calculated_status))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumSize(250, 165)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        number = QLabel(f"Machine {machine.machine_number}")
        number.setObjectName("machineNumber")
        number.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(number)

        name = QLabel(machine.name)
        name.setObjectName("mutedLabel")
        name.setWordWrap(True)
        layout.addWidget(name)

        location_text = " | ".join(part for part in (machine.area, machine.cell) if part)
        if location_text:
            location = QLabel(location_text)
            location.setObjectName("mutedLabel")
            location.setWordWrap(True)
            layout.addWidget(location)

        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.addWidget(StatusBadge(machine.calculated_status))
        open_count = QLabel(f"{machine.open_issue_count} open")
        open_count.setObjectName("openCount")
        open_count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        footer.addWidget(open_count, 1)
        layout.addLayout(footer)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.machine.machine_number)
        super().mousePressEvent(event)


class InfoRow(QWidget):
    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        key = QLabel(label)
        key.setObjectName("mutedLabel")
        key.setMinimumWidth(115)
        val = QLabel(value or "-")
        val.setWordWrap(True)
        layout.addWidget(key)
        layout.addWidget(val, 1)


class MetricPill(QFrame):
    def __init__(self, label: str, value: str = "-", parent=None):
        super().__init__(parent)
        self.setObjectName("metricPill")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(1)

        label_widget = QLabel(label)
        label_widget.setObjectName("metricLabel")
        self.value_widget = QLabel(value)
        self.value_widget.setObjectName("metricValue")
        layout.addWidget(label_widget)
        layout.addWidget(self.value_widget)

    def set_value(self, value: str) -> None:
        self.value_widget.setText(value or "-")


class PrimaryActionButton(QPushButton):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("primaryButton")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))


class SearchBox(QLineEdit):
    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self.setObjectName("searchBox")
        self.setClearButtonEnabled(True)
        self.setPlaceholderText(placeholder)
        self.setMinimumHeight(38)


class SortDropdown(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("compactDropdown")
        for label, value in SORT_OPTIONS:
            self.addItem(label, value)
        self.setMinimumHeight(38)
        self.setCurrentIndex(self.findData(DATE_DESC))


class LatestCountDropdown(QComboBox):
    def __init__(self, default_limit: int | None = 10, parent=None):
        super().__init__(parent)
        self.setObjectName("compactDropdown")
        for label, value in LATEST_OPTIONS:
            self.addItem(label, value)
        self.setMinimumHeight(38)
        self.setCurrentIndex(self.findData(default_limit))


class IssueListToolbar(QWidget):
    controls_changed = Signal()
    log_issue_requested = Signal()

    def __init__(
        self,
        title: str,
        search_placeholder: str,
        *,
        show_log_action: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        self.count_label = QLabel()
        self.count_label.setObjectName("mutedLabel")
        header.addWidget(title_label)
        header.addWidget(self.count_label)
        header.addStretch(1)
        if show_log_action:
            self.log_button = PrimaryActionButton("Report Problem")
            self.log_button.setObjectName("sectionPrimaryButton")
            self.log_button.clicked.connect(self.log_issue_requested.emit)
            header.addWidget(self.log_button)
        layout.addLayout(header)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.search = SearchBox(search_placeholder)
        self.search.textChanged.connect(self.controls_changed.emit)
        self.sort = SortDropdown()
        self.sort.currentIndexChanged.connect(self.controls_changed.emit)
        self.latest = LatestCountDropdown(10)
        self.latest.currentIndexChanged.connect(self.controls_changed.emit)
        self.display_mode = QComboBox()
        self.display_mode.setObjectName("compactDropdown")
        self.display_mode.addItem("Table", "table")
        self.display_mode.addItem("Kiosk", "kiosk")
        self.display_mode.setMinimumHeight(38)
        self.display_mode.currentIndexChanged.connect(self.controls_changed.emit)

        sort_label = QLabel("Sort")
        sort_label.setObjectName("controlLabel")
        show_label = QLabel("Show")
        show_label.setObjectName("controlLabel")
        mode_label = QLabel("Mode")
        mode_label.setObjectName("controlLabel")

        controls.addWidget(self.search, 1)
        controls.addWidget(sort_label)
        controls.addWidget(self.sort)
        controls.addWidget(show_label)
        controls.addWidget(self.latest)
        controls.addWidget(mode_label)
        controls.addWidget(self.display_mode)
        layout.addLayout(controls)

    def update_count(self, shown: int, matched: int, total: int) -> None:
        if total == 0:
            text = "No issues"
        elif shown == matched == total:
            text = f"{shown} shown"
        else:
            text = f"{shown} of {matched} matched | {total} total"
        self.count_label.setText(text)


class IssueListView(QFrame):
    resolve_requested = Signal(int)
    log_issue_requested = Signal()
    detail_requested = Signal(int, str)
    open_requested = Signal(str, int)
    criteria_changed = Signal()

    ACTIVE_COLUMNS = (
        "Issue Title",
        "Status",
        "Problem Description",
        "Logged By",
        "Created",
        "Age",
        "Category",
        "Actions",
    )
    RESOLVED_COLUMNS = (
        "Issue Title",
        "Status When Logged",
        "Problem Description",
        "Solution",
        "Logged By",
        "Resolved By",
        "Resolved",
        "Time Open",
        "Category",
        "Action",
    )

    def __init__(self, mode: str, title: str, search_placeholder: str, *, show_log_action: bool = False, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.include_resolved_fields = mode == "resolved"
        self._issues: list[Issue | ResolvedIssue] = []
        self._visible_table_issues: list[Issue | ResolvedIssue] = []
        self.setObjectName("listPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)

        self.toolbar = IssueListToolbar(
            title,
            search_placeholder,
            show_log_action=show_log_action,
        )
        self.toolbar.controls_changed.connect(self._handle_controls_changed)
        self.toolbar.log_issue_requested.connect(self.log_issue_requested.emit)
        layout.addWidget(self.toolbar)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("mutedLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumHeight(46)
        layout.addWidget(self.empty_label)

        self.table = QTableWidget()
        self.table.setObjectName("issueTable")
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.itemDoubleClicked.connect(self._open_table_item)
        self.table.itemActivated.connect(self._open_table_item)
        layout.addWidget(self.table, 1)

        self.card_scroll = QScrollArea()
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.card_host = QWidget()
        self.card_host.setObjectName("transparentHost")
        self.card_layout = QVBoxLayout(self.card_host)
        self.card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_layout.setSpacing(10)
        self.card_scroll.setWidget(self.card_host)
        layout.addWidget(self.card_scroll, 1)
        self.card_scroll.hide()

        self._configure_columns()

    def set_issues(self, issues: list[Issue | ResolvedIssue]) -> None:
        self._issues = list(issues)
        self._refresh_view()

    def criteria(self) -> tuple[str, str, int | None]:
        return (
            self.toolbar.search.text(),
            self.toolbar.sort.currentData() or DATE_DESC,
            self.toolbar.latest.currentData(),
        )

    def _handle_controls_changed(self) -> None:
        self.criteria_changed.emit()
        self._refresh_view()

    def _configure_columns(self) -> None:
        columns = self.RESOLVED_COLUMNS if self.include_resolved_fields else self.ACTIVE_COLUMNS
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(74)
        header.setDefaultSectionSize(128)
        header.setStretchLastSection(False)

        for column in range(len(columns)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)

        if self.include_resolved_fields:
            widths = (170, 142, 220, 220, 110, 110, 142, 92, 100, 94)
            stretch_columns = (2, 3)
        else:
            widths = (190, 118, 260, 112, 142, 78, 100, 154)
            stretch_columns = (2,)

        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)
        for column in stretch_columns:
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

    def _refresh_view(self) -> None:
        query, sort_key, latest_limit = self.criteria()

        matched = filter_issues(
            self._issues,
            query=query,
            include_resolved_fields=self.include_resolved_fields,
        )
        visible = prepare_issue_rows(
            self._issues,
            query=query,
            sort_key=sort_key,
            latest_limit=latest_limit,
            include_resolved_fields=self.include_resolved_fields,
        )

        self.toolbar.update_count(len(visible), len(matched), len(self._issues))
        self._clear_cards()
        self.table.setRowCount(0)
        self._visible_table_issues = []
        self.empty_label.setVisible(len(visible) == 0)
        self.table.setVisible(False)
        self.card_scroll.setVisible(False)
        if len(visible) == 0:
            self.empty_label.setText(self._empty_text(has_query=bool(query.strip())))
            return

        if self.toolbar.display_mode.currentData() == "kiosk":
            self._populate_cards(visible)
            self.card_scroll.setVisible(True)
            return

        self.table.setVisible(True)
        self._populate_table(visible)

    def _populate_table(self, visible: list[Issue | ResolvedIssue]) -> None:
        self.table.setRowCount(0)
        self._visible_table_issues = visible
        self.table.setRowCount(len(visible))
        for row, issue in enumerate(visible):
            if self.include_resolved_fields and isinstance(issue, ResolvedIssue):
                self._populate_resolved_row(row, issue)
            elif isinstance(issue, Issue):
                self._populate_active_row(row, issue)
            self.table.setRowHeight(row, 54)
        self.table.clearSelection()

    def _populate_cards(self, visible: list[Issue | ResolvedIssue]) -> None:
        for issue in visible:
            if isinstance(issue, ResolvedIssue):
                card = ResolvedIssueCard(issue)
                card.detail_requested.connect(lambda issue_id=issue.id: self._emit_open("resolved", issue_id))
            elif isinstance(issue, Issue):
                card = IssueCard(issue)
                card.resolve_requested.connect(self.resolve_requested.emit)
                card.detail_requested.connect(lambda issue_id=issue.id: self._emit_open("active", issue_id))
            else:
                continue
            self.card_layout.addWidget(card)
        self.card_layout.addStretch(1)

    def _populate_active_row(self, row: int, issue: Issue) -> None:
        self.table.setItem(row, 0, self._item(preview_text(issue.title, 64), issue.title))
        self.table.setCellWidget(row, 1, self._centered_widget(StatusBadge(issue.severity)))
        self.table.setItem(row, 2, self._item(preview_text(issue.description, 92), issue.description))
        self.table.setItem(row, 3, self._item(issue.logged_by))
        self.table.setItem(row, 4, self._item(format_timestamp(issue.created_at), issue.created_at))
        self.table.setItem(row, 5, self._item(format_duration_between(issue.created_at)))
        self.table.setItem(row, 6, self._item(issue.category or "-"))

        view_button = QPushButton("Open")
        view_button.setObjectName("tableActionButton")
        view_button.clicked.connect(lambda _checked=False, issue_id=issue.id: self._emit_open("active", issue_id))
        resolve_button = QPushButton("Resolve")
        resolve_button.setObjectName("tableActionButton")
        resolve_button.clicked.connect(lambda _checked=False, issue_id=issue.id: self.resolve_requested.emit(issue_id))
        self.table.setCellWidget(row, 7, self._action_widget(view_button, resolve_button))

    def _populate_resolved_row(self, row: int, issue: ResolvedIssue) -> None:
        self.table.setItem(row, 0, self._item(preview_text(issue.title, 58), issue.title))
        self.table.setCellWidget(row, 1, self._centered_widget(StatusBadge(issue.severity)))
        self.table.setItem(row, 2, self._item(preview_text(issue.description, 86), issue.description))
        self.table.setItem(row, 3, self._item(preview_text(issue.solution, 86), issue.solution))
        self.table.setItem(row, 4, self._item(issue.logged_by))
        self.table.setItem(row, 5, self._item(issue.resolved_by or "-"))
        self.table.setItem(row, 6, self._item(format_timestamp(issue.resolved_at), issue.resolved_at))
        self.table.setItem(row, 7, self._item(format_duration_between(issue.created_at, issue.resolved_at)))
        self.table.setItem(row, 8, self._item(issue.category or "-"))
        view_button = QPushButton("Open")
        view_button.setObjectName("tableActionButton")
        view_button.clicked.connect(lambda _checked=False, issue_id=issue.id: self._emit_open("resolved", issue_id))
        self.table.setCellWidget(row, 9, self._centered_widget(view_button))

    def _open_table_item(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if row < 0 or row >= len(self._visible_table_issues):
            return
        issue = self._visible_table_issues[row]
        if isinstance(issue, ResolvedIssue):
            self._emit_open("resolved", issue.id)
        else:
            self._emit_open("active", issue.id)

    def _emit_open(self, mode: str, issue_id: int) -> None:
        self.open_requested.emit(mode, issue_id)
        self.detail_requested.emit(issue_id, mode)

    def _empty_text(self, *, has_query: bool) -> str:
        if has_query:
            return "No issues match the current search."
        if self.include_resolved_fields:
            return "No recently resolved issues."
        return "No active issues."

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
        layout.setSpacing(0)
        layout.addStretch(1)
        layout.addWidget(widget)
        layout.addStretch(1)
        return host

    @staticmethod
    def _action_widget(*widgets: QWidget) -> QWidget:
        host = QWidget()
        host.setObjectName("transparentHost")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(5)
        layout.addStretch(1)
        for widget in widgets:
            layout.addWidget(widget)
        layout.addStretch(1)
        return host

    def _clear_cards(self) -> None:
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()


class IssueCard(QFrame):
    resolve_requested = Signal(int)
    detail_requested = Signal(int)

    def __init__(self, issue: Issue, parent=None):
        super().__init__(parent)
        self.issue = issue
        self.setObjectName("issueCard")
        self.setProperty("statusState", status_state(issue.severity))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel(issue.title)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        top.addWidget(StatusBadge(issue.severity))
        layout.addLayout(top)

        description = QLabel(issue.description)
        description.setWordWrap(True)
        layout.addWidget(description)

        meta_parts = [f"Logged by {issue.logged_by}", issue.created_at]
        if issue.category:
            meta_parts.insert(1, issue.category)
        meta = QLabel(" | ".join(meta_parts))
        meta.setObjectName("mutedLabel")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        actions = QHBoxLayout()
        actions.addStretch(1)
        detail_button = QPushButton("View Details")
        detail_button.setObjectName("tableActionButton")
        detail_button.clicked.connect(lambda: self.detail_requested.emit(issue.id))
        resolve_button = QPushButton("Resolve Issue")
        resolve_button.setObjectName("resolveButton")
        resolve_button.clicked.connect(lambda: self.resolve_requested.emit(issue.id))
        actions.addWidget(detail_button)
        actions.addWidget(resolve_button)
        layout.addLayout(actions)


class ResolvedIssueCard(QFrame):
    detail_requested = Signal(int)

    def __init__(self, issue: ResolvedIssue, parent=None):
        super().__init__(parent)
        self.issue = issue
        self.setObjectName("issueCard")
        self.setProperty("archiveState", "resolved")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title = QLabel(issue.title)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        solution = QLabel(f"Fix: {issue.solution}")
        solution.setWordWrap(True)
        layout.addWidget(solution)

        archive_note = ""
        if issue.archive_status == "pending":
            archive_note = " | Archive pending"
        elif issue.archive_status == "archive_error":
            archive_note = " | Archive needs attention"

        meta = QLabel(f"Resolved {issue.resolved_at} | {issue.severity}{archive_note}")
        meta.setObjectName("mutedLabel")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        actions = QHBoxLayout()
        actions.addStretch(1)
        detail_button = QPushButton("View Details")
        detail_button.setObjectName("tableActionButton")
        detail_button.clicked.connect(lambda: self.detail_requested.emit(issue.id))
        actions.addWidget(detail_button)
        layout.addLayout(actions)
