from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
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
from beeline_issue_tracker.domain import (
    LINE_DOWN,
    NON_CRITICAL,
    NO_ISSUES,
    Issue,
    MachineResolvedStats,
    MachineSummary,
    ResolvedIssue,
)
from beeline_issue_tracker.perf import elapsed_ms, log as perf_log, now as perf_now
from beeline_issue_tracker.ui_v2.issue_list_model import format_timestamp, parse_timestamp, preview_text
from beeline_issue_tracker.ui_v2.machine_cell import _format_seconds
from beeline_issue_tracker.ui_v2.theme import ThemeManager, repolish, status_state
from beeline_issue_tracker.ui_v2.trends import GraphTrendsPanel
from beeline_issue_tracker.ui_v2.widgets import BrandHeader, HoneycombBackground, IssueListView, StatusBadge


logger = logging.getLogger(__name__)

NO_DATA_TEXT = "No data available"


@dataclass(frozen=True)
class MachineDetailsSnapshot:
    machine_number: str
    section: str
    summary: MachineSummary | None
    active_issues: list[Issue]
    resolved_issues: list[ResolvedIssue]
    stats: MachineResolvedStats | None
    trend: list[object]
    category_counts: dict[str, int]
    severity_counts: dict[str, int]
    patterns_text: str


def load_machine_details_snapshot(
    repository: IssueRepository,
    predictive_service: PredictiveMaintenanceService | None,
    machine_number: str,
    section: str = "overview",
) -> MachineDetailsSnapshot:
    started_at = perf_now()
    call_started = perf_now()
    summary = repository.get_machine_summary(machine_number)
    perf_log("details.get_machine_summary", machine=machine_number, elapsed_ms=elapsed_ms(call_started))
    if summary is None:
        perf_log("details.snapshot", machine=machine_number, found=False, elapsed_ms=elapsed_ms(started_at))
        return MachineDetailsSnapshot(machine_number, section, None, [], [], None, [], {}, {}, "")

    call_started = perf_now()
    active_issues = repository.list_active_issues(summary.machine_number, limit=10)
    perf_log("details.list_active", machine=summary.machine_number, limit=10, elapsed_ms=elapsed_ms(call_started))
    call_started = perf_now()
    resolved_issues = repository.list_resolved_issues(summary.machine_number, limit=10)
    perf_log("details.list_resolved", machine=summary.machine_number, limit=10, elapsed_ms=elapsed_ms(call_started))
    call_started = perf_now()
    stats = repository.get_machine_resolved_stats(summary.machine_number)
    perf_log("details.resolved_stats", machine=summary.machine_number, elapsed_ms=elapsed_ms(call_started))

    trend = []
    category_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    patterns_text = "No recurring patterns detected yet"
    if predictive_service is not None:
        call_started = perf_now()
        trend = predictive_service.get_machine_trend(summary.machine_number, periods=8)
        perf_log("details.get_trend", machine=summary.machine_number, elapsed_ms=elapsed_ms(call_started))
        call_started = perf_now()
        category_counts = predictive_service.get_category_breakdown(machine_number=summary.machine_number, days=90)
        severity_counts = predictive_service.get_severity_breakdown(machine_number=summary.machine_number, days=90)
        perf_log("details.get_breakdowns", machine=summary.machine_number, elapsed_ms=elapsed_ms(call_started))
        call_started = perf_now()
        patterns_text = _patterns_text(predictive_service, summary.machine_number)
        perf_log("details.get_patterns", machine=summary.machine_number, elapsed_ms=elapsed_ms(call_started))

    perf_log("details.snapshot", machine=summary.machine_number, found=True, elapsed_ms=elapsed_ms(started_at))
    return MachineDetailsSnapshot(
        machine_number=summary.machine_number,
        section=section,
        summary=summary,
        active_issues=active_issues,
        resolved_issues=resolved_issues,
        stats=stats,
        trend=trend,
        category_counts=category_counts,
        severity_counts=severity_counts,
        patterns_text=patterns_text,
    )


class MachineDetailsPage(HoneycombBackground):
    back_requested = Signal()
    log_issue_requested = Signal(str)
    resolve_issue_requested = Signal(int)
    issue_detail_requested = Signal(int, str)

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
        self._can_report = True
        self.active_history_list: IssueListView | None = None
        self.resolved_history_list: IssueListView | None = None
        self._sections: dict[str, QWidget] = {}
        self._section_nav_buttons: dict[str, QPushButton] = {}

        page = QVBoxLayout(self)
        page.setContentsMargins(24, 22, 24, 22)
        page.setSpacing(16)

        header = QHBoxLayout()
        self.back_button = QPushButton("Back to Machine")
        self.back_button.setObjectName("quietButton")
        self.back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back_button)
        self.brand_header = BrandHeader("Machine Info", "", paths.logo_path(), theme_manager)
        header.addWidget(self.brand_header, 1)
        page.addLayout(header)
        page.addLayout(self._build_section_nav())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("transparentHost")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(14)
        self.scroll.setWidget(self.content)
        page.addWidget(self.scroll, 1)

    def load_machine(self, machine_number: str, section: str = "overview") -> None:
        self.apply_snapshot(load_machine_details_snapshot(self.repository, self.predictive_service, machine_number, section))

    def show_loading(self, machine_number: str, section: str = "overview") -> None:
        self.machine_number = machine_number
        self.active_history_list = None
        self.resolved_history_list = None
        self._clear_content()
        self._sections = {}
        self.brand_header.set_subtitle(f"Machine {machine_number}")
        self._add_text_panel("Loading", "Loading machine information...", section="overview")
        panel = self._panel("Issue History", "history")
        layout = panel.layout()
        assert layout is not None
        active_list = IssueListView("active", "Active/Open Issues", "Search active issues...", show_log_action=True)
        active_list.set_log_action_enabled(self._can_report)
        active_list.log_issue_requested.connect(lambda: self._request_log_issue(machine_number))
        active_list.set_query_result([], matched=0, total=0)
        self.active_history_list = active_list
        layout.addWidget(active_list)
        self.content_layout.addWidget(panel)
        QTimer.singleShot(0, lambda target=section: self._focus_section(target))

    def apply_snapshot(self, snapshot: MachineDetailsSnapshot) -> None:
        self.machine_number = snapshot.machine_number
        self.active_history_list = None
        self.resolved_history_list = None
        self._clear_content()
        self._sections = {}

        summary = snapshot.summary
        if summary is None:
            self.brand_header.set_subtitle(f"Machine {snapshot.machine_number}")
            self._add_text_panel("Machine not found", "This machine is not available in the active machine list.")
            return

        self.brand_header.set_subtitle(f"Machine {summary.machine_number} | {summary.name}")
        active_issues = snapshot.active_issues
        resolved_issues = snapshot.resolved_issues
        stats = snapshot.stats
        if stats is None:
            self._add_text_panel("Machine not found", "Resolved issue history is not available for this machine.")
            return

        self._add_summary_hero(summary, active_issues, resolved_issues, summary.open_issue_count, stats.total_resolved)
        self._add_issue_history(summary.machine_number, active_issues, resolved_issues, stats, summary.open_issue_count)
        self._add_memory(stats, resolved_issues, snapshot.patterns_text)
        self._add_trends(snapshot)
        self.content_layout.addStretch(1)
        QTimer.singleShot(0, lambda target=snapshot.section: self._focus_section(target))

    def _add_summary_hero(
        self,
        machine: MachineSummary,
        active_issues: list[Issue],
        resolved_issues: list[ResolvedIssue],
        active_total: int,
        resolved_total: int,
    ) -> None:
        panel = QFrame()
        panel.setObjectName("summaryHero")
        panel.setProperty("statusState", status_state(machine.calculated_status))
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        title_row = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setContentsMargins(0, 0, 0, 0)
        title_block.setSpacing(2)
        title = QLabel(f"Machine {machine.machine_number}")
        title.setObjectName("machineNumber")
        subtitle = QLabel(_display(machine.name))
        subtitle.setObjectName("subtitleLabel")
        meta = QLabel(_machine_identity_text(machine))
        meta.setObjectName("mutedLabel")
        meta.setWordWrap(True)
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        title_block.addWidget(meta)
        title_row.addLayout(title_block, 1)
        title_row.addWidget(StatusBadge(machine.calculated_status))
        layout.addLayout(title_row)

        last_updated = _last_updated(active_issues, resolved_issues)
        cards = (
            _fact_card("Machine Number", machine.machine_number),
            _fact_card("Model / Name", machine.name),
            _fact_card("Area", machine.area),
            _fact_card("Cell", machine.cell),
            _fact_card("Asset Tag", machine.asset_tag),
            _fact_card("Current Status", machine.calculated_status, status=machine.calculated_status),
            _fact_card("Open Issues", str(active_total)),
            _fact_card("Resolved Issues", str(resolved_total)),
            _fact_card("Highest Severity", machine.calculated_status, status=machine.calculated_status),
            _fact_card("Last Updated", last_updated),
        )
        layout.addLayout(_card_grid(cards, columns=5))

        self._sections["overview"] = panel
        self.content_layout.addWidget(panel)
        repolish(panel)

    def _add_current_status(
        self,
        machine: MachineSummary,
        active_issues: list[Issue],
        resolved_issues: list[ResolvedIssue],
        active_total: int,
        resolved_total: int,
    ) -> None:
        panel = self._panel("Current Status", "status")
        layout = panel.layout()
        assert layout is not None
        last_updated = _last_updated(active_issues, resolved_issues)
        cards = (
            _fact_card("Machine Status", machine.calculated_status, status=machine.calculated_status),
            _fact_card("Open Issues", str(active_total)),
            _fact_card("Highest Severity", machine.calculated_status, status=machine.calculated_status),
            _fact_card("Resolved History", str(resolved_total)),
            _fact_card("Last Updated", last_updated),
        )
        layout.addLayout(_card_grid(cards, columns=5))
        panel.setProperty("statusState", status_state(machine.calculated_status))
        repolish(panel)
        self.content_layout.addWidget(panel)

    def _add_issue_history(
        self,
        machine_number: str,
        active_issues: list[Issue],
        resolved_issues: list[ResolvedIssue],
        stats: MachineResolvedStats,
        active_total: int,
    ) -> None:
        panel = self._panel("Issue History", "history")
        layout = panel.layout()
        assert layout is not None
        most_recent = _most_recent_issue_text(active_issues, resolved_issues)
        summary_cards = (
            _fact_card("Active", str(active_total)),
            _fact_card("Resolved", str(stats.total_resolved)),
            _fact_card("Common Category", stats.most_common_category),
            _fact_card("Average Time To Resolve", _duration_seconds_text(stats.average_time_open_seconds)),
            _fact_card("Most Recent Issue", most_recent),
        )
        layout.addLayout(_card_grid(summary_cards, columns=5))

        active_list = IssueListView("active", "Active/Open Issues", "Search active issues...", show_log_action=True)
        active_list.set_log_action_enabled(self._can_report)
        active_list.log_issue_requested.connect(lambda: self._request_log_issue(machine_number))
        active_list.resolve_requested.connect(self.resolve_issue_requested.emit)
        active_list.detail_requested.connect(self.issue_detail_requested.emit)
        active_list.criteria_changed.connect(self._refresh_issue_history_lists)
        self.active_history_list = active_list
        layout.addWidget(active_list)

        resolved_list = IssueListView("resolved", "Related History", "Search resolved issues...")
        resolved_list.detail_requested.connect(self.issue_detail_requested.emit)
        resolved_list.criteria_changed.connect(self._refresh_issue_history_lists)
        self.resolved_history_list = resolved_list
        layout.addWidget(resolved_list)
        active_list.set_query_result(active_issues, matched=active_total, total=active_total)
        resolved_list.set_query_result(resolved_issues, matched=stats.total_resolved, total=stats.total_resolved)
        self.content_layout.addWidget(panel)

    def _refresh_issue_history_lists(self) -> None:
        if not self.machine_number or self.active_history_list is None or self.resolved_history_list is None:
            return
        active_query, active_sort, active_limit, active_offset = self.active_history_list.criteria()
        resolved_query, resolved_sort, resolved_limit, resolved_offset = self.resolved_history_list.criteria()
        active_issues = self.repository.list_active_issues(
            self.machine_number,
            query=active_query,
            sort_key=active_sort,
            limit=active_limit,
            offset=active_offset,
        )
        resolved_issues = self.repository.list_resolved_issues(
            self.machine_number,
            query=resolved_query,
            sort_key=resolved_sort,
            limit=resolved_limit,
            offset=resolved_offset,
        )
        self.active_history_list.set_query_result(
            active_issues,
            matched=self.repository.count_active_issues_matching(self.machine_number, active_query),
            total=self.repository.count_total_active_issues(self.machine_number),
        )
        self.resolved_history_list.set_query_result(
            resolved_issues,
            matched=self.repository.count_resolved_issues_matching(self.machine_number, resolved_query),
            total=self.repository.count_total_resolved_issues(self.machine_number),
        )

    def _add_trends(self, snapshot: MachineDetailsSnapshot) -> None:
        panel = GraphTrendsPanel(self.theme_manager)
        panel.set_data(
            snapshot.trend,
            category_counts=snapshot.category_counts,
            severity_counts=snapshot.severity_counts,
        )
        self._sections["trends"] = panel
        self.content_layout.addWidget(panel)

    def _add_memory(
        self,
        stats: MachineResolvedStats,
        resolved_issues: list[ResolvedIssue],
        patterns_text: str,
    ) -> None:
        panel = self._panel("Troubleshooting Memory", "memory")
        layout = panel.layout()
        assert layout is not None
        if stats.total_resolved == 0:
            layout.addWidget(
                self._muted(
                    "No resolved history yet. Troubleshooting memory will appear here after issues are resolved."
                )
            )
            self.content_layout.addWidget(panel)
            return

        cards = (
            _fact_card("Repeated Problems", stats.recurring_warning or stats.most_common_title or "No repeat pattern detected"),
            _fact_card("Successful Fixes", _common_solution_text(resolved_issues)),
            _fact_card("Average Resolution Time", _duration_seconds_text(stats.average_time_open_seconds)),
            _fact_card("Common Categories", _common_category_text(resolved_issues, stats)),
            _fact_card("Common Corrective Actions", _common_solution_text(resolved_issues)),
        )
        layout.addLayout(_card_grid(cards, columns=3))
        if self.predictive_service is not None:
            layout.addWidget(_fact_card("Recurring Patterns", patterns_text))
        self.content_layout.addWidget(panel)

    def set_can_report(self, enabled: bool) -> None:
        self._can_report = enabled
        if self.active_history_list is not None:
            self.active_history_list.set_log_action_enabled(enabled)

    def _request_log_issue(self, machine_number: str) -> None:
        logger.debug("Add Issue clicked for machine %s", machine_number)
        self.log_issue_requested.emit(machine_number)

    def _build_section_nav(self) -> QHBoxLayout:
        nav = QHBoxLayout()
        nav.setSpacing(8)
        for label, section in (
            ("Overview", "overview"),
            ("Issue History", "history"),
            ("Trends", "trends"),
            ("Memory", "memory"),
        ):
            button = QPushButton(label)
            button.setObjectName("sectionNavButton")
            button.clicked.connect(lambda _checked=False, target=section: self._focus_section(target))
            self._section_nav_buttons[section] = button
            nav.addWidget(button)
        nav.addStretch(1)
        return nav

    def _panel(self, title: str, section: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("infoPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        layout.addWidget(title_label)
        self._sections[section] = panel
        return panel

    def _add_text_panel(self, title: str, text: str, *, section: str | None = None) -> None:
        panel = self._panel(title, section or title.casefold().replace(" ", "_"))
        layout = panel.layout()
        assert layout is not None
        body = QLabel(text or NO_DATA_TEXT)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(body)
        self.content_layout.addWidget(panel)

    @staticmethod
    def _muted(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("mutedLabel")
        label.setWordWrap(True)
        return label

    def _focus_section(self, section: str) -> None:
        active_section = section if section in self._sections else "overview"
        for button_section, button in self._section_nav_buttons.items():
            button.setProperty("active", "true" if button_section == active_section else "false")
            repolish(button)
        target = self._sections.get(active_section) or self._sections.get("overview")
        if target is not None:
            self.scroll.ensureWidgetVisible(target, 0, 12)

    def _clear_content(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            child_layout = item.layout()
            if child_layout:
                _clear_layout(child_layout)


def _fact_card(label: str, value: str | None, *, status: str | None = None) -> QFrame:
    card = QFrame()
    card.setObjectName("factCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 9, 12, 10)
    layout.setSpacing(4)
    label_widget = QLabel(label)
    label_widget.setObjectName("metricLabel")
    layout.addWidget(label_widget)
    display_value = _display(value)
    if status:
        layout.addWidget(StatusBadge(display_value))
    else:
        value_widget = QLabel(display_value)
        value_widget.setObjectName("largeMetricValue" if len(display_value) <= 18 else "metricValue")
        value_widget.setWordWrap(True)
        value_widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(value_widget)
    return card


def _card_grid(cards: Iterable[QWidget], *, columns: int) -> QGridLayout:
    grid = QGridLayout()
    grid.setHorizontalSpacing(10)
    grid.setVerticalSpacing(10)
    for index, card in enumerate(cards):
        grid.addWidget(card, index // columns, index % columns)
    return grid


def _highest_severity(active_issues: list[Issue]) -> str:
    if any(issue.severity == LINE_DOWN for issue in active_issues):
        return LINE_DOWN
    if any(issue.severity == NON_CRITICAL for issue in active_issues):
        return NON_CRITICAL
    if active_issues:
        return active_issues[0].severity or NO_ISSUES
    return NO_ISSUES


def _last_updated(active_issues: list[Issue], resolved_issues: list[ResolvedIssue]) -> str:
    values = []
    for issue in active_issues:
        values.extend([issue.updated_at, issue.created_at])
    for issue in resolved_issues:
        values.extend([issue.resolved_at, issue.created_at])
    dated = [(parse_timestamp(value), value) for value in values if value]
    dated = [(parsed, raw) for parsed, raw in dated if parsed.year > 1]
    if not dated:
        return NO_DATA_TEXT
    return format_timestamp(max(dated, key=lambda item: item[0])[1])


def _most_recent_issue_text(active_issues: list[Issue], resolved_issues: list[ResolvedIssue]) -> str:
    candidates = []
    for issue in active_issues:
        candidates.append((parse_timestamp(issue.created_at), issue.title))
    for issue in resolved_issues:
        candidates.append((parse_timestamp(issue.resolved_at), issue.title))
    candidates = [(parsed, title) for parsed, title in candidates if parsed.year > 1 and title]
    if not candidates:
        return "No issue history yet"
    return preview_text(max(candidates, key=lambda item: item[0])[1], 80)


def _machine_identity_text(machine: MachineSummary) -> str:
    parts = [
        " / ".join(part for part in (machine.area, machine.cell) if part),
        f"Asset {machine.asset_tag}" if machine.asset_tag else "",
        f"{machine.manufacturer} {machine.model}".strip(),
        f"IMM Serial {machine.imm_serial}" if machine.imm_serial else "",
        f"Robot {machine.robot_type} {machine.robot_model}".strip() if machine.robot_type or machine.robot_model else "",
    ]
    return " | ".join(part for part in parts if part) or NO_DATA_TEXT


def _common_solution_text(resolved_issues: list[ResolvedIssue]) -> str:
    solutions = Counter(_compact_text(issue.solution) for issue in resolved_issues if _compact_text(issue.solution))
    if not solutions:
        return "No fix patterns yet"
    return " | ".join(f"{preview_text(solution, 70)} ({count})" for solution, count in solutions.most_common(3))


def _common_category_text(resolved_issues: list[ResolvedIssue], stats: MachineResolvedStats) -> str:
    categories = Counter(_compact_text(issue.category) or "Uncategorized" for issue in resolved_issues)
    if not categories and stats.most_common_category:
        return stats.most_common_category
    if not categories:
        return NO_DATA_TEXT
    return " | ".join(f"{category}: {count}" for category, count in categories.most_common(4))


def _patterns_text(service: PredictiveMaintenanceService, machine_number: str) -> str:
    return _patterns_display_text(service.get_recurring_patterns(machine_number=machine_number))


def _patterns_display_text(patterns) -> str:
    if not patterns:
        return "No recurring patterns detected yet"
    return " | ".join(f"{pattern.display_label} ({pattern.occurrence_count})" for pattern in patterns[:4])


def _duration_seconds_text(seconds: int | None) -> str:
    if seconds is None:
        return NO_DATA_TEXT
    return _format_seconds(seconds)


def _display(value: str | None) -> str:
    text = _compact_text(value)
    return text or NO_DATA_TEXT


def _compact_text(value: str | None) -> str:
    return " ".join(str(value or "").split())


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.deleteLater()
        child_layout = item.layout()
        if child_layout:
            _clear_layout(child_layout)
