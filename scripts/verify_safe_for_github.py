from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from pathlib import Path
import sys

from openpyxl import load_workbook

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from beeline_issue_tracker.data.archive import ARCHIVE_SHEET, GROUPED_SHEET, HEADERS


RUNTIME_DIRS = {"data", "archive", "backups", "logs", "config"}
SAFE_RUNTIME_PLACEHOLDERS = {
    "data/.gitkeep",
    "data/README.md",
    "archive/.gitkeep",
    "archive/README.md",
    "backups/.gitkeep",
    "backups/README.md",
    "logs/.gitkeep",
    "logs/README.md",
    "config/.gitkeep",
    "config/README.md",
}
ALLOWED_TEMPLATES = {
    "templates/beeline_config.template.json",
    "templates/beeline.template.sqlite",
    "templates/beeline_archive.template.xlsx",
}
SECRET_NAME_RE = re.compile(
    r"(^|[/\\])(\.env|.*secret.*|.*token.*|.*password.*|.*credential.*|.*apikey.*|.*api_key.*)$",
    re.IGNORECASE,
)
SENSITIVE_NAME_RE = re.compile(
    r"(badge|employee|operator|user|personnel|payroll|plant[_-]?data|machine[_-]?export)",
    re.IGNORECASE,
)


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []

    existing_files = _existing_files()
    staged_or_tracked = _git_files("--cached") | _git_files()

    _check_existing_sensitive_files(existing_files, failures)
    _check_git_sensitive_files(staged_or_tracked, failures)
    _check_templates(failures)

    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"  - {warning}")

    if failures:
        print("BeeLine GitHub safety check FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("BeeLine GitHub safety check passed.")
    print("Runtime data, templates, config, archive, logs, and obvious secrets look safe for commit.")
    return 0


def _existing_files() -> set[str]:
    files: set[str] = set()
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = _rel(path)
        if rel.startswith(".git/") or "/__pycache__/" in f"/{rel}" or rel.endswith(".pyc"):
            continue
        files.add(rel)
    return files


def _git_files(*args: str) -> set[str]:
    command = ["git", "ls-files", *args]
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return set()
    if result.returncode != 0:
        return set()
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def _check_existing_sensitive_files(files: set[str], failures: list[str]) -> None:
    for rel in sorted(files):
        if rel in ALLOWED_TEMPLATES or rel in SAFE_RUNTIME_PLACEHOLDERS:
            continue
        suffix = Path(rel).suffix.lower()
        if suffix in {".sqlite", ".sqlite3", ".db", ".xlsx", ".xlsm", ".xls"}:
            if _is_allowed_runtime_path(rel):
                continue
            failures.append(f"Sensitive data-like file exists outside ignored runtime/template folders: {rel}")
        if suffix in {".log", ".zip", ".bak"} and not _is_allowed_runtime_path(rel):
            failures.append(f"Log or backup file exists outside ignored runtime folders: {rel}")
        if SECRET_NAME_RE.search(rel) and rel not in ALLOWED_TEMPLATES:
            failures.append(f"Secret-like file is present: {rel}")


def _check_git_sensitive_files(files: set[str], failures: list[str]) -> None:
    for rel in sorted(files):
        if rel in ALLOWED_TEMPLATES or rel in SAFE_RUNTIME_PLACEHOLDERS:
            continue
        parts = rel.split("/")
        suffix = Path(rel).suffix.lower()
        if parts[0] in RUNTIME_DIRS:
            failures.append(f"Runtime file is tracked or staged and must not be committed: {rel}")
        if suffix in {".sqlite", ".sqlite3", ".db", ".xlsx", ".xlsm", ".xls", ".log", ".zip", ".bak"}:
            failures.append(f"Sensitive file type is tracked or staged: {rel}")
        if SECRET_NAME_RE.search(rel):
            failures.append(f"Secret-like file is tracked or staged: {rel}")
        if SENSITIVE_NAME_RE.search(rel) and not rel.startswith("app/") and not rel.startswith("tests/"):
            failures.append(f"Sensitive-name file is tracked or staged: {rel}")


def _check_templates(failures: list[str]) -> None:
    config_template = PROJECT_ROOT / "templates" / "beeline_config.template.json"
    sqlite_template = PROJECT_ROOT / "templates" / "beeline.template.sqlite"
    archive_template = PROJECT_ROOT / "templates" / "beeline_archive.template.xlsx"

    for path in (config_template, sqlite_template, archive_template):
        if not path.exists():
            failures.append(f"Missing required safe template: {_rel(path)}")

    if config_template.exists():
        try:
            config = json.loads(config_template.read_text(encoding="utf-8"))
            machines = config.get("machines", [])
            if machines:
                failures.append("Config template should not contain real machine rows; keep machines empty or fake.")
        except Exception as exc:
            failures.append(f"Config template is not valid JSON: {exc}")

    if sqlite_template.exists():
        try:
            with sqlite3.connect(sqlite_template) as conn:
                table_counts = {
                    "machines": conn.execute("SELECT COUNT(*) FROM machines").fetchone()[0],
                    "active_issues": conn.execute("SELECT COUNT(*) FROM active_issues").fetchone()[0],
                    "resolved_issues_cache": conn.execute("SELECT COUNT(*) FROM resolved_issues_cache").fetchone()[0],
                }
            for table, count in table_counts.items():
                if count:
                    failures.append(f"SQLite template table {table} contains {count} records; expected zero.")
        except Exception as exc:
            failures.append(f"Could not validate SQLite template: {exc}")

    if archive_template.exists():
        try:
            workbook = load_workbook(archive_template, read_only=True, data_only=True)
            if ARCHIVE_SHEET not in workbook.sheetnames:
                failures.append(f"Excel template is missing {ARCHIVE_SHEET!r}.")
            if GROUPED_SHEET not in workbook.sheetnames:
                failures.append(f"Excel template is missing {GROUPED_SHEET!r}.")

            if ARCHIVE_SHEET in workbook.sheetnames:
                worksheet = workbook[ARCHIVE_SHEET]
                header = tuple(cell.value for cell in next(worksheet.iter_rows(min_row=1, max_row=1)))
                if header[: len(HEADERS)] != HEADERS:
                    failures.append("Excel template archive headers do not match BeeLine archive schema.")
                data_rows = [
                    row for row in worksheet.iter_rows(min_row=2, values_only=True)
                    if any(value is not None for value in row)
                ]
                if data_rows:
                    failures.append(f"Excel template contains {len(data_rows)} archive records; expected zero.")
        except Exception as exc:
            failures.append(f"Could not validate Excel archive template: {exc}")


def _is_allowed_runtime_path(rel: str) -> bool:
    first = rel.split("/", 1)[0]
    return first in RUNTIME_DIRS


def _rel(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
