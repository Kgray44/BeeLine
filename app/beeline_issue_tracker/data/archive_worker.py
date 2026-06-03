from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from beeline_issue_tracker.data.archive import ExcelArchive
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.domain import ResolvedIssue, display_issue_id


logger = logging.getLogger(__name__)


class ArchiveSignals(QObject):
    finished = Signal(int, bool, str)


class ArchiveRetrySignals(QObject):
    finished = Signal(int, int, str)


class ArchiveIssueTask(QRunnable):
    def __init__(
        self,
        archive_path: Path,
        repository: IssueRepository,
        issue: ResolvedIssue,
        *,
        cache_keep_days: int = 180,
        cache_keep_minimum: int = 1000,
        cache_keep_per_machine_minimum: int = 25,
    ):
        super().__init__()
        self.archive_path = archive_path
        self.repository = repository
        self.issue = issue
        self.cache_keep_days = cache_keep_days
        self.cache_keep_minimum = cache_keep_minimum
        self.cache_keep_per_machine_minimum = cache_keep_per_machine_minimum
        self.signals = ArchiveSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = ExcelArchive(self.archive_path).append_resolved_issue(self.issue)
        except Exception as exc:
            message = str(exc)
            logger.exception("Excel archive failed for resolved issue %s at %s", display_issue_id(self.issue), self.archive_path)
            self.repository.mark_archive_result(self.issue.id, success=False, error=message)
            self.signals.finished.emit(self.issue.id, False, message)
            return

        self.repository.mark_archive_result(self.issue.id, success=True)
        trimmed = self.repository.trim_resolved_issue_cache(
            keep_days=self.cache_keep_days,
            keep_minimum=self.cache_keep_minimum,
            keep_per_machine_minimum=self.cache_keep_per_machine_minimum,
        )
        logger.info(
            "Resolved issue %s archived to %s [%s row %s]",
            display_issue_id(self.issue),
            result.archive_path,
            result.sheet_name,
            result.row_number,
        )
        message = f"Excel archive updated ({result.sheet_name} row {result.row_number})"
        if result.grouped_refresh_deferred:
            message += "; grouped view refresh deferred until --repair-archive"
        if trimmed:
            message += f"; trimmed {trimmed} archived cache record(s)"
        self.signals.finished.emit(self.issue.id, True, message)


class ArchiveRetryTask(QRunnable):
    def __init__(
        self,
        archive_path: Path,
        repository: IssueRepository,
        *,
        limit: int = 100,
        cache_keep_days: int = 180,
        cache_keep_minimum: int = 1000,
        cache_keep_per_machine_minimum: int = 25,
    ):
        super().__init__()
        self.archive_path = archive_path
        self.repository = repository
        self.limit = limit
        self.cache_keep_days = cache_keep_days
        self.cache_keep_minimum = cache_keep_minimum
        self.cache_keep_per_machine_minimum = cache_keep_per_machine_minimum
        self.signals = ArchiveRetrySignals()

    @Slot()
    def run(self) -> None:
        failed = self.repository.list_failed_archive_writes(limit=self.limit)
        if not failed:
            self.signals.finished.emit(0, 0, "No failed archive writes to retry.")
            return

        self.repository.mark_archive_retry_pending([issue.id for issue in failed])
        success_count = 0
        failed_count = 0
        for issue in failed:
            try:
                ExcelArchive(self.archive_path).append_resolved_issue(issue)
            except Exception as exc:
                failed_count += 1
                message = str(exc)
                logger.exception("Archive retry failed for resolved issue %s", display_issue_id(issue))
                self.repository.mark_archive_result(issue.id, success=False, error=message)
                continue
            success_count += 1
            self.repository.mark_archive_result(issue.id, success=True)

        if success_count:
            self.repository.trim_resolved_issue_cache(
                keep_days=self.cache_keep_days,
                keep_minimum=self.cache_keep_minimum,
                keep_per_machine_minimum=self.cache_keep_per_machine_minimum,
            )

        self.signals.finished.emit(
            success_count,
            failed_count,
            f"Archive retry complete. {success_count} archived successfully; {failed_count} still failed.",
        )
