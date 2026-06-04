from __future__ import annotations

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.data.archive_search import (
    DEEP_SEARCH_LIMIT,
    QUICK_SEARCH_LIMIT,
    DeepArchiveSearchTask,
    search_result_dedupe_key,
)
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.domain import (
    LINE_DOWN,
    NON_CRITICAL,
    NO_ISSUES,
    STATUS_ORDER,
    IssueSearchResult,
    MachineSummary,
    display_issue_id,
)
from beeline_issue_tracker.perf import elapsed_ms, log as perf_log, now as perf_now
from beeline_issue_tracker.special import (
    PlantDeteriorationState,
    SpecialEffectsSettings,
    calculate_plant_deterioration,
)
from beeline_issue_tracker.ui_v2.issue_list_model import format_duration_between, format_timestamp, preview_text
from beeline_issue_tracker.ui_v2.theme import ThemeManager
from beeline_issue_tracker.ui_v2.widgets import BrandHeader, HoneycombBackground, MachineCard, MetricPill, SearchBox, StatusBadge


MIN_CARD_WIDTH = 320


class HiveDashboardPage(HoneycombBackground):
    machine_selected = Signal(str)
    issue_detail_requested = Signal(str, int)
    open_issues_requested = Signal()
    predictive_requested = Signal()
    special_state_changed = Signal(object)
    falling_drip_requested = Signal(str, str, object, int)

    def __init__(self, repository: IssueRepository, theme_manager: ThemeManager, paths: AppPaths, parent=None):
        super().__init__(theme_manager, parent)
        self.repository = repository
        self.theme_manager = theme_manager
        self.paths = paths
        self._machines: list[MachineSummary] = []
        self._machine_cards: dict[str, MachineCard] = {}
        self._special_settings = SpecialEffectsSettings()
        self._special_state = calculate_plant_deterioration((), self._special_settings)
        self._special_tick = 0
        self._last_card_layout: tuple[tuple[str, ...], int] | None = None
        self._search_results: list[IssueSearchResult] = []
        self._deep_task: DeepArchiveSearchTask | None = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(110)
        self._resize_timer.timeout.connect(self._render_dashboard)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._render_dashboard)
        self._special_timer = QTimer(self)
        self._special_timer.setInterval(66)
        self._special_timer.timeout.connect(self._advance_special_effects)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(24, 22, 24, 22)
        page_layout.setSpacing(18)

        header = QHBoxLayout()
        header.addWidget(BrandHeader("BeeLine Issue Tracker", "Hive Dashboard", paths.logo_path(), theme_manager))
        header.addStretch(1)
        open_issues = QPushButton("View All Open Issues")
        open_issues.setObjectName("primaryButton")
        open_issues.clicked.connect(self.open_issues_requested.emit)
        header.addWidget(open_issues)
        self.predictive_button = QPushButton("Predictive Maintenance")
        self.predictive_button.setObjectName("primaryButton")
        self.predictive_button.clicked.connect(self.predictive_requested.emit)
        header.addWidget(self.predictive_button)
        page_layout.addLayout(header)

        self.summary_panel = QFrame()
        self.summary_panel.setObjectName("infoPanel")
        summary_layout = QHBoxLayout(self.summary_panel)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(10)
        self.total_pill = MetricPill("Total Machines")
        self.open_pill = MetricPill("Open Issues")
        self.line_down_pill = MetricPill("Line Down")
        self.non_critical_pill = MetricPill("Non-Critical")
        self.no_issues_pill = MetricPill("No Issues")
        for pill in (
            self.total_pill,
            self.open_pill,
            self.line_down_pill,
            self.non_critical_pill,
            self.no_issues_pill,
        ):
            summary_layout.addWidget(pill)
        summary_layout.addStretch(1)
        page_layout.addWidget(self.summary_panel)

        controls_panel = QFrame()
        controls_panel.setObjectName("infoPanel")
        controls = QVBoxLayout(controls_panel)
        controls.setContentsMargins(14, 12, 14, 12)
        controls.setSpacing(10)
        self.search = SearchBox("Search issues, history, fixes, people, machines...")
        self.search.textChanged.connect(self._queue_search_render)
        self.issue_state = QComboBox()
        self.issue_state.setObjectName("compactDropdown")
        for label, value in (
            ("All Issues", "all"),
            ("Open Issues", "open"),
            ("Archived / Resolved", "resolved"),
        ):
            self.issue_state.addItem(label, value)
        self.issue_state.currentIndexChanged.connect(self._render_dashboard)
        self.search_mode = QComboBox()
        self.search_mode.setObjectName("compactDropdown")
        self.search_mode.addItem("Quick", "quick")
        self.search_mode.addItem("Deep", "deep")
        self.search_mode.setToolTip("Quick searches SQLite. Deep searches SQLite first, then the Excel archive.")
        self.search_mode.currentIndexChanged.connect(self._render_dashboard)
        self.cancel_deep = QPushButton("Cancel Deep Search")
        self.cancel_deep.setObjectName("tableActionButton")
        self.cancel_deep.clicked.connect(self._cancel_deep_search)
        self.cancel_deep.hide()
        self.sort = QComboBox()
        self.sort.setObjectName("compactDropdown")
        for label, value in (
            ("Plant Layout", "plant"),
            ("Severity", "severity"),
            ("Open Issues", "open_issues"),
            ("Machine A-Z", "machine_asc"),
            ("Machine Z-A", "machine_desc"),
        ):
            self.sort.addItem(label, value)
        self.sort.currentIndexChanged.connect(self._render_dashboard)
        self.area_filter = QComboBox()
        self.area_filter.setObjectName("compactDropdown")
        self.area_filter.currentIndexChanged.connect(self._render_dashboard)
        self.cell_filter = QComboBox()
        self.cell_filter.setObjectName("compactDropdown")
        self.cell_filter.currentIndexChanged.connect(self._render_dashboard)
        controls.addWidget(self.search)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)
        filter_row.addWidget(QLabel("State"))
        filter_row.addWidget(self.issue_state)
        filter_row.addWidget(QLabel("Mode"))
        filter_row.addWidget(self.search_mode)
        filter_row.addWidget(self.cancel_deep)
        filter_row.addWidget(QLabel("Sort"))
        filter_row.addWidget(self.sort)
        filter_row.addWidget(QLabel("Area"))
        filter_row.addWidget(self.area_filter)
        filter_row.addWidget(QLabel("Cell"))
        filter_row.addWidget(self.cell_filter)
        filter_row.addStretch(1)
        controls.addLayout(filter_row)
        page_layout.addWidget(controls_panel)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("transparentHost")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(18)
        self.scroll.setWidget(self.grid_host)
        page_layout.addWidget(self.scroll, 1)

        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results_host = QWidget()
        self.results_host.setObjectName("transparentHost")
        self.results_layout = QVBoxLayout(self.results_host)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(12)
        self.results_scroll.setWidget(self.results_host)
        self.results_scroll.hide()
        page_layout.addWidget(self.results_scroll, 1)

    def refresh(self) -> None:
        started_at = perf_now()
        call_started = perf_now()
        self._machines = self.repository.list_machines_with_status()
        perf_log("repo.list_machines_with_status", count=len(self._machines), elapsed_ms=elapsed_ms(call_started))
        self._update_summary()
        self._recalculate_special_state()
        self._update_filter_options()
        self._render_dashboard()
        perf_log("dashboard.refresh_internal", machines=len(self._machines), elapsed_ms=elapsed_ms(started_at))

    @property
    def special_state(self) -> PlantDeteriorationState:
        return self._special_state

    def set_special_effects_settings(self, settings: SpecialEffectsSettings) -> None:
        self._special_settings = settings
        self._recalculate_special_state()
        self._apply_special_effects_to_cards()

    def set_can_open_predictive_maintenance(self, enabled: bool) -> None:
        self.predictive_button.setVisible(enabled)

    def special_effects_settings(self) -> SpecialEffectsSettings:
        return self._special_settings

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_timer.start()

    def _update_summary(self) -> None:
        machines = self._machines
        open_total = sum(machine.open_issue_count for machine in machines)
        line_down_total = sum(1 for machine in machines if machine.calculated_status == LINE_DOWN)
        non_critical_total = sum(1 for machine in machines if machine.calculated_status == NON_CRITICAL)
        no_issues_total = sum(1 for machine in machines if machine.calculated_status == NO_ISSUES)
        self.total_pill.set_value(str(len(machines)))
        self.open_pill.set_value(str(open_total))
        self.line_down_pill.set_value(str(line_down_total))
        self.non_critical_pill.set_value(str(non_critical_total))
        self.no_issues_pill.set_value(str(no_issues_total))

    def _recalculate_special_state(self) -> None:
        next_state = calculate_plant_deterioration(self._machines, self._special_settings)
        self._special_state = next_state
        self.special_state_changed.emit(next_state)
        if next_state.effect_active and not self._special_timer.isActive():
            self._special_timer.start()
        elif not next_state.effect_active and self._special_timer.isActive():
            self._special_timer.stop()
            self._special_tick = 0

    def _update_filter_options(self) -> None:
        self._set_filter_options(self.area_filter, sorted({m.area for m in self._machines if m.area}))
        self._set_filter_options(self.cell_filter, sorted({m.cell for m in self._machines if m.cell}))

    def _set_filter_options(self, combo: QComboBox, values: list[str]) -> None:
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("All", "")
        for value in values:
            combo.addItem(value, value)
        next_index = combo.findData(current)
        combo.setCurrentIndex(next_index if next_index >= 0 else 0)
        combo.setVisible(bool(values))
        combo.blockSignals(False)

    def _render_dashboard(self) -> None:
        if self._has_issue_query():
            self.scroll.hide()
            self.results_scroll.show()
            self._render_issue_results()
            return
        self.results_scroll.hide()
        self.scroll.show()
        self._render_cards()

    def _render_cards(self) -> None:
        started_at = perf_now()
        self._clear_layout(self.results_layout)
        current_numbers = {machine.machine_number for machine in self._machines}
        removed = 0
        for machine_number in tuple(self._machine_cards):
            if machine_number not in current_numbers:
                card = self._machine_cards.pop(machine_number)
                card.setParent(None)
                card.deleteLater()
                removed += 1
                self._last_card_layout = None

        machines = self._filtered_machines()
        columns = self._column_count()
        visible_numbers_ordered = tuple(machine.machine_number for machine in machines)
        layout_key = (visible_numbers_ordered, columns)
        layout_rebuilt = layout_key != self._last_card_layout
        if layout_rebuilt:
            self._detach_grid_widgets()
        created = 0
        updated = 0
        for index, machine in enumerate(machines):
            card = self._machine_cards.get(machine.machine_number)
            if card is None:
                card = MachineCard(machine)
                card.clicked.connect(self.machine_selected.emit)
                self._machine_cards[machine.machine_number] = card
                created += 1
                layout_rebuilt = True
            else:
                card.update_machine(machine)
                updated += 1
            card.set_special_effect_state(self._special_state, self._special_tick, self._special_settings)
            card.show()
            if layout_rebuilt:
                self.grid.addWidget(card, index // columns, index % columns)
        visible_numbers = {machine.machine_number for machine in machines}
        for machine_number, card in self._machine_cards.items():
            if machine_number not in visible_numbers:
                card.hide()
        if layout_rebuilt:
            self.grid.setRowStretch((len(machines) // columns) + 1, 1)
            self._last_card_layout = layout_key
        perf_log(
            "dashboard.render_cards",
            visible=len(machines),
            cached=len(self._machine_cards),
            created=created,
            updated=updated,
            removed=removed,
            layout_rebuilt=layout_rebuilt,
            elapsed_ms=elapsed_ms(started_at),
        )

    def _advance_special_effects(self) -> None:
        if not self._special_state.effect_active:
            return
        self._special_tick += 1
        self._apply_special_effects_to_cards()

    def _apply_special_effects_to_cards(self) -> None:
        for card in self._machine_cards.values():
            card.set_special_effect_state(self._special_state, self._special_tick, self._special_settings)
            for machine_number, status, origin, seed in card.take_pending_falling_drips(self):
                self.falling_drip_requested.emit(machine_number, status, origin, seed)

    def _render_issue_results(self) -> None:
        self._cancel_deep_search(quiet=True)
        self._detach_grid_widgets()

        query = self.search.text().strip()
        state_filter = self.issue_state.currentData() or "all"
        started_at = perf_now()
        self._search_results = self.repository.search_issues(
            query,
            state_filter=state_filter,
            limit=QUICK_SEARCH_LIMIT,
        )
        perf_log(
            "dashboard.quick_search",
            state=state_filter,
            count=len(self._search_results),
            limit=QUICK_SEARCH_LIMIT,
            elapsed_ms=elapsed_ms(started_at),
        )
        mode = self.search_mode.currentData() or "quick"
        if mode == "deep" and state_filter != "open":
            self._render_search_result_list(
                "Showing quick results from open issues and recent archive records. Still searching the full Excel archive...",
                running=True,
            )
            self._start_deep_search(query, state_filter)
            return

        self._render_search_result_list("Quick Search results from SQLite only.", running=False)

    def _render_search_result_list(self, status_text: str, *, running: bool) -> None:
        self._clear_layout(self.results_layout)
        self.cancel_deep.setVisible(running)

        state_filter = self.issue_state.currentData() or "all"
        summary = QLabel(_result_count_text(len(self._search_results), state_filter))
        summary.setObjectName("sectionTitle")
        self.results_layout.addWidget(summary)
        status = QLabel(status_text)
        status.setObjectName("mutedLabel")
        status.setWordWrap(True)
        self.results_layout.addWidget(status)

        if not self._search_results:
            empty = QLabel(self._empty_search_text())
            empty.setObjectName("mutedLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(160)
            self.results_layout.addWidget(empty)
            self.results_layout.addStretch(1)
            return

        for result in self._search_results:
            self.results_layout.addWidget(self._result_card(result))
        self.results_layout.addStretch(1)

    def _start_deep_search(self, query: str, state_filter: str) -> None:
        perf_log("dashboard.deep_search_start", state=state_filter, quick_count=len(self._search_results))
        task = DeepArchiveSearchTask(
            self.paths.archive_path,
            query=query,
            state_filter=state_filter,
            existing_keys={search_result_dedupe_key(result) for result in self._search_results},
            limit=DEEP_SEARCH_LIMIT,
        )
        self._deep_task = task
        task.signals.batch_found.connect(lambda batch, active_task=task: self._handle_deep_batch(active_task, batch))
        task.signals.progress_updated.connect(
            lambda message, active_task=task: self._handle_deep_progress(active_task, message)
        )
        task.signals.failed.connect(lambda message, active_task=task: self._handle_deep_failed(active_task, message))
        task.signals.cancelled.connect(lambda active_task=task: self._handle_deep_cancelled(active_task))
        task.signals.finished.connect(lambda _count, active_task=task: self._handle_deep_finished(active_task))
        QThreadPool.globalInstance().start(task)

    def _handle_deep_batch(self, task: DeepArchiveSearchTask, batch: list[IssueSearchResult]) -> None:
        if task is not self._deep_task:
            return
        self._search_results.extend(batch)
        self._render_search_result_list("Still searching the full Excel archive...", running=True)

    def _handle_deep_progress(self, task: DeepArchiveSearchTask, message: str) -> None:
        if task is not self._deep_task:
            return
        self._render_search_result_list(message, running=True)

    def _handle_deep_failed(self, task: DeepArchiveSearchTask, _message: str) -> None:
        if task is not self._deep_task:
            return
        self._deep_task = None
        self._render_search_result_list(
            "Deep Search could not read the Excel archive. Quick Search results are still shown.",
            running=False,
        )

    def _handle_deep_cancelled(self, task: DeepArchiveSearchTask) -> None:
        if task is not self._deep_task:
            return
        self._deep_task = None
        self._render_search_result_list("Deep Search cancelled. Showing results found before cancellation.", running=False)

    def _handle_deep_finished(self, task: DeepArchiveSearchTask) -> None:
        if task is not self._deep_task:
            return
        self._deep_task = None
        self._render_search_result_list(
            "Deep Search complete. Showing open issues, recent archive records, and Excel archive history.",
            running=False,
        )

    def _filtered_machines(self) -> list[MachineSummary]:
        area = self.area_filter.currentData() or ""
        cell = self.cell_filter.currentData() or ""
        machines = []
        for machine in self._machines:
            if area and machine.area != area:
                continue
            if cell and machine.cell != cell:
                continue
            machines.append(machine)

        sort_key = self.sort.currentData() or "plant"
        if sort_key == "severity":
            order = {status: index for index, status in enumerate(STATUS_ORDER)}
            return sorted(machines, key=lambda m: (order.get(m.calculated_status, 99), -m.open_issue_count, m.display_order))
        if sort_key == "open_issues":
            return sorted(machines, key=lambda m: (-m.open_issue_count, m.display_order, m.machine_number))
        if sort_key == "machine_asc":
            return sorted(machines, key=lambda m: m.machine_number.casefold())
        if sort_key == "machine_desc":
            return sorted(machines, key=lambda m: m.machine_number.casefold(), reverse=True)
        return sorted(machines, key=lambda m: (m.display_order, m.machine_number.casefold()))

    def _column_count(self) -> int:
        available = max(1, self.scroll.viewport().width())
        spacing = self.grid.horizontalSpacing()
        return max(1, (available + spacing) // (MIN_CARD_WIDTH + spacing))

    def _has_issue_query(self) -> bool:
        return bool(self.search.text().strip())

    def _queue_search_render(self) -> None:
        self._search_timer.start()

    def _cancel_deep_search(self, _checked: bool = False, *, quiet: bool = False) -> None:
        if self._deep_task is None:
            self.cancel_deep.hide()
            return
        task = self._deep_task
        self._deep_task = None
        task.cancel()
        self.cancel_deep.hide()
        if not quiet:
            self._render_search_result_list("Deep Search cancelled. Showing results found before cancellation.", running=False)

    def _empty_search_text(self) -> str:
        mode = self.search_mode.currentData() or "quick"
        if mode == "deep":
            return "No matching records were found in open issues, recent archive records, or the Excel archive."
        return "No matching open or recent archived issues found. Use Deep Search to include older Excel archive records."

    def _result_card(self, result: IssueSearchResult) -> QFrame:
        card = QFrame()
        card.setObjectName("searchResultCard")
        card.setProperty("state", result.state)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel(result.title)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        state = QLabel(result.source or ("Open Issue" if result.state == "open" else "Recent Archive"))
        state.setObjectName("smallSectionTitle")
        top.addWidget(state)
        if result.status:
            top.addWidget(StatusBadge(result.status))
        layout.addLayout(top)

        machine = QLabel(f"Machine {result.machine_number} | {result.machine_name}")
        machine.setObjectName("mutedLabel")
        machine.setWordWrap(True)
        layout.addWidget(machine)

        description = result.description
        if result.resolution:
            description = f"{result.description} | Fix: {result.resolution}"
        body = QLabel(preview_text(description, 180))
        body.setWordWrap(True)
        layout.addWidget(body)

        timestamp = result.resolved_at or result.created_at
        age_or_date = (
            f"Resolved {format_timestamp(result.resolved_at)}"
            if result.resolved_at
            else f"Open {format_duration_between(result.created_at)}"
        )
        meta_parts = [
            display_issue_id(result),
            result.category or "Uncategorized",
            result.status,
            f"Logged by {result.logged_by}",
            age_or_date,
            f"Created {format_timestamp(result.created_at)}" if timestamp != result.created_at else "",
        ]
        meta = QLabel(" | ".join(part for part in meta_parts if part))
        meta.setObjectName("mutedLabel")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        actions = QHBoxLayout()
        actions.addStretch(1)
        if result.state in {"open", "resolved"}:
            open_button = QPushButton("Open Issue")
            open_button.setObjectName("tableActionButton")
            mode = "active" if result.state == "open" else "resolved"
            open_button.clicked.connect(
                lambda _checked=False, result_mode=mode, issue_id=result.issue_id: self.issue_detail_requested.emit(
                    result_mode,
                    issue_id,
                )
            )
            actions.addWidget(open_button)
        machine_button = QPushButton("Machine")
        machine_button.setObjectName("tableActionButton")
        machine_button.clicked.connect(
            lambda _checked=False, machine_number=result.machine_number: self.machine_selected.emit(machine_number)
        )
        actions.addWidget(machine_button)
        layout.addLayout(actions)
        return card

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
            child_layout = item.layout()
            if child_layout:
                HiveDashboardPage._clear_layout(child_layout)

    def _detach_grid_widgets(self) -> None:
        self._last_card_layout = None
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)


def _result_count_text(count: int, state_filter: str) -> str:
    scope = {
        "open": "open issue",
        "resolved": "archived/resolved issue",
    }.get(state_filter, "issue")
    suffix = "" if count == 1 else "s"
    return f"{count} matching {scope}{suffix}"
