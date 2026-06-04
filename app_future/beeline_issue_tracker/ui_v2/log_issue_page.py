from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.domain import LINE_DOWN, NON_CRITICAL
from beeline_issue_tracker.future_features import IntakeSuggestion
from beeline_issue_tracker.ui_v2.issue_list_model import format_timestamp, preview_text
from beeline_issue_tracker.ui_v2.theme import ThemeManager
from beeline_issue_tracker.ui_v2.widgets import BrandHeader, HoneycombBackground


class LogIssuePage(HoneycombBackground):
    cancel_requested = Signal()
    save_requested = Signal(dict)
    suggestions_requested = Signal(str, str)
    suggestion_open_requested = Signal(int)

    def __init__(
        self,
        repository: IssueRepository,
        theme_manager: ThemeManager,
        paths: AppPaths,
        category_options: tuple[str, ...] = ("Automation", "Machine", "Maintenance"),
        parent=None,
    ):
        super().__init__(theme_manager, parent)
        self.repository = repository
        self.theme_manager = theme_manager
        self.paths = paths
        self.category_options = tuple(category_options) or ("Automation", "Machine", "Maintenance")
        self.machine_number_value = ""
        self._suggestion_query = ""
        self._suggestion_timer = QTimer(self)
        self._suggestion_timer.setSingleShot(True)
        self._suggestion_timer.setInterval(400)
        self._suggestion_timer.timeout.connect(self._request_suggestions)

        page = QVBoxLayout(self)
        page.setContentsMargins(24, 22, 24, 22)
        page.setSpacing(18)

        header = QHBoxLayout()
        self.brand_header = BrandHeader("Report Problem", "", paths.logo_path(), theme_manager)
        header.addWidget(self.brand_header, 1)
        page.addLayout(header)

        panel = QFrame()
        panel.setObjectName("formPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(22, 20, 22, 20)
        panel_layout.setSpacing(18)

        status_label = QLabel("Status")
        status_label.setObjectName("sectionTitle")
        panel_layout.addWidget(status_label)

        status_row = QHBoxLayout()
        status_row.setSpacing(14)
        self.non_critical_button = QPushButton(NON_CRITICAL)
        self.non_critical_button.setObjectName("statusNonCriticalButton")
        self.non_critical_button.setCheckable(True)
        self.line_down_button = QPushButton(LINE_DOWN)
        self.line_down_button.setObjectName("statusLineDownButton")
        self.line_down_button.setCheckable(True)
        self.status_group = QButtonGroup(self)
        self.status_group.setExclusive(True)
        self.status_group.addButton(self.non_critical_button)
        self.status_group.addButton(self.line_down_button)
        status_row.addWidget(self.non_critical_button)
        status_row.addWidget(self.line_down_button)
        panel_layout.addLayout(status_row)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(14)

        self.machine_number = QLineEdit()
        self.machine_number.setReadOnly(True)
        self.machine_number.setMinimumHeight(44)
        self.logged_by = QLineEdit()
        self.logged_by.setMinimumHeight(44)
        self.logged_by.setPlaceholderText("Name or operator ID")
        self.issue_title = QLineEdit()
        self.issue_title.setMinimumHeight(44)
        self.issue_title.setPlaceholderText("Short issue title")
        self.issue_title.textChanged.connect(self._queue_suggestions)
        self.description = QTextEdit()
        self.description.setMinimumHeight(150)
        self.description.setPlaceholderText("What is happening?")
        self.description.textChanged.connect(self._queue_suggestions)
        self.category = QComboBox()
        self.category.setMinimumHeight(44)
        for category in self.category_options:
            self.category.addItem(category, category)
        self.category.addItem("Other", "__other__")
        self.category.currentIndexChanged.connect(self._update_custom_category_visibility)
        self.custom_category = QLineEdit()
        self.custom_category.setMinimumHeight(44)
        self.custom_category.setPlaceholderText("Custom category")
        category_holder = QWidget()
        category_layout = QVBoxLayout(category_holder)
        category_layout.setContentsMargins(0, 0, 0, 0)
        category_layout.setSpacing(8)
        category_layout.addWidget(self.category)
        category_layout.addWidget(self.custom_category)

        form.addRow("Machine", self.machine_number)
        form.addRow("Logged by", self.logged_by)
        form.addRow("Issue title", self.issue_title)
        form.addRow("Problem description", self.description)
        form.addRow("Category", category_holder)
        self.what_changed = QTextEdit()
        self.what_changed.setMinimumHeight(70)
        self.what_changed.setPlaceholderText("What changed? (optional)")
        self.tried_already = QTextEdit()
        self.tried_already.setMinimumHeight(70)
        self.tried_already.setPlaceholderText("Tried already? (optional)")
        form.addRow("What changed?", self.what_changed)
        form.addRow("Tried already?", self.tried_already)
        panel_layout.addLayout(form)

        self.suggestions_panel = QFrame()
        self.suggestions_panel.setObjectName("infoPanel")
        suggestions_layout = QVBoxLayout(self.suggestions_panel)
        suggestions_layout.setContentsMargins(14, 12, 14, 12)
        suggestions_layout.setSpacing(8)
        suggestions_title = QLabel("Similar Resolved Issues")
        suggestions_title.setObjectName("smallSectionTitle")
        suggestions_layout.addWidget(suggestions_title)
        self.suggestions_status = QLabel("")
        self.suggestions_status.setObjectName("mutedLabel")
        self.suggestions_status.setWordWrap(True)
        suggestions_layout.addWidget(self.suggestions_status)
        self.suggestions_list = QVBoxLayout()
        self.suggestions_list.setContentsMargins(0, 0, 0, 0)
        self.suggestions_list.setSpacing(6)
        suggestions_layout.addLayout(self.suggestions_list)
        self.suggestions_panel.hide()
        panel_layout.addWidget(self.suggestions_panel)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("quietButton")
        cancel.clicked.connect(self.cancel_requested.emit)
        save = QPushButton("Save Issue")
        save.setObjectName("primaryButton")
        save.clicked.connect(self._save)
        actions.addWidget(cancel)
        actions.addWidget(save)
        panel_layout.addLayout(actions)

        page.addWidget(panel)
        page.addStretch(1)

    def load_machine(self, machine_number: str) -> None:
        self.machine_number_value = machine_number
        machine = self.repository.get_machine(machine_number)
        self.machine_number.setText(machine_number)
        if machine is None:
            self.brand_header.set_subtitle(f"Machine {machine_number}")
        else:
            self.brand_header.set_subtitle(
                f"Machine {machine.machine_number} | {machine.name} | {machine.area} | {machine.cell}"
            )
        self.logged_by.clear()
        self.issue_title.clear()
        self.description.clear()
        self.what_changed.clear()
        self.tried_already.clear()
        self.category.setCurrentIndex(0)
        self.custom_category.clear()
        self._update_custom_category_visibility()
        self.non_critical_button.setChecked(True)
        self._clear_suggestions()
        self.logged_by.setFocus()

    def values(self) -> dict[str, str]:
        severity = LINE_DOWN if self.line_down_button.isChecked() else NON_CRITICAL
        category_value = self.category.currentData() or ""
        if category_value == "__other__":
            category_value = self.custom_category.text().strip()
        return {
            "machine_number": self.machine_number.text().strip(),
            "logged_by": self.logged_by.text().strip(),
            "title": self.issue_title.text().strip(),
            "description": self.description.toPlainText().strip(),
            "severity": severity,
            "category": str(category_value).strip(),
            "what_changed": self.what_changed.toPlainText().strip(),
            "tried_already": self.tried_already.toPlainText().strip(),
        }

    def _save(self) -> None:
        values = self.values()
        missing = []
        if not values["logged_by"]:
            missing.append("logged by")
        if not values["title"]:
            missing.append("issue title")
        if not values["description"]:
            missing.append("problem description")
        if missing:
            QMessageBox.warning(self, "Missing information", "Please enter: " + ", ".join(missing))
            return
        self.save_requested.emit(values)

    def _update_custom_category_visibility(self) -> None:
        self.custom_category.setVisible(self.category.currentData() == "__other__")

    def _queue_suggestions(self) -> None:
        self._suggestion_timer.start()

    def _request_suggestions(self) -> None:
        query = " ".join((self.issue_title.text() + " " + self.description.toPlainText()).split())
        self._suggestion_query = query
        if len(query) < 3 or not self.machine_number_value:
            self._clear_suggestions()
            return
        self.suggestions_panel.show()
        self.suggestions_status.setText("Searching local resolved history...")
        _clear_layout(self.suggestions_list)
        self.suggestions_requested.emit(self.machine_number_value, query)

    def apply_suggestions(self, query: str, suggestions: list[IntakeSuggestion]) -> None:
        if query != self._suggestion_query:
            return
        self.suggestions_panel.setVisible(bool(query))
        _clear_layout(self.suggestions_list)
        if not suggestions:
            self.suggestions_status.setText("No close local matches yet.")
            return
        self.suggestions_status.setText(f"{len(suggestions)} local match{'es' if len(suggestions) != 1 else ''}")
        for suggestion in suggestions[:5]:
            self.suggestions_list.addWidget(self._suggestion_row(suggestion))

    def _suggestion_row(self, suggestion: IntakeSuggestion) -> QWidget:
        row = QFrame()
        row.setObjectName("factCard")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        text = QLabel(
            f"{preview_text(suggestion.title, 90)}\n"
            f"{suggestion.category} | {suggestion.confidence} | {format_timestamp(suggestion.resolved_at)}\n"
            f"Fix: {suggestion.solution_preview}"
        )
        text.setWordWrap(True)
        layout.addWidget(text, 1)
        open_button = QPushButton("Open")
        open_button.setObjectName("tableActionButton")
        open_button.clicked.connect(lambda _checked=False, value=suggestion.issue_id: self.suggestion_open_requested.emit(value))
        layout.addWidget(open_button)
        return row

    def _clear_suggestions(self) -> None:
        self._suggestion_query = ""
        self.suggestions_panel.hide()
        self.suggestions_status.clear()
        _clear_layout(self.suggestions_list)


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.deleteLater()
        child_layout = item.layout()
        if child_layout:
            _clear_layout(child_layout)
