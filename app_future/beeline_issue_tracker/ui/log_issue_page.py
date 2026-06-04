from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
from beeline_issue_tracker.ui.theme import ThemeManager
from beeline_issue_tracker.ui.widgets import BrandHeader, HoneycombBackground


class LogIssuePage(HoneycombBackground):
    cancel_requested = Signal()
    save_requested = Signal(dict)

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
        self.description = QTextEdit()
        self.description.setMinimumHeight(150)
        self.description.setPlaceholderText("What is happening?")
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
        panel_layout.addLayout(form)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel")
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
        self.category.setCurrentIndex(0)
        self.custom_category.clear()
        self._update_custom_category_visibility()
        self.non_critical_button.setChecked(True)
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
