from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)

from beeline_issue_tracker.config import RuntimeConfig


ROLE_OPTIONS = (
    ("Viewer", "viewer"),
    ("Technician", "technician"),
    ("Admin", "admin"),
)


class LoginDialog(QDialog):
    def __init__(self, runtime_config: RuntimeConfig, parent=None):
        super().__init__(parent)
        self.runtime_config = runtime_config
        self.setWindowTitle("Login")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        prompt = QLabel("Select access level")
        prompt.setObjectName("sectionTitle")
        layout.addWidget(prompt)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.role = QComboBox()
        for label, value in ROLE_OPTIONS:
            self.role.addItem(label, value)
        self.role.currentIndexChanged.connect(self._refresh_pin_state)
        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin.setPlaceholderText("PIN")
        self.help_text = QLabel()
        self.help_text.setObjectName("mutedLabel")
        self.help_text.setWordWrap(True)
        form.addRow("Role", self.role)
        form.addRow("PIN", self.pin)
        layout.addLayout(form)
        layout.addWidget(self.help_text)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_pin_state()

    def selected_role(self) -> str:
        return self.role.currentData() or "viewer"

    def _refresh_pin_state(self) -> None:
        role = self.selected_role()
        requires_pin = self.runtime_config.role_requires_pin(role)
        self.pin.setVisible(role != "viewer")
        self.pin.setEnabled(role != "viewer")
        if role == "viewer":
            self.help_text.setText("Viewer can inspect dashboards, issues, and history.")
        elif requires_pin:
            self.help_text.setText("Enter the configured hashed local PIN for this role.")
        elif role == "admin":
            self.help_text.setText("Admin login requires a configured hashed admin PIN in local config.")
        else:
            self.help_text.setText("No technician PIN is configured; local technician mode is available.")

    def accept(self) -> None:
        role = self.selected_role()
        pin = self.pin.text().strip()
        if role == "viewer":
            super().accept()
            return
        if self.runtime_config.role_requires_pin(role):
            if not pin:
                QMessageBox.warning(self, "Missing PIN", "Please enter the configured PIN.")
                return
            if self.runtime_config.verify_pin_for_roles(pin, (role,)):
                super().accept()
                return
            QMessageBox.warning(self, "PIN rejected", "That PIN is not authorized for this role.")
            return
        if role == "admin":
            QMessageBox.warning(
                self,
                "Admin PIN not configured",
                "Add an enabled admin role with a hashed PIN to local config before using Admin settings.",
            )
            return
        super().accept()


class PinDialog(QDialog):
    def __init__(self, action_label: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PIN Required")
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        prompt = QLabel(action_label)
        prompt.setObjectName("sectionTitle")
        layout.addWidget(prompt)

        self.pin = QLineEdit()
        self.pin.setEchoMode(QLineEdit.EchoMode.Password)
        self.pin.setPlaceholderText("Technician/Admin PIN")
        self.pin.setMinimumHeight(42)
        layout.addWidget(self.pin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self) -> str:
        return self.pin.text().strip()

    def accept(self) -> None:
        if not self.value():
            QMessageBox.warning(self, "Missing PIN", "Please enter a PIN.")
            return
        super().accept()


class ResolveIssueDialog(QDialog):
    def __init__(self, issue_title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Resolve Issue")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.issue_title = QLineEdit(issue_title)
        self.issue_title.setReadOnly(True)
        self.resolved_by = QLineEdit()
        self.resolved_by.setPlaceholderText("Optional")
        self.solution = QTextEdit()
        self.solution.setMinimumHeight(130)
        self.solution.setPlaceholderText("What fixed the issue?")

        form.addRow("Issue", self.issue_title)
        form.addRow("Resolved by", self.resolved_by)
        form.addRow("Solution/fix", self.solution)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, str]:
        return {
            "resolved_by": self.resolved_by.text().strip(),
            "solution": self.solution.toPlainText().strip(),
        }

    def accept(self) -> None:
        if not self.values()["solution"]:
            QMessageBox.warning(self, "Missing solution", "Please enter the solution/fix before resolving.")
            return
        super().accept()
