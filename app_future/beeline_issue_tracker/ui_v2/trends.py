from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from beeline_issue_tracker.analytics.models import MachineTrendPoint
from beeline_issue_tracker.ui_v2.charts import BarBreakdownChart, LineTrendChart, trend_issue_values
from beeline_issue_tracker.ui_v2.theme import ThemeManager


class GraphTrendsPanel(QFrame):
    def __init__(self, theme_manager: ThemeManager, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.setObjectName("infoPanel")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 16, 18, 16)
        self.layout.setSpacing(12)

        title = QLabel("Trends")
        title.setObjectName("sectionTitle")
        self.layout.addWidget(title)

        self.empty_label = QLabel("Not enough trend data yet. BeeLine will draw this graph as issues are logged.")
        self.empty_label.setObjectName("mutedLabel")
        self.empty_label.setWordWrap(True)
        self.layout.addWidget(self.empty_label)

        self.chart_row = QHBoxLayout()
        self.chart_row.setSpacing(12)
        self.trend_chart = LineTrendChart(theme_manager)
        self.severity_chart = BarBreakdownChart(theme_manager)
        self.category_chart = BarBreakdownChart(theme_manager)
        self.chart_row.addWidget(self.trend_chart, 2)
        self.chart_row.addWidget(self.severity_chart, 1)
        self.chart_row.addWidget(self.category_chart, 1)
        self.layout.addLayout(self.chart_row)

    def set_data(
        self,
        trend: list[MachineTrendPoint] | tuple[MachineTrendPoint, ...],
        *,
        category_counts: dict[str, int] | None = None,
        severity_counts: dict[str, int] | None = None,
    ) -> None:
        category_counts = category_counts or {}
        severity_counts = severity_counts or {}
        labels, values = trend_issue_values(list(trend))
        has_trend_data = any(value > 0 for value in values)
        has_breakdowns = bool(category_counts or severity_counts)
        has_any_data = has_trend_data or has_breakdowns

        self.empty_label.setVisible(not has_any_data)
        self.trend_chart.setVisible(has_any_data)
        self.severity_chart.setVisible(has_any_data)
        self.category_chart.setVisible(has_any_data)

        self.trend_chart.set_points(
            "Issue Count Over Time",
            labels if has_trend_data else [],
            values if has_trend_data else [],
        )
        self.severity_chart.set_values("Severity Distribution", severity_counts)
        self.category_chart.set_values("Category Frequency", category_counts)
