from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from beeline_issue_tracker.domain import Issue, MachineSummary, ResolvedIssue
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
        self.setMinimumSize(230, 155)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        number = QLabel(f"Machine {machine.machine_number}")
        number.setObjectName("machineNumber")
        number.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(number)

        name = QLabel(machine.name)
        name.setObjectName("mutedLabel")
        layout.addWidget(name)

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


class IssueCard(QFrame):
    resolve_requested = Signal(int)

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
        resolve_button = QPushButton("Resolve Issue")
        resolve_button.setObjectName("resolveButton")
        resolve_button.clicked.connect(lambda: self.resolve_requested.emit(issue.id))
        actions.addWidget(resolve_button)
        layout.addLayout(actions)


class ResolvedIssueCard(QFrame):
    def __init__(self, issue: ResolvedIssue, parent=None):
        super().__init__(parent)
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
