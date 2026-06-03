from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from beeline_issue_tracker.data.archive import ExcelArchive
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.domain import ResolvedIssue


logger = logging.getLogger(__name__)


class ArchiveSignals(QObject):
    finished = Signal(int, bool, str)


class ArchiveIssueTask(QRunnable):
    def __init__(self, archive_path: Path, repository: IssueRepository, issue: ResolvedIssue):
        super().__init__()
        self.archive_path = archive_path
        self.repository = repository
        self.issue = issue
        self.signals = ArchiveSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = ExcelArchive(self.archive_path).append_resolved_issue(self.issue)
        except Exception as exc:
            message = str(exc)
            logger.exception("Excel archive failed for resolved issue %s at %s", self.issue.id, self.archive_path)
            self.repository.mark_archive_result(self.issue.id, success=False, error=message)
            self.signals.finished.emit(self.issue.id, False, message)
            return

        self.repository.mark_archive_result(self.issue.id, success=True)
        logger.info(
            "Resolved issue %s archived to %s [%s row %s]",
            self.issue.id,
            result.archive_path,
            result.sheet_name,
            result.row_number,
        )
        self.signals.finished.emit(
            self.issue.id,
            True,
            f"Archived to {result.archive_path} ({result.sheet_name} row {result.row_number})",
        )
