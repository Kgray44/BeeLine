from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)


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
