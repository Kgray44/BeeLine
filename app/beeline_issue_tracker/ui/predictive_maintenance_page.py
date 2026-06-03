from __future__ import annotations

"""Predictive maintenance dashboard page."""

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from beeline_issue_tracker.analytics.models import (
    MachineRiskSummary,
    PredictiveMaintenanceAlert,
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_STABLE,
    RISK_UNKNOWN,
)
from beeline_issue_tracker.analytics.predictive_service import (
    PredictiveMaintenanceService,
    filter_machine_risks,
    sort_machine_risks,
)
from beeline_issue_tracker.analytics.reporting import build_predictive_summary_text
from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.perf import elapsed_ms, log as perf_log, now as perf_now
from beeline_issue_tracker.ui.charts import BarBreakdownChart, LineTrendChart, trend_issue_values
from beeline_issue_tracker.ui.issue_list_model import format_timestamp, preview_text
from beeline_issue_tracker.ui.theme import ThemeManager
from beeline_issue_tracker.ui.widgets import BrandHeader, HoneycombBackground, MetricPill, SearchBox


@dataclass(frozen=True)
class PredictivePageSnapshot:
    risks: list[MachineRiskSummary]
    alerts: list[PredictiveMaintenanceAlert]
    patterns: list[object]
    trend_labels: list[str]
    trend_values: list[int]
    category_counts: dict[str, int]


def load_predictive_page_snapshot(service: PredictiveMaintenanceService) -> PredictivePageSnapshot:
    started_at = perf_now()
    call_started = perf_now()
    risks = service.get_all_machine_risks()
    perf_log("predictive.get_all_machine_risks", count=len(risks), elapsed_ms=elapsed_ms(call_started))
    call_started = perf_now()
    alerts = service.get_predictive_alerts(limit=20)
    perf_log("predictive.get_alerts", count=len(alerts), elapsed_ms=elapsed_ms(call_started))
    call_started = perf_now()
    patterns = service.get_recurring_patterns(days=service.settings.recurrence_window_days)
    perf_log("predictive.get_patterns", count=len(patterns), elapsed_ms=elapsed_ms(call_started))
    call_started = perf_now()
    labels, values = trend_issue_values(
        service.get_global_trend(
            periods=service.settings.grouped_chart_periods,
        )
    )
    perf_log("predictive.get_global_trend", elapsed_ms=elapsed_ms(call_started))
    call_started = perf_now()
    category_counts = service.get_category_breakdown(days=service.settings.risk_window_days)
    perf_log("predictive.get_category_breakdown", count=len(category_counts), elapsed_ms=elapsed_ms(call_started))
    perf_log("predictive.snapshot", elapsed_ms=elapsed_ms(started_at))
    return PredictivePageSnapshot(risks, alerts, patterns, labels, values, category_counts)


class PredictiveMaintenancePage(HoneycombBackground):
    back_requested = Signal()
    machine_requested = Signal(str)
    dismiss_alert_requested = Signal(int)

    RISK_COLUMNS = (
        "Machine",
        "Area/Cell",
        "Risk Level",
        "Risk Score",
        "Open Issues",
        "Recent Issues",
        "Predicted Problem",
        "Suggested Action",
        "Confidence",
        "Action",
    )
    PATTERN_COLUMNS = ("Machine", "Pattern", "Count", "Last Seen", "Common Solution", "Risk Note")

    def __init__(
        self,
        service: PredictiveMaintenanceService,
        theme_manager: ThemeManager,
        paths: AppPaths,
        parent=None,
    ):
        super().__init__(theme_manager, parent)
        self.service = service
        self.theme_manager = theme_manager
        self.paths = paths
        self._risks: list[MachineRiskSummary] = []
        self._alerts: list[PredictiveMaintenanceAlert] = []
        self._visible_risks: list[MachineRiskSummary] = []
        self._patterns: list[object] = []
        self._trend_labels: list[str] = []
        self._trend_values: list[int] = []
        self._category_counts: dict[str, int] = {}
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(160)
        self._render_timer.timeout.connect(self._render_risk_table)

        page = QVBoxLayout(self)
        page.setContentsMargins(24, 22, 24, 22)
        page.setSpacing(14)

        header = QHBoxLayout()
        back = QPushButton("Back to Dashboard")
        back.clicked.connect(self.back_requested.emit)
        header.addWidget(back)
        header.addWidget(BrandHeader("BeeLine", "Predictive Maintenance", paths.logo_path(), theme_manager), 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        header.addWidget(refresh)
        copy_summary = QPushButton("Copy Summary")
        copy_summary.clicked.connect(self._copy_summary)
        header.addWidget(copy_summary)
        export_summary = QPushButton("Export Summary .txt")
        export_summary.clicked.connect(self._export_summary)
        header.addWidget(export_summary)
        page.addLayout(header)

        summary_panel = QFrame()
        summary_panel.setObjectName("infoPanel")
        summary_layout = QHBoxLayout(summary_panel)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(10)
        self.critical_pill = MetricPill("Critical")
        self.high_pill = MetricPill("High")
        self.medium_pill = MetricPill("Medium")
        self.recurring_pill = MetricPill("Recurring")
        self.line_down_pill = MetricPill("Open Line Down")
        self.open_total_pill = MetricPill("Total Open")
        for pill in (
            self.critical_pill,
            self.high_pill,
            self.medium_pill,
            self.recurring_pill,
            self.line_down_pill,
            self.open_total_pill,
        ):
            summary_layout.addWidget(pill)
        summary_layout.addStretch(1)
        page.addWidget(summary_panel)

        controls_panel = QFrame()
        controls_panel.setObjectName("infoPanel")
        controls = QHBoxLayout(controls_panel)
        controls.setContentsMargins(14, 12, 14, 12)
        controls.setSpacing(10)
        self.search = SearchBox("Search machines...")
        self.search.textChanged.connect(self._queue_risk_render)
        self.risk_filter = QComboBox()
        self.risk_filter.setObjectName("compactDropdown")
        self.risk_filter.addItem("All Risk", "")
        for level in (RISK_CRITICAL, RISK_HIGH, RISK_MEDIUM, RISK_LOW, RISK_STABLE, RISK_UNKNOWN):
            self.risk_filter.addItem(level, level)
        self.risk_filter.currentIndexChanged.connect(self._render_risk_table)
        self.sort = QComboBox()
        self.sort.setObjectName("compactDropdown")
        for label, value in (
            ("Risk Score", "risk_score"),
            ("Machine A-Z", "machine_asc"),
            ("Recent Issues", "recent_issue_count"),
            ("Open Issues", "open_issue_count"),
        ):
            self.sort.addItem(label, value)
        self.sort.currentIndexChanged.connect(self._render_risk_table)
        controls.addWidget(self.search, 1)
        controls.addWidget(self.risk_filter)
        controls.addWidget(self.sort)
        page.addWidget(controls_panel)

        splitter = QSplitter(Qt.Orientation.Vertical)
        top = QWidget()
        top.setObjectName("transparentHost")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(14)

        self.risk_table = QTableWidget()
        self.risk_table.setObjectName("issueTable")
        self.risk_table.setColumnCount(len(self.RISK_COLUMNS))
        self.risk_table.setHorizontalHeaderLabels(self.RISK_COLUMNS)
        self.risk_table.setAlternatingRowColors(True)
        self.risk_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.risk_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.risk_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.risk_table.setShowGrid(False)
        self.risk_table.verticalHeader().setVisible(False)
        self.risk_table.horizontalHeader().setHighlightSections(False)
        self.risk_table.itemDoubleClicked.connect(self._open_risk_item)
        top_layout.addWidget(self.risk_table, 2)

        right_panel = QWidget()
        right_panel.setObjectName("transparentHost")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(14)
        self.alerts_panel = QFrame()
        self.alerts_panel.setObjectName("infoPanel")
        self.alerts_layout = QVBoxLayout(self.alerts_panel)
        self.alerts_layout.setContentsMargins(14, 12, 14, 12)
        self.alerts_layout.setSpacing(8)
        right_layout.addWidget(self.alerts_panel, 1)
        chart_host = QWidget()
        chart_host.setObjectName("transparentHost")
        chart_grid = QGridLayout(chart_host)
        chart_grid.setContentsMargins(0, 0, 0, 0)
        chart_grid.setSpacing(10)
        self.trend_chart = LineTrendChart(theme_manager)
        self.breakdown_chart = BarBreakdownChart(theme_manager)
        chart_grid.addWidget(self.trend_chart, 0, 0)
        chart_grid.addWidget(self.breakdown_chart, 0, 1)
        right_layout.addWidget(chart_host, 1)
        top_layout.addWidget(right_panel, 1)
        splitter.addWidget(top)

        pattern_panel = QFrame()
        pattern_panel.setObjectName("infoPanel")
        pattern_layout = QVBoxLayout(pattern_panel)
        pattern_layout.setContentsMargins(14, 12, 14, 12)
        title = QLabel("Recurring Patterns")
        title.setObjectName("sectionTitle")
        pattern_layout.addWidget(title)
        self.pattern_table = QTableWidget()
        self.pattern_table.setObjectName("issueTable")
        self.pattern_table.setColumnCount(len(self.PATTERN_COLUMNS))
        self.pattern_table.setHorizontalHeaderLabels(self.PATTERN_COLUMNS)
        self.pattern_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pattern_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.pattern_table.setShowGrid(False)
        self.pattern_table.verticalHeader().setVisible(False)
        pattern_layout.addWidget(self.pattern_table)
        splitter.addWidget(pattern_panel)
        splitter.setSizes([560, 240])
        page.addWidget(splitter, 1)
        self._configure_tables()

    def refresh(self) -> None:
        self.apply_snapshot(load_predictive_page_snapshot(self.service))

    def show_loading(self) -> None:
        self.critical_pill.set_value("-")
        self.high_pill.set_value("-")
        self.medium_pill.set_value("-")
        self.recurring_pill.set_value("-")
        self.line_down_pill.set_value("-")
        self.open_total_pill.set_value("-")
        self._risks = []
        self._alerts = []
        self._patterns = []
        self._trend_labels = []
        self._trend_values = []
        self._category_counts = {}
        self._render_risk_table(empty_text="Loading predictive maintenance data...")
        self._render_alerts(loading=True)
        self._render_patterns([])
        self.trend_chart.set_points("Global Issue Trend", [], [])
        self.breakdown_chart.set_values("Category Breakdown", {})

    def apply_snapshot(self, snapshot: PredictivePageSnapshot) -> None:
        self._risks = list(snapshot.risks)
        self._alerts = list(snapshot.alerts)
        self._patterns = list(snapshot.patterns)
        self._trend_labels = list(snapshot.trend_labels)
        self._trend_values = list(snapshot.trend_values)
        self._category_counts = dict(snapshot.category_counts)
        self._update_summary(self._patterns)
        self._render_risk_table()
        self._render_alerts()
        self._render_patterns(self._patterns)
        self._render_charts()

    def focus_machine(self, machine_number: str) -> None:
        self.risk_filter.setCurrentIndex(0)
        self.search.setText(machine_number)
        self._render_risk_table()

    def _configure_tables(self) -> None:
        risk_widths = (145, 120, 100, 82, 88, 96, 190, 230, 90, 110)
        for column, width in enumerate(risk_widths):
            self.risk_table.setColumnWidth(column, width)
        pattern_widths = (120, 190, 70, 145, 220, 320)
        for column, width in enumerate(pattern_widths):
            self.pattern_table.setColumnWidth(column, width)

    def _update_summary(self, patterns) -> None:
        self.critical_pill.set_value(str(sum(1 for risk in self._risks if risk.risk_level == RISK_CRITICAL)))
        self.high_pill.set_value(str(sum(1 for risk in self._risks if risk.risk_level == RISK_HIGH)))
        self.medium_pill.set_value(str(sum(1 for risk in self._risks if risk.risk_level == RISK_MEDIUM)))
        self.recurring_pill.set_value(str(len({pattern.machine_number for pattern in patterns})))
        self.line_down_pill.set_value(str(sum(risk.line_down_open_count for risk in self._risks)))
        self.open_total_pill.set_value(str(sum(risk.open_issue_count for risk in self._risks)))

    def _queue_risk_render(self) -> None:
        self._render_timer.start()

    def _render_risk_table(self, empty_text: str | None = None) -> None:
        started_at = perf_now()
        filtered = filter_machine_risks(
            self._risks,
            query=self.search.text(),
            risk_level=self.risk_filter.currentData() or "",
        )
        self._visible_risks = sort_machine_risks(filtered, sort_key=self.sort.currentData() or "risk_score")
        self.risk_table.setUpdatesEnabled(False)
        self.risk_table.blockSignals(True)
        try:
            self.risk_table.setRowCount(0)
            if not self._visible_risks:
                self.risk_table.setRowCount(1)
                self.risk_table.setSpan(0, 0, 1, len(self.RISK_COLUMNS))
                self.risk_table.setItem(
                    0,
                    0,
                    self._item(
                        empty_text
                        or "Not enough issue history yet to generate strong predictions. "
                        "BeeLine will improve predictions as issues are logged and resolved."
                    ),
                )
                return
            self.risk_table.clearSpans()
            self.risk_table.setRowCount(len(self._visible_risks))
            for row, risk in enumerate(self._visible_risks):
                location = " / ".join(part for part in (risk.area, risk.cell) if part)
                self.risk_table.setItem(row, 0, self._item(f"{risk.machine_number} | {risk.machine_name}"))
                self.risk_table.setItem(row, 1, self._item(location or "-"))
                self.risk_table.setItem(row, 2, self._item(risk.risk_level))
                self.risk_table.setItem(row, 3, self._item(str(risk.risk_score)))
                self.risk_table.setItem(row, 4, self._item(str(risk.open_issue_count)))
                self.risk_table.setItem(row, 5, self._item(str(risk.recent_issue_count)))
                self.risk_table.setItem(row, 6, self._item(preview_text(risk.predicted_problem, 72), risk.predicted_problem))
                self.risk_table.setItem(row, 7, self._item(preview_text(risk.suggested_action, 86), risk.suggested_action))
                self.risk_table.setItem(row, 8, self._item(risk.confidence))
                self.risk_table.setCellWidget(row, 9, self._open_machine_button(risk.machine_number))
                self.risk_table.setRowHeight(row, 52)
            self.risk_table.clearSelection()
        finally:
            self.risk_table.blockSignals(False)
            self.risk_table.setUpdatesEnabled(True)
            perf_log("predictive.render_risk_table", rows=len(self._visible_risks), elapsed_ms=elapsed_ms(started_at))

    def _render_alerts(self, *, loading: bool = False) -> None:
        self._clear_layout(self.alerts_layout)
        title = QLabel("Predictive Alerts")
        title.setObjectName("sectionTitle")
        self.alerts_layout.addWidget(title)
        if not self._alerts:
            empty = QLabel(
                "Loading predictive alerts..."
                if loading
                else "Not enough issue history yet to generate strong predictions. "
                "BeeLine will improve predictions as issues are logged and resolved."
            )
            empty.setObjectName("mutedLabel")
            empty.setWordWrap(True)
            self.alerts_layout.addWidget(empty)
            self.alerts_layout.addStretch(1)
            return
        for alert in self._alerts[:8]:
            row = QFrame()
            row.setObjectName("formPanel")
            layout = QVBoxLayout(row)
            layout.setContentsMargins(10, 8, 10, 8)
            layout.setSpacing(5)
            label = QLabel(f"{alert.risk_level} | Machine {alert.machine_number}")
            label.setObjectName("cardTitle")
            label.setWordWrap(True)
            layout.addWidget(label)
            message = QLabel(f"{alert.title}: {alert.message}")
            message.setWordWrap(True)
            layout.addWidget(message)
            reasons = QLabel(" | ".join(alert.reasons) or "-")
            reasons.setObjectName("mutedLabel")
            reasons.setWordWrap(True)
            layout.addWidget(reasons)
            actions = QHBoxLayout()
            open_button = QPushButton("Open Machine")
            open_button.setObjectName("tableActionButton")
            open_button.clicked.connect(lambda _checked=False, machine=alert.machine_number: self.machine_requested.emit(machine))
            actions.addWidget(open_button)
            if alert.id is not None:
                dismiss = QPushButton("Dismiss")
                dismiss.setObjectName("tableActionButton")
                dismiss.clicked.connect(lambda _checked=False, alert_id=alert.id: self._dismiss_alert(alert_id))
                actions.addWidget(dismiss)
            actions.addStretch(1)
            layout.addLayout(actions)
            self.alerts_layout.addWidget(row)
        self.alerts_layout.addStretch(1)

    def _render_patterns(self, patterns) -> None:
        started_at = perf_now()
        visible_patterns = list(patterns)[:200]
        self.pattern_table.setUpdatesEnabled(False)
        self.pattern_table.blockSignals(True)
        try:
            self.pattern_table.setRowCount(0)
            if not visible_patterns:
                self.pattern_table.setRowCount(1)
                self.pattern_table.setSpan(0, 0, 1, len(self.PATTERN_COLUMNS))
                self.pattern_table.setItem(0, 0, self._item("No recurring patterns detected yet."))
                return
            self.pattern_table.clearSpans()
            self.pattern_table.setRowCount(len(visible_patterns))
            for row, pattern in enumerate(visible_patterns):
                solution = pattern.common_solutions[0] if pattern.common_solutions else "-"
                self.pattern_table.setItem(row, 0, self._item(pattern.machine_number))
                self.pattern_table.setItem(row, 1, self._item(pattern.display_label))
                self.pattern_table.setItem(row, 2, self._item(str(pattern.occurrence_count)))
                self.pattern_table.setItem(row, 3, self._item(format_timestamp(pattern.last_seen_at), pattern.last_seen_at))
                self.pattern_table.setItem(row, 4, self._item(preview_text(solution, 72), solution))
                self.pattern_table.setItem(row, 5, self._item(pattern.risk_note))
                self.pattern_table.setRowHeight(row, 48)
        finally:
            self.pattern_table.blockSignals(False)
            self.pattern_table.setUpdatesEnabled(True)
            perf_log("predictive.render_patterns", rows=len(visible_patterns), elapsed_ms=elapsed_ms(started_at))

    def _render_charts(self) -> None:
        self.trend_chart.set_points("Global Issue Trend", self._trend_labels, self._trend_values)
        self.breakdown_chart.set_values(
            "Category Breakdown",
            self._category_counts,
        )

    def _copy_summary(self) -> None:
        summary = build_predictive_summary_text(self._risks, self._alerts, self._patterns)
        QGuiApplication.clipboard().setText(summary)
        QMessageBox.information(self, "Summary copied", "Predictive maintenance summary copied locally.")

    def _export_summary(self) -> None:
        summary = build_predictive_summary_text(self._risks, self._alerts, self._patterns)
        export_dir = self.paths.root_dir / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        filename = f"predictive_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path = export_dir / filename
        path.write_text(summary + "\n", encoding="utf-8")
        QMessageBox.information(self, "Summary exported", f"Local summary written to:\n{path}")

    def _dismiss_alert(self, alert_id: int) -> None:
        self.dismiss_alert_requested.emit(alert_id)

    def _open_risk_item(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if 0 <= row < len(self._visible_risks):
            self.machine_requested.emit(self._visible_risks[row].machine_number)

    def _open_machine_button(self, machine_number: str) -> QWidget:
        host = QWidget()
        host.setObjectName("transparentHost")
        layout = QHBoxLayout(host)
        layout.setContentsMargins(4, 4, 4, 4)
        button = QPushButton("Open Machine")
        button.setObjectName("tableActionButton")
        button.clicked.connect(lambda _checked=False, machine=machine_number: self.machine_requested.emit(machine))
        layout.addWidget(button)
        return host

    @staticmethod
    def _item(text: str, tooltip: str | None = None) -> QTableWidgetItem:
        item = QTableWidgetItem(text or "-")
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if tooltip:
            item.setToolTip(tooltip)
        return item

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            child_layout = item.layout()
            if child_layout:
                PredictiveMaintenancePage._clear_layout(child_layout)
