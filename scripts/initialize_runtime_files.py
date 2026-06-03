from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from beeline_issue_tracker.config import AppPaths, initialize_runtime_files
from beeline_issue_tracker.data.archive import create_empty_archive_workbook
from beeline_issue_tracker.data.database import initialize_database


CONFIG_TEMPLATE = {
    "version": 1,
    "notes": [
        "This is a safe placeholder template.",
        "Create local plant machine configuration in config/beeline_config.json.",
        "Never commit real machine data, employee names, badge IDs, issue history, or secrets.",
    ],
    "roles": {
        "operator": {
            "enabled": False,
            "pin_hash": "",
        },
        "technician": {
            "enabled": False,
            "pin_hash": "",
        },
        "admin": {
            "enabled": False,
            "pin_hash": "",
        },
    },
    "analytics": {
        "enabled": True,
        "risk_window_days": 30,
        "recurrence_window_days": 60,
        "high_risk_threshold": 65,
        "critical_risk_threshold": 85,
        "grouped_chart_periods": 8,
        "persist_predictive_alerts": True,
        "enable_fix_suggestions": True,
        "enable_related_issues": True,
    },
    "machines": [],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create safe BeeLine templates and runtime files.")
    parser.add_argument(
        "--create-templates",
        action="store_true",
        help="Create missing safe template files before initializing runtime files.",
    )
    parser.add_argument(
        "--force-templates",
        action="store_true",
        help="Overwrite template files with empty safe templates.",
    )
    return parser


def create_templates(paths: AppPaths, *, force: bool = False) -> None:
    paths.ensure_directories()
    _write_config_template(paths.config_template_path, force=force)
    _write_sqlite_template(paths.db_template_path, force=force)
    _write_archive_template(paths.archive_template_path, force=force)


def _write_config_template(path: Path, *, force: bool) -> None:
    if path.exists() and not force:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(CONFIG_TEMPLATE, indent=2) + "\n", encoding="utf-8")


def _write_sqlite_template(path: Path, *, force: bool) -> None:
    if path.exists() and not force:
        return
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    initialize_database(path)


def _write_archive_template(path: Path, *, force: bool) -> None:
    if path.exists() and not force:
        return
    if path.exists():
        path.unlink()
    create_empty_archive_workbook(path)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = AppPaths.from_environment()
    if args.create_templates or args.force_templates:
        create_templates(paths, force=args.force_templates)
    initialize_runtime_files(paths)
    print(f"Runtime config: {paths.runtime_config_path}")
    print(f"Runtime SQLite: {paths.db_path}")
    print(f"Runtime archive: {paths.archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
