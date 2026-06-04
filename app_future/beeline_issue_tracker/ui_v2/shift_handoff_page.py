from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.domain import Issue, ResolvedIssue, display_issue_id
from beeline_issue_tracker.future_features import KnownFix, MachineOpenCluster, ShiftHandoffSummary, issue_age
from beeline_issue_tracker.perf import elapsed_ms, log as perf_log, now as perf_now
from beeline_issue_tracker.ui_v2.issue_list_model import format_timestamp, preview_text
from beeline_issue_tracker.ui_v2.theme import ThemeManager
from beeline_issue_tracker.ui_v2.widgets import BrandHeader, EmptyStatePanel, HoneycombBackground, MetricPill, StatusBadge


@dataclass(frozen=True)
class ShiftHandoffSnapshot:
    summary: ShiftHandoffSummary
    window_label: str


def load_shift_handoff_snapshot(repository: IssueRepository, window_key: str) -> ShiftHandoffSnapshot:
    started_at = perf_now()
    start_at, end_at, label = _handoff_window(window_key)
    summary = repository.build_shift_handoff_summary(start_at, end_at)
    perf_log("shift_handoff.load", window=window_key, elapsed_ms=elapsed_ms(started_at))
    return ShiftHandoffSnapshot(summary=summary, window_label=label)


class ShiftHandoffPage(HoneycombBackground):
    back_requested = Signal()
    refresh_requested = Signal()
    issue_open_requested = Signal(str, int)
    machine_requested = Signal(str)

    def __init__(self, theme_manager: ThemeManager, paths: AppPaths, parent=None):
        super().__init__(theme_manager, parent)
        self.theme_manager = theme_manager
        self.paths = paths
        self._snapshot: ShiftHandoffSnapshot | None = None

        page = QVBoxLayout(self)
        page.setContentsMargins(24, 22, 24, 22)
        page.setSpacing(16)

        header = QHBoxLayout()
        back = QPushButton("Back")
        back.setObjectName("quietButton")
        back.clicked.connect(self.back_requested.emit)
        header.addWidget(back)
        header.addWidget(BrandHeader("Shift Handoff", "Current shift summary", paths.logo_path(), theme_manager), 1)
        self.window = QComboBox()
        self.window.setObjectName("compactDropdown")
        self.window.addItem("Last 8 Hours", "8h")
        self.window.addItem("Last 12 Hours", "12h")
        self.window.addItem("Today", "today")
        self.window.currentIndexChanged.connect(self.refresh_requested.emit)
        header.addWidget(self.window)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("secondaryButton")
        refresh.clicked.connect(self.refresh_requested.emit)
        header.addWidget(refresh)
        copy = QPushButton("Copy Summary")
        copy.setObjectName("secondaryButton")
        copy.clicked.connect(self.copy_summary)
        header.addWidget(copy)
        export = QPushButton("Export TXT")
        export.setObjectName("secondaryButton")
        export.clicked.connect(self.export_summary)
        header.addWidget(export)
        page.addLayout(header)

        self.summary_panel = QFrame()
        self.summary_panel.setObjectName("infoPanel")
        summary_layout = QHBoxLayout(self.summary_panel)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(10)
        self.line_down_pill = MetricPill("Line Down")
        self.stale_pill = MetricPill("Stale")
        self.opened_pill = MetricPill("Opened")
        self.resolved_pill = MetricPill("Resolved")
        self.archive_pill = MetricPill("Archive")
        for pill in (self.line_down_pill, self.stale_pill, self.opened_pill, self.resolved_pill, self.archive_pill):
            summary_layout.addWidget(pill)
        summary_layout.addStretch(1)
        page.addWidget(self.summary_panel)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("transparentHost")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        self.scroll.setWidget(self.content)
        page.addWidget(self.scroll, 1)

    def current_window_key(self) -> str:
        return self.window.currentData() or "8h"

    def show_loading(self) -> None:
        self._snapshot = None
        self._clear_content()
        self.content_layout.addWidget(EmptyStatePanel("Loading shift handoff", "BeeLine Future is building a bounded SQLite summary."))

    def apply_snapshot(self, snapshot: ShiftHandoffSnapshot) -> None:
        self._snapshot = snapshot
        summary = snapshot.summary
        self.line_down_pill.set_value(str(len(summary.current_line_down)))
        self.stale_pill.set_value(str(len(summary.current_stale)))
        self.opened_pill.set_value(str(len(summary.opened)))
        self.resolved_pill.set_value(str(len(summary.resolved)))
        archive_text = f"{summary.archive_failed_count} failed"
        if summary.archive_pending_count:
            archive_text += f", {summary.archive_pending_count} pending"
        self.archive_pill.set_value(archive_text)

        self._clear_content()
        self._add_panel("Window", [f"{snapshot.window_label}: {format_timestamp(summary.start_at)} to {format_timestamp(summary.end_at)}"])
        self._add_issue_panel("Current Line Down", summary.current_line_down, active=True)
        self._add_issue_panel("Current Stale", summary.current_stale, active=True)
        self._add_issue_panel("Opened During Window", summary.opened, active=True)
        self._add_issue_panel("Resolved During Window", summary.resolved, active=False)
        self._add_cluster_panel(summary.multiple_open)
        self._add_known_fix_panel(summary.recurring_patterns)
        self._add_panel(
            "Archive",
            [
                f"Pending writes: {summary.archive_pending_count}",
                f"Failed writes: {summary.archive_failed_count}",
            ],
        )
        self.content_layout.addStretch(1)

    def copy_summary(self) -> None:
        if self._snapshot is None:
            return
        QApplication.clipboard().setText(summary_to_text(self._snapshot.summary, self._snapshot.window_label))

    def export_summary(self) -> None:
        if self._snapshot is None:
            return
        export_dir = self.paths.root_dir / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = export_dir / f"beeline_shift_handoff_{stamp}.txt"
        path.write_text(summary_to_text(self._snapshot.summary, self._snapshot.window_label), encoding="utf-8")

    def _add_issue_panel(self, title: str, issues: list[Issue] | list[ResolvedIssue], *, active: bool) -> None:
        if not issues:
            self._add_panel(title, ["None"])
            return
        panel = self._panel(title)
        layout = panel.layout()
        assert layout is not None
        for issue in issues[:50]:
            layout.addWidget(self._issue_row(issue, active=active))
        self.content_layout.addWidget(panel)

    def _issue_row(self, issue: Issue | ResolvedIssue, *, active: bool) -> QWidget:
        row = QFrame()
        row.setObjectName("factCard")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        if active and isinstance(issue, Issue):
            age = issue_age(issue)
            meta = f"{display_issue_id(issue)} | Machine {issue.machine_number} | {age.label} | {age.state}"
            mode = "active"
            issue_id = issue.id
        else:
            meta = f"{display_issue_id(issue)} | Machine {issue.machine_number} | Resolved {format_timestamp(issue.resolved_at)}"
            mode = "resolved"
            issue_id = issue.id
        title = QLabel(f"{preview_text(issue.title, 90)}\n{meta}")
        title.setWordWrap(True)
        layout.addWidget(title, 1)
        layout.addWidget(StatusBadge(issue.severity))
        open_button = QPushButton("Open")
        open_button.setObjectName("tableActionButton")
        open_button.clicked.connect(lambda _checked=False, m=mode, value=issue_id: self.issue_open_requested.emit(m, value))
        machine_button = QPushButton("Machine")
        machine_button.setObjectName("tableActionButton")
        machine_button.clicked.connect(lambda _checked=False, value=issue.machine_number: self.machine_requested.emit(value))
        layout.addWidget(open_button)
        layout.addWidget(machine_button)
        return row

    def _add_cluster_panel(self, clusters: list[MachineOpenCluster]) -> None:
        if not clusters:
            self._add_panel("Machines With Multiple Open Issues", ["None"])
            return
        lines = [
            f"Machine {cluster.machine_number} | {cluster.machine_name}: {cluster.open_count} open, {cluster.line_down_count} line down"
            for cluster in clusters
        ]
        self._add_panel("Machines With Multiple Open Issues", lines)

    def _add_known_fix_panel(self, fixes: list[KnownFix]) -> None:
        if not fixes:
            self._add_panel("Recurring Patterns In Window", ["None"])
            return
        lines = [
            f"{fix.pattern} | {fix.category} | seen {fix.times_seen} | common fix: {fix.solution_preview}"
            for fix in fixes
        ]
        self._add_panel("Recurring Patterns In Window", lines)

    def _add_panel(self, title: str, lines: list[str]) -> None:
        panel = self._panel(title)
        layout = panel.layout()
        assert layout is not None
        for line in lines:
            label = QLabel(line)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(label)
        self.content_layout.addWidget(panel)

    def _panel(self, title: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("infoPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        layout.addWidget(title_label)
        return panel

    def _clear_content(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            child_layout = item.layout()
            if child_layout:
                _clear_layout(child_layout)


def summary_to_text(summary: ShiftHandoffSummary, window_label: str) -> str:
    lines = [
        "BeeLine Future Shift Handoff",
        f"Window: {window_label}",
        f"Start: {summary.start_at}",
        f"End: {summary.end_at}",
        "",
        f"Current line down: {len(summary.current_line_down)}",
        *[f"- {display_issue_id(issue)} | Machine {issue.machine_number} | {issue.title}" for issue in summary.current_line_down],
        "",
        f"Current stale: {len(summary.current_stale)}",
        *[f"- {display_issue_id(issue)} | Machine {issue.machine_number} | {issue_age(issue).state} | {issue.title}" for issue in summary.current_stale],
        "",
        f"Opened: {len(summary.opened)}",
        *[f"- {display_issue_id(issue)} | Machine {issue.machine_number} | {issue.title}" for issue in summary.opened],
        "",
        f"Resolved: {len(summary.resolved)}",
        *[f"- {display_issue_id(issue)} | Machine {issue.machine_number} | {issue.title}" for issue in summary.resolved],
        "",
        f"Archive pending: {summary.archive_pending_count}",
        f"Archive failed: {summary.archive_failed_count}",
    ]
    return "\n".join(lines)


def _handoff_window(window_key: str) -> tuple[str, str, str]:
    local_now = datetime.now().astimezone()
    if window_key == "12h":
        start = local_now - timedelta(hours=12)
        label = "Last 12 Hours"
    elif window_key == "today":
        start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = "Today"
    else:
        start = local_now - timedelta(hours=8)
        label = "Last 8 Hours"
    end = local_now
    return (
        start.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        end.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        label,
    )


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.deleteLater()
        child_layout = item.layout()
        if child_layout:
            _clear_layout(child_layout)
