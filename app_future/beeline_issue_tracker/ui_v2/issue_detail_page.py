from __future__ import annotations

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

from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.analytics.models import FixSuggestion, RecurringIssuePattern, RelatedIssueMatch
from beeline_issue_tracker.domain import (
    IssueAttachment,
    IssueWithMachineContext,
    ResolvedIssue,
    ResolvedIssueWithMachineContext,
    display_issue_id,
)
from beeline_issue_tracker.future_features import issue_age
from beeline_issue_tracker.ui_v2.issue_list_model import format_duration_between, format_timestamp, preview_text
from beeline_issue_tracker.ui_v2.theme import ThemeManager, repolish, status_state
from beeline_issue_tracker.ui_v2.widgets import (
    BrandHeader,
    EmptyStatePanel,
    HoneycombBackground,
    InfoRow,
    MetricPill,
    PrimaryActionButton,
    StatusBadge,
)


class IssueDetailPage(HoneycombBackground):
    back_requested = Signal()
    machine_requested = Signal(str)
    resolve_requested = Signal(int)
    related_issue_requested = Signal(str, int)

    def __init__(self, theme_manager: ThemeManager, paths: AppPaths, parent=None):
        super().__init__(theme_manager, parent)
        self.theme_manager = theme_manager
        self.paths = paths
        self._machine_number = ""
        self._active_issue_id: int | None = None

        page = QVBoxLayout(self)
        page.setContentsMargins(24, 22, 24, 22)
        page.setSpacing(16)

        nav = QHBoxLayout()
        self.back_button = QPushButton("Back")
        self.back_button.setObjectName("quietButton")
        self.back_button.clicked.connect(self.back_requested.emit)
        nav.addWidget(self.back_button)
        self.machine_button = QPushButton("Go to Machine")
        self.machine_button.setObjectName("secondaryButton")
        self.machine_button.clicked.connect(self._go_to_machine)
        nav.addWidget(self.machine_button)
        nav.addStretch(1)
        page.addLayout(nav)

        self.header = QFrame()
        self.header.setObjectName("machineHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(14)
        self.brand_header = BrandHeader("Issue Detail", "", paths.logo_path(), theme_manager)
        header_layout.addWidget(self.brand_header, 1)
        self.status_badge = StatusBadge("Unknown/Error")
        header_layout.addWidget(self.status_badge)
        self.resolve_button = PrimaryActionButton("Resolve Issue")
        self.resolve_button.clicked.connect(self._resolve_current)
        header_layout.addWidget(self.resolve_button)
        page.addWidget(self.header)

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

    def show_loading(self, mode: str, issue_id: int) -> None:
        self._machine_number = ""
        self._active_issue_id = None
        self.resolve_button.setVisible(mode == "active")
        self._set_header("Issue Detail", "Unknown/Error", f"Loading {mode} issue {issue_id}...")
        self._clear_content()
        self._add_text_panel("Loading", "Loading issue details...")

    def load_active(
        self,
        context: IssueWithMachineContext,
        *,
        related_issues: list[ResolvedIssue] | None = None,
        related_matches: list[RelatedIssueMatch] | None = None,
        fix_suggestions: list[FixSuggestion] | None = None,
        trend_summary: dict[str, int] | None = None,
        attachments: list[IssueAttachment] | None = None,
    ) -> None:
        issue = context.issue
        self._machine_number = issue.machine_number
        self._active_issue_id = issue.id
        self.resolve_button.show()
        self._set_header(issue.title, issue.severity, _machine_subtitle(context))
        self._clear_content()
        self._add_metric_row(
            (
                ("Issue ID", display_issue_id(issue)),
                ("Machine", issue.machine_number),
                ("Area", context.machine.area if context.machine else "-"),
                ("Cell", context.machine.cell if context.machine else "-"),
                ("Asset", context.machine.asset_tag if context.machine else "-"),
                ("Age", format_duration_between(issue.created_at)),
                ("Age Flag", issue_age(issue).state),
            )
        )
        self._add_text_panel("Problem Description", issue.description)
        if issue.what_changed:
            self._add_text_panel("What Changed?", issue.what_changed)
        if issue.tried_already:
            self._add_text_panel("Tried Already", issue.tried_already)
        self._add_info_panel(
            "Metadata",
            (
                ("Machine name", context.machine.name if context.machine else "-"),
                ("Logged by", issue.logged_by),
                ("Created", format_timestamp(issue.created_at)),
                ("Updated", format_timestamp(issue.updated_at)),
                ("Category", issue.category or "-"),
                ("Internal record ID", str(issue.id)),
            ),
        )
        self._add_future_sections(
            related_issues or [],
            trend_summary or {},
            attachments or [],
            related_matches=related_matches or [],
            fix_suggestions=fix_suggestions or [],
            show_fix_empty=True,
        )
        self.content_layout.addStretch(1)

    def load_resolved(
        self,
        context: ResolvedIssueWithMachineContext,
        *,
        trend_summary: dict[str, int] | None = None,
        attachments: list[IssueAttachment] | None = None,
        related_matches: list[RelatedIssueMatch] | None = None,
        recurring_patterns: list[RecurringIssuePattern] | None = None,
    ) -> None:
        issue = context.issue
        self._machine_number = issue.machine_number
        self._active_issue_id = None
        self.resolve_button.hide()
        self._set_header(issue.title, issue.severity, _machine_subtitle(context))
        self._clear_content()
        self._add_metric_row(
            (
                ("Issue ID", display_issue_id(issue)),
                ("Machine", issue.machine_number),
                ("Area", context.machine.area if context.machine else "-"),
                ("Cell", context.machine.cell if context.machine else "-"),
                ("Asset", context.machine.asset_tag if context.machine else "-"),
                ("Time open", format_duration_between(issue.created_at, issue.resolved_at)),
            )
        )
        self._add_text_panel("Problem Description", issue.description)
        if issue.what_changed:
            self._add_text_panel("What Changed?", issue.what_changed)
        if issue.tried_already:
            self._add_text_panel("Tried Already", issue.tried_already)
        self._add_text_panel("Solution/Fix", issue.solution)
        archive_status = issue.archive_status
        if issue.archive_error:
            archive_status = f"{archive_status}: {issue.archive_error}"
        self._add_info_panel(
            "Metadata",
            (
                ("Machine name", context.machine.name if context.machine else "-"),
                ("Logged by", issue.logged_by),
                ("Resolved by", issue.resolved_by or "-"),
                ("Created", format_timestamp(issue.created_at)),
                ("Resolved", format_timestamp(issue.resolved_at)),
                ("Category", issue.category or "-"),
                ("Original numeric ID", str(issue.original_issue_id)),
                ("Resolved/cache ID", str(issue.id)),
                ("Archive status", archive_status),
            ),
        )
        self._add_future_sections(
            [],
            trend_summary or {},
            attachments or [],
            related_matches=related_matches or [],
            recurring_patterns=recurring_patterns or [],
        )
        self.content_layout.addStretch(1)

    def _set_header(self, title: str, status: str, subtitle: str) -> None:
        self.brand_header.set_title(title)
        self.brand_header.set_subtitle(subtitle)
        self.status_badge.set_status(status)
        self.header.setProperty("statusState", status_state(status))
        repolish(self.header)

    def _add_metric_row(self, metrics: tuple[tuple[str, str], ...]) -> None:
        row = QHBoxLayout()
        row.setSpacing(10)
        for label, value in metrics:
            pill = MetricPill(label, value)
            row.addWidget(pill)
        row.addStretch(1)
        self.content_layout.addLayout(row)

    def _add_text_panel(self, title: str, text: str) -> None:
        panel = QFrame()
        panel.setObjectName("formPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        body = QLabel(text or "-")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(title_label)
        layout.addWidget(body)
        self.content_layout.addWidget(panel)

    def _add_info_panel(self, title: str, rows: tuple[tuple[str, str], ...]) -> None:
        panel = QFrame()
        panel.setObjectName("infoPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        layout.addWidget(title_label)
        for label, value in rows:
            layout.addWidget(InfoRow(label, value))
        self.content_layout.addWidget(panel)

    def _add_future_sections(
        self,
        related_issues: list[ResolvedIssue],
        trend_summary: dict[str, int],
        attachments: list[IssueAttachment],
        *,
        related_matches: list[RelatedIssueMatch] | None = None,
        fix_suggestions: list[FixSuggestion] | None = None,
        recurring_patterns: list[RecurringIssuePattern] | None = None,
        show_fix_empty: bool = False,
    ) -> None:
        related = related_matches or related_issues
        suggestions = (fix_suggestions or [])[:5]
        patterns = (recurring_patterns or [])[:5]
        has_intelligence = bool(related or attachments or suggestions or patterns or show_fix_empty)
        if suggestions:
            self._add_fix_suggestions_panel(suggestions)
        elif show_fix_empty:
            self._add_empty_state(
                "No suggested fixes yet",
                "Suggestions appear after similar resolved issues with fix text are found.",
            )
        if related:
            self._add_related_panel(related[:5])
        if patterns:
            self._add_recurring_patterns_panel(patterns)
        if attachments:
            attachment_text = "\n".join(
                f"{attachment.original_filename}{f' - {attachment.note}' if attachment.note else ''}"
                for attachment in attachments
            )
            self._add_text_panel("Attachments", attachment_text)
        if not has_intelligence:
            self._add_empty_state(
                "No related history yet",
                "BeeLine will suggest fixes once similar resolved issues exist.",
            )

    def _add_recurring_patterns_panel(self, patterns: list[RecurringIssuePattern]) -> None:
        if not patterns:
            return
        text = "\n".join(
            f"{pattern.display_label}: {pattern.risk_note}"
            for pattern in patterns[:5]
        )
        self._add_text_panel("Recurring Patterns", text)

    def _add_fix_suggestions_panel(self, suggestions: list[FixSuggestion]) -> None:
        if not suggestions:
            return
        panel = QFrame()
        panel.setObjectName("infoPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        title = QLabel("Suggested Fixes")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        for suggestion in suggestions:
            body = QLabel(
                f"{suggestion.title} | Confidence: {suggestion.confidence} | "
                f"Based on {suggestion.based_on_count} resolved issue(s)\n"
                f"{suggestion.suggestion}\n{suggestion.caution}"
            )
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(body)
        self.content_layout.addWidget(panel)

    def _add_related_panel(self, related_issues: list[ResolvedIssue] | list[RelatedIssueMatch]) -> None:
        if not related_issues:
            return
        panel = QFrame()
        panel.setObjectName("infoPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        title = QLabel("Related History")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        for issue in related_issues:
            row = QHBoxLayout()
            if isinstance(issue, RelatedIssueMatch):
                reasons = " | ".join(issue.match_reasons)
                label_text = (
                    f"{preview_text(issue.title, 80)} | {format_timestamp(issue.resolved_at or '')} | "
                    f"Match {issue.match_score}: {reasons}"
                )
                issue_id = issue.issue_id
            else:
                label_text = f"{display_issue_id(issue)} | {preview_text(issue.title, 80)} | {format_timestamp(issue.resolved_at)}"
                issue_id = issue.id
            label = QLabel(label_text)
            label.setWordWrap(True)
            row.addWidget(label, 1)
            button = QPushButton("Open")
            button.setObjectName("tableActionButton")
            button.clicked.connect(
                lambda _checked=False, resolved_issue_id=issue_id: self.related_issue_requested.emit("resolved", resolved_issue_id)
            )
            row.addWidget(button)
            layout.addLayout(row)
        self.content_layout.addWidget(panel)

    def _add_empty_state(self, title: str, body: str) -> None:
        self.content_layout.addWidget(EmptyStatePanel(title, body))

    def _clear_content(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            child_layout = item.layout()
            if child_layout:
                _clear_layout(child_layout)

    def _go_to_machine(self) -> None:
        if self._machine_number:
            self.machine_requested.emit(self._machine_number)

    def _resolve_current(self) -> None:
        if self._active_issue_id is not None:
            self.resolve_requested.emit(self._active_issue_id)


def _machine_subtitle(context: IssueWithMachineContext | ResolvedIssueWithMachineContext) -> str:
    issue = context.issue
    if context.machine is None:
        return f"Machine {issue.machine_number}"
    machine = context.machine
    location = " | ".join(part for part in (machine.area, machine.cell) if part)
    return f"Machine {machine.machine_number} | {machine.name}{f' | {location}' if location else ''}"


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.deleteLater()
        child_layout = item.layout()
        if child_layout:
            _clear_layout(child_layout)
