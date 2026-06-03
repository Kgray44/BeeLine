from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)

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
