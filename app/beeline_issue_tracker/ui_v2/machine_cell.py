from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from beeline_issue_tracker.analytics.predictive_service import PredictiveMaintenanceService
from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.domain import Issue, MachineResolvedStats, MachineSummary, ResolvedIssue
from beeline_issue_tracker.perf import elapsed_ms, log as perf_log, now as perf_now
from beeline_issue_tracker.ui_v2.theme import ThemeManager, repolish, status_state
from beeline_issue_tracker.ui_v2.trends import GraphTrendsPanel
from beeline_issue_tracker.ui_v2.widgets import (
    BrandHeader,
    HoneycombBackground,
    IssueListView,
    MetricPill,
    StatusBadge,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MachineCellQuery:
    active_query: str = ""
    active_sort: str = "date_desc"
    active_limit: int = 10
    active_offset: int = 0
    resolved_query: str = ""
    resolved_sort: str = "date_desc"
    resolved_limit: int = 10
    resolved_offset: int = 0


@dataclass(frozen=True)
class MachineCellSnapshot:
    machine_number: str
    summary: MachineSummary | None
    active_issues: list[Issue]
    active_matched: int
    resolved_issues: list[ResolvedIssue]
    resolved_matched: int
    stats: MachineResolvedStats | None
    trend: list[object]
    category_counts: dict[str, int]
    severity_counts: dict[str, int]


def load_machine_cell_snapshot(
    repository: IssueRepository,
    predictive_service: PredictiveMaintenanceService | None,
    machine_number: str,
    criteria: MachineCellQuery,
) -> MachineCellSnapshot:
    started_at = perf_now()
    call_started = perf_now()
    summary = repository.get_machine_summary(machine_number)
    perf_log("repo.get_machine_summary", machine=machine_number, elapsed_ms=elapsed_ms(call_started))
    if summary is None:
        perf_log("machine.snapshot", machine=machine_number, found=False, elapsed_ms=elapsed_ms(started_at))
        return MachineCellSnapshot(machine_number, None, [], 0, [], 0, None, [], {}, {})

    call_started = perf_now()
    active_issues = repository.list_active_issues(
        summary.machine_number,
        query=criteria.active_query,
        sort_key=criteria.active_sort,
        limit=criteria.active_limit,
        offset=criteria.active_offset,
    )
    perf_log(
        "repo.list_active_issues",
        machine=summary.machine_number,
        limit=criteria.active_limit,
        offset=criteria.active_offset,
        elapsed_ms=elapsed_ms(call_started),
    )

    call_started = perf_now()
    resolved_issues = repository.list_resolved_issues(
        summary.machine_number,
        query=criteria.resolved_query,
        sort_key=criteria.resolved_sort,
        limit=criteria.resolved_limit,
        offset=criteria.resolved_offset,
    )
    perf_log(
        "repo.list_resolved_issues",
        machine=summary.machine_number,
        limit=criteria.resolved_limit,
        offset=criteria.resolved_offset,
        elapsed_ms=elapsed_ms(call_started),
    )

    call_started = perf_now()
    stats = repository.get_machine_resolved_stats(summary.machine_number)
    perf_log("repo.get_machine_resolved_stats", machine=summary.machine_number, elapsed_ms=elapsed_ms(call_started))

    if criteria.active_query.strip():
        call_started = perf_now()
        active_matched = repository.count_active_issues_matching(summary.machine_number, criteria.active_query)
        perf_log("repo.count_active_issues_matching", machine=summary.machine_number, elapsed_ms=elapsed_ms(call_started))
    else:
        active_matched = summary.open_issue_count

    if criteria.resolved_query.strip():
        call_started = perf_now()
        resolved_matched = repository.count_resolved_issues_matching(summary.machine_number, criteria.resolved_query)
        perf_log("repo.count_resolved_issues_matching", machine=summary.machine_number, elapsed_ms=elapsed_ms(call_started))
    else:
        resolved_matched = stats.total_resolved

    trend = []
    category_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    if predictive_service is not None:
        call_started = perf_now()
        trend = predictive_service.get_machine_trend(summary.machine_number, periods=8)
        perf_log("machine.get_trend", machine=summary.machine_number, elapsed_ms=elapsed_ms(call_started))
        call_started = perf_now()
        category_counts = predictive_service.get_category_breakdown(machine_number=summary.machine_number, days=90)
        severity_counts = predictive_service.get_severity_breakdown(machine_number=summary.machine_number, days=90)
        perf_log("machine.get_breakdowns", machine=summary.machine_number, elapsed_ms=elapsed_ms(call_started))

    perf_log("machine.snapshot", machine=summary.machine_number, found=True, elapsed_ms=elapsed_ms(started_at))
    return MachineCellSnapshot(
        machine_number=summary.machine_number,
        summary=summary,
        active_issues=active_issues,
        active_matched=active_matched,
        resolved_issues=resolved_issues,
        resolved_matched=resolved_matched,
        stats=stats,
        trend=trend,
        category_counts=category_counts,
        severity_counts=severity_counts,
    )


class MachineCellPage(HoneycombBackground):
    back_requested = Signal()
    log_issue_requested = Signal(str)
    resolve_issue_requested = Signal(int)
    issue_detail_requested = Signal(int, str)
    machine_details_requested = Signal(str, str)

    def __init__(
        self,
        repository: IssueRepository,
        theme_manager: ThemeManager,
        paths: AppPaths,
        predictive_service: PredictiveMaintenanceService | None = None,
        parent=None,
    ):
        super().__init__(theme_manager, parent)
        self.repository = repository
        self.theme_manager = theme_manager
        self.paths = paths
        self.predictive_service = predictive_service
        self.machine_number: str | None = None

        page = QVBoxLayout(self)
        page.setContentsMargins(24, 22, 24, 22)
        page.setSpacing(16)

        nav = QHBoxLayout()
        self.back_button = QPushButton("Back to Hive Dashboard")
        self.back_button.clicked.connect(self.back_requested.emit)
        nav.addWidget(self.back_button)
        nav.addWidget(BrandHeader("BeeLine Issue Tracker", "Machine Cell", paths.logo_path(), theme_manager), 1)
        info_button = QPushButton("Machine Info")
        info_button.setObjectName("secondaryButton")
        info_button.clicked.connect(lambda _checked=False: self._request_machine_details("overview"))
        nav.addWidget(info_button)
        page.addLayout(nav)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("transparentHost")
        body = QVBoxLayout(self.content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        self.scroll.setWidget(self.content)
        page.addWidget(self.scroll, 1)

        self.machine_header = QFrame()
        self.machine_header.setObjectName("machineHeader")
        header_layout = QVBoxLayout(self.machine_header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(14)

        title_row = QHBoxLayout()
        title_row.setSpacing(14)
        title_text = QVBoxLayout()
        title_text.setContentsMargins(0, 0, 0, 0)
        title_text.setSpacing(2)
        self.machine_title = QLabel("Machine")
        self.machine_title.setObjectName("machineNumber")
        self.machine_subtitle = QLabel("")
        self.machine_subtitle.setObjectName("subtitleLabel")
        self.machine_meta = QLabel("")
        self.machine_meta.setObjectName("mutedLabel")
        self.machine_meta.setWordWrap(True)
        title_text.addWidget(self.machine_title)
        title_text.addWidget(self.machine_subtitle)
        title_text.addWidget(self.machine_meta)
        title_row.addLayout(title_text, 1)
        self.status_badge = StatusBadge("Unknown/Error")
        title_row.addWidget(self.status_badge)
        header_layout.addLayout(title_row)

        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        self.area_pill = MetricPill("Area")
        self.cell_pill = MetricPill("Cell")
        self.asset_pill = MetricPill("Asset Tag")
        self.open_issue_pill = MetricPill("Open Issues")
        self.recent_resolved_pill = MetricPill("Recent Resolved")
        for pill in (
            self.area_pill,
            self.cell_pill,
            self.asset_pill,
            self.open_issue_pill,
            self.recent_resolved_pill,
        ):
            metrics.addWidget(pill)
        metrics.addStretch(1)
        header_layout.addLayout(metrics)
        body.addWidget(self.machine_header)

        self.active_list = IssueListView(
            "active",
            "Active/Open Issues",
            "Search active issues...",
            show_log_action=True,
        )
        self.active_list.resolve_requested.connect(self.resolve_issue_requested.emit)
        self.active_list.log_issue_requested.connect(self._request_log_issue)
        self.active_list.detail_requested.connect(self.issue_detail_requested.emit)
        self.active_list.criteria_changed.connect(self.refresh)
        body.addWidget(self.active_list)

        self.resolved_list = IssueListView(
            "resolved",
            "Related History",
            "Search resolved issues...",
        )
        self.resolved_list.detail_requested.connect(self.issue_detail_requested.emit)
        self.resolved_list.criteria_changed.connect(self.refresh)
        body.addWidget(self.resolved_list)

        self.memory_panel = QFrame()
        self.memory_panel.setObjectName("infoPanel")
        memory_layout = QVBoxLayout(self.memory_panel)
        memory_layout.setContentsMargins(16, 12, 16, 12)
        memory_layout.setSpacing(6)
        memory_title = QLabel("Troubleshooting Memory")
        memory_title.setObjectName("sectionTitle")
        self.memory_summary = QLabel()
        self.memory_summary.setObjectName("mutedLabel")
        self.memory_summary.setWordWrap(True)
        memory_layout.addWidget(memory_title)
        memory_layout.addWidget(self.memory_summary)
        body.addWidget(self.memory_panel)
        self.trends_panel = GraphTrendsPanel(theme_manager)
        body.addWidget(self.trends_panel)
        body.addStretch(1)

    def load_machine(self, machine_number: str) -> None:
        self.machine_number = machine_number
        self.apply_snapshot(
            load_machine_cell_snapshot(
                self.repository,
                self.predictive_service,
                machine_number,
                self.current_query(),
            )
        )

    def show_loading(self, machine_number: str) -> None:
        self.machine_number = machine_number
        self.machine_title.setText(f"Machine {machine_number}")
        self.machine_subtitle.setText("Loading machine details...")
        self.machine_meta.setText("")
        self.status_badge.set_status("Unknown/Error")
        self.machine_header.setProperty("statusState", "unknown")
        repolish(self.machine_header)
        self.area_pill.set_value("-")
        self.cell_pill.set_value("-")
        self.asset_pill.set_value("-")
        self.open_issue_pill.set_value("-")
        self.recent_resolved_pill.set_value("-")
        self.memory_summary.setText("Loading recent issue history...")
        self.trends_panel.set_data([], category_counts={}, severity_counts={})
        self.active_list.set_query_result([], matched=0, total=0)
        self.resolved_list.set_query_result([], matched=0, total=0)

    def set_can_report(self, enabled: bool) -> None:
        self.active_list.set_log_action_enabled(enabled)

    def refresh(self) -> None:
        if not self.machine_number:
            return
        self.apply_snapshot(
            load_machine_cell_snapshot(
                self.repository,
                self.predictive_service,
                self.machine_number,
                self.current_query(),
            )
        )

    def current_query(self) -> MachineCellQuery:
        active_query, active_sort, active_limit, active_offset = self.active_list.criteria()
        resolved_query, resolved_sort, resolved_limit, resolved_offset = self.resolved_list.criteria()
        return MachineCellQuery(
            active_query=active_query,
            active_sort=active_sort,
            active_limit=active_limit,
            active_offset=active_offset,
            resolved_query=resolved_query,
            resolved_sort=resolved_sort,
            resolved_limit=resolved_limit,
            resolved_offset=resolved_offset,
        )

    def apply_snapshot(self, snapshot: MachineCellSnapshot) -> None:
        if self.machine_number != snapshot.machine_number:
            perf_log(
                "machine.apply_snapshot_skipped",
                current=self.machine_number,
                snapshot=snapshot.machine_number,
            )
            return

        summary = snapshot.summary
        if summary is None:
            self.machine_title.setText("Machine not found")
            self.machine_subtitle.setText("")
            self.machine_meta.setText("")
            self.status_badge.set_status("Unknown/Error")
            self.machine_header.setProperty("statusState", "unknown")
            repolish(self.machine_header)
            self.area_pill.set_value("-")
            self.cell_pill.set_value("-")
            self.asset_pill.set_value("-")
            self.open_issue_pill.set_value("0")
            self.recent_resolved_pill.set_value("0")
            self.memory_summary.setText("No resolved history yet.")
            self.trends_panel.set_data([], category_counts={}, severity_counts={})
            self.active_list.set_issues([])
            self.resolved_list.set_issues([])
            return

        self.machine_title.setText(f"Machine {summary.machine_number}")
        self.machine_subtitle.setText(summary.name)
        self.machine_meta.setText(_machine_meta_text(summary))
        self.status_badge.set_status(summary.calculated_status)
        self.machine_header.setProperty("statusState", status_state(summary.calculated_status))
        repolish(self.machine_header)

        self.area_pill.set_value(summary.area)
        self.cell_pill.set_value(summary.cell)
        self.asset_pill.set_value(summary.asset_tag)
        self.open_issue_pill.set_value(str(summary.open_issue_count))
        self.recent_resolved_pill.set_value(str(snapshot.stats.total_resolved if snapshot.stats is not None else 0))
        self.memory_summary.setText(_memory_text(snapshot.stats) if snapshot.stats is not None else "No resolved history yet.")
        self.trends_panel.set_data(
            snapshot.trend,
            category_counts=snapshot.category_counts,
            severity_counts=snapshot.severity_counts,
        )
        self.active_list.set_query_result(
            snapshot.active_issues,
            matched=snapshot.active_matched,
            total=summary.open_issue_count,
        )
        self.resolved_list.set_query_result(
            snapshot.resolved_issues,
            matched=snapshot.resolved_matched,
            total=snapshot.stats.total_resolved if snapshot.stats is not None else 0,
        )

    def _request_log_issue(self) -> None:
        if self.machine_number:
            logger.debug("Add Issue clicked for machine %s", self.machine_number)
            self.log_issue_requested.emit(self.machine_number)

    def _request_machine_details(self, section: str) -> None:
        if self.machine_number:
            self.machine_details_requested.emit(self.machine_number, section)

def _memory_text(stats) -> str:
    if stats.total_resolved == 0:
        return "No resolved history yet."
    avg = _format_seconds(stats.average_time_open_seconds)
    last_fix = stats.last_resolved_title or "-"
    parts = [
        f"Resolved: {stats.total_resolved}",
        f"Most common category: {stats.most_common_category or '-'}",
        f"Average time open: {avg}",
        f"Recurring: {stats.recurring_warning or 'None'}",
        f"Last fix: {last_fix}",
    ]
    return " | ".join(parts)


def _machine_meta_text(machine) -> str:
    parts = [
        " / ".join(part for part in (machine.area, machine.cell) if part),
        f"Asset {machine.asset_tag}" if machine.asset_tag else "",
        f"{machine.manufacturer} {machine.model}".strip(),
        f"IMM Serial {machine.imm_serial}" if machine.imm_serial else "",
        f"Robot {machine.robot_type} {machine.robot_model}".strip()
        if machine.robot_type or machine.robot_model
        else "",
    ]
    return " | ".join(part for part in parts if part)


def _format_seconds(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24
    if days:
        return f"{days}d {hours % 24}h"
    if hours:
        return f"{hours}h {minutes % 60}m"
    return f"{minutes}m"


def _format_minutes(minutes: int | None) -> str:
    if minutes is None:
        return "-"
    hours = minutes // 60
    days = hours // 24
    if days:
        return f"{days}d {hours % 24}h"
    if hours:
        return f"{hours}h {minutes % 60}m"
    return f"{minutes}m"
