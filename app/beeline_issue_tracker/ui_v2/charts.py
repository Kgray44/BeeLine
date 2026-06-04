from __future__ import annotations

"""Small Qt-native charts for local predictive maintenance views."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from beeline_issue_tracker.analytics.models import (
    MachineTrendPoint,
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_STABLE,
    RISK_UNKNOWN,
)
from beeline_issue_tracker.ui_v2.theme import DARK_THEME, ThemeManager, theme_from_name


def trend_issue_values(trend: list[MachineTrendPoint]) -> tuple[list[str], list[int]]:
    return ([point.period_label for point in trend], [point.open_count + point.resolved_count for point in trend])


def normalize_chart_values(values: list[int]) -> list[float]:
    if not values:
        return []
    maximum = max(values)
    if maximum <= 0:
        return [0.0 for _value in values]
    return [value / maximum for value in values]


def risk_level_color(risk_level: str) -> str:
    return {
        RISK_CRITICAL: "#d64545",
        RISK_HIGH: "#e16d2f",
        RISK_MEDIUM: "#f4c542",
        "Moderate": "#f4c542",
        RISK_LOW: "#33b56b",
        RISK_STABLE: "#33b56b",
        RISK_UNKNOWN: "#8a929a",
    }.get(risk_level, "#8a929a")


class LineTrendChart(QWidget):
    def __init__(self, theme_manager: ThemeManager | None = None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.title = "Trend"
        self.labels: list[str] = []
        self.values: list[int] = []
        self.setMinimumHeight(190)
        if self.theme_manager is not None:
            self.theme_manager.theme_changed.connect(lambda _theme: self.update())

    def set_points(self, title: str, labels: list[str], values: list[int]) -> None:
        self.title = title
        self.labels = list(labels)
        self.values = list(values)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        tokens = _tokens(self.theme_manager)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(tokens.panel))
        painter.setPen(QColor(tokens.text_primary))
        painter.drawText(12, 24, self.title)

        plot = QRectF(36, 42, max(1, self.width() - 52), max(1, self.height() - 74))
        painter.setPen(QPen(QColor(tokens.border), 1))
        painter.drawRect(plot)
        if not self.values:
            painter.setPen(QColor(tokens.text_secondary))
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "No trend data")
            return

        normalized = normalize_chart_values(self.values)
        if len(normalized) == 1:
            x_positions = [plot.left() + plot.width() / 2]
        else:
            step = plot.width() / (len(normalized) - 1)
            x_positions = [plot.left() + index * step for index in range(len(normalized))]
        points = [
            (x, plot.bottom() - value * (plot.height() - 12) - 6)
            for x, value in zip(x_positions, normalized)
        ]

        path = QPainterPath()
        path.moveTo(points[0][0], points[0][1])
        for x, y in points[1:]:
            path.lineTo(x, y)
        painter.setPen(QPen(QColor(tokens.accent), 3))
        painter.drawPath(path)
        painter.setBrush(QColor(tokens.accent))
        for x, y in points:
            painter.drawEllipse(QRectF(x - 3, y - 3, 6, 6))

        painter.setPen(QColor(tokens.text_secondary))
        for label, x in zip(self.labels, x_positions):
            painter.drawText(QRectF(x - 34, plot.bottom() + 6, 68, 18), Qt.AlignmentFlag.AlignCenter, label)


class BarBreakdownChart(QWidget):
    def __init__(self, theme_manager: ThemeManager | None = None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.title = "Breakdown"
        self.values: dict[str, int] = {}
        self.setMinimumHeight(190)
        if self.theme_manager is not None:
            self.theme_manager.theme_changed.connect(lambda _theme: self.update())

    def set_values(self, title: str, values: dict[str, int]) -> None:
        self.title = title
        self.values = dict(values)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        tokens = _tokens(self.theme_manager)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(tokens.panel))
        painter.setPen(QColor(tokens.text_primary))
        painter.drawText(12, 24, self.title)
        items = list(self.values.items())[:6]
        if not items:
            painter.setPen(QColor(tokens.text_secondary))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No breakdown data")
            return

        maximum = max(value for _label, value in items) or 1
        top = 44
        row_height = max(24, (self.height() - top - 12) // max(1, len(items)))
        for index, (label, value) in enumerate(items):
            y = top + index * row_height
            painter.setPen(QColor(tokens.text_secondary))
            painter.drawText(12, y + 17, label[:24])
            bar_width = int((self.width() - 174) * (value / maximum))
            painter.setBrush(QColor(tokens.accent))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(128, y + 4, max(2, bar_width), 16, 4, 4)
            painter.setPen(QColor(tokens.text_primary))
            painter.drawText(self.width() - 42, y + 17, str(value))


class RiskScoreBar(QWidget):
    def __init__(self, theme_manager: ThemeManager | None = None, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.score = 0
        self.risk_level = RISK_UNKNOWN
        self.setMinimumHeight(42)
        if self.theme_manager is not None:
            self.theme_manager.theme_changed.connect(lambda _theme: self.update())

    def set_score(self, score: int, risk_level: str) -> None:
        self.score = max(0, min(100, int(score)))
        self.risk_level = risk_level
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        tokens = _tokens(self.theme_manager)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 10, max(1, self.width()), 18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens.background_subtle))
        painter.drawRoundedRect(rect, 5, 5)
        fill = QRectF(rect.left(), rect.top(), rect.width() * (self.score / 100), rect.height())
        painter.setBrush(QColor(risk_level_color(self.risk_level)))
        painter.drawRoundedRect(fill, 5, 5)
        painter.setPen(QColor(tokens.text_primary))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"{self.risk_level} | {self.score}")


def _tokens(theme_manager: ThemeManager | None):
    return theme_manager.current_theme if theme_manager is not None else theme_from_name(DARK_THEME)
