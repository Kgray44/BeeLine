from __future__ import annotations

import argparse
import logging
import os
import sys

from PySide6.QtWidgets import QApplication

from beeline_issue_tracker.config import APP_NAME, AppPaths, initialize_runtime_files, load_runtime_config
from beeline_issue_tracker.data.archive import inspect_archive, refresh_archive_workbook
from beeline_issue_tracker.data.database import initialize_database
from beeline_issue_tracker.data.repository import IssueRepository
from beeline_issue_tracker.domain import display_issue_id
from beeline_issue_tracker.perf import elapsed_ms, log as perf_log, now as perf_now


logger = logging.getLogger(__name__)
UI_VERSIONS = ("v2",)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument(
        "--ui-version",
        choices=UI_VERSIONS,
        default=os.environ.get("BEELINE_UI_VERSION", "v2"),
        help=(
            "Choose which BeeLine UI shell to launch. v2 is the current BeeLine UI."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Initialize the database and print a startup summary without opening the UI.",
    )
    parser.add_argument(
        "--archive-status",
        action="store_true",
        help="Print the Excel archive path and latest archive status without opening the UI.",
    )
    parser.add_argument(
        "--repair-archive",
        action="store_true",
        help="Rebuild the readable grouped Excel archive view, then print archive status.",
    )
    return parser


def load_ui_classes(ui_version: str):
    if ui_version == "v2":
        from beeline_issue_tracker.ui_v2.main_window import MainWindow
        from beeline_issue_tracker.ui_v2.theme import ThemeManager
        return MainWindow, ThemeManager
    raise ValueError(f"Unknown BeeLine UI version: {ui_version}")


def print_archive_status(paths: AppPaths, repository: IssueRepository) -> None:
    inspection = inspect_archive(paths.archive_path)
    latest = repository.get_latest_resolved_issue()
    counts = repository.archive_status_counts()

    print(f"Excel archive path: {paths.archive_path}")
    print(f"Archive exists: {'yes' if inspection.exists else 'no'}")
    if inspection.sheet_names:
        print(f"Archive sheets: {', '.join(inspection.sheet_names)}")
    print(f"Archive sheet: {inspection.sheet_name}")
    print(f"Archived Excel rows: {inspection.row_count}")
    print(f"Resolved_By_Date exists: {'yes' if inspection.grouped_sheet_exists else 'no'}")
    if inspection.error:
        print(f"Archive workbook error: {inspection.error}")
    if inspection.latest_cache_id is not None:
        print(
            "Latest Excel row: "
            f"cache_id={inspection.latest_cache_id}, "
            f"resolved_at={inspection.latest_resolved_at}, "
            f"title={inspection.latest_title}"
        )
    else:
        print("Latest Excel row: none")

    if counts:
        summary = ", ".join(f"{status}={count}" for status, count in counts.items())
        print(f"SQLite archive statuses: {summary}")
    else:
        print("SQLite archive statuses: none")

    if latest is None:
        print("Latest SQLite resolved issue: none")
    else:
        print(
            "Latest SQLite resolved issue: "
            f"id={display_issue_id(latest)}, machine={latest.machine_number}, "
            f"status={latest.archive_status}, title={latest.title}"
        )
        if latest.archive_error:
            print(f"Latest archive error: {latest.archive_error}")


def print_startup_archive_health(paths: AppPaths, repository: IssueRepository) -> None:
    # Startup health must stay SQLite/path-only. The Excel archive can grow very
    # large, so normal startup deliberately avoids opening or scanning it.
    latest = repository.get_latest_resolved_issue()
    counts = repository.archive_status_counts()

    print(f"Excel archive path: {paths.archive_path}")
    print("Archive workbook check: skipped during normal startup")
    if counts:
        summary = ", ".join(f"{status}={count}" for status, count in counts.items())
        print(f"SQLite archive statuses: {summary}")
    else:
        print("SQLite archive statuses: none")

    if latest is None:
        print("Latest SQLite resolved issue: none")
        return

    print(
        "Latest SQLite resolved issue: "
        f"id={display_issue_id(latest)}, machine={latest.machine_number}, "
        f"status={latest.archive_status}, title={latest.title}"
    )
    if latest.archive_error:
        print(f"Latest archive error: {latest.archive_error}")


def main(argv: list[str] | None = None) -> int:
    started_at = perf_now()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.ui_version not in UI_VERSIONS:
        parser.error(
            "argument --ui-version: invalid choice: "
            f"{args.ui_version!r} (choose from 'v2')"
        )
    paths = AppPaths.from_environment()
    initialize_runtime_files(paths)
    runtime_config = load_runtime_config(paths.runtime_config_path)
    initialize_database(paths.db_path, runtime_config.machine_rows())

    repository = IssueRepository(paths.db_path)
    if args.repair_archive:
        refresh_archive_workbook(paths.archive_path)
        print("Excel archive repaired/refreshed.")
        print_archive_status(paths, repository)
        return 0
    if args.check:
        machines = repository.list_machines_with_status()
        print(f"{APP_NAME}: database ready at {paths.db_path}")
        print(f"Machines: {len(machines)}")
        print(f"Runtime config path: {paths.runtime_config_path}")
        print(f"Templates: {paths.template_dir}")
        print_startup_archive_health(paths, repository)
        return 0
    if args.archive_status:
        print_archive_status(paths, repository)
        return 0

    logger.info("%s database path: %s", APP_NAME, paths.db_path)
    logger.info("%s Excel archive path: %s", APP_NAME, paths.archive_path)
    logger.info("%s runtime config path: %s", APP_NAME, paths.runtime_config_path)

    app = QApplication(sys.argv if argv is None else [sys.argv[0], *argv])
    app.setOrganizationName("BeeLine")
    app.setApplicationName(APP_NAME)
    MainWindow, ThemeManager = load_ui_classes(args.ui_version)
    theme_manager = ThemeManager()
    app.setStyleSheet(theme_manager.build_stylesheet())
    theme_manager.theme_changed.connect(lambda _theme: app.setStyleSheet(theme_manager.build_stylesheet()))

    window = MainWindow(repository, paths, theme_manager, runtime_config)
    window.show()
    perf_log("app.startup_ready", elapsed_ms=elapsed_ms(started_at))
    return app.exec()
