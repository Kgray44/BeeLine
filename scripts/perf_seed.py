from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from beeline_issue_tracker.config import AppPaths
from beeline_issue_tracker.data.database import connect, initialize_database


FAKE_USERS = ("Perf Seeder", "Test Operator", "Demo Technician")
FAKE_CATEGORIES = ("Sensor", "Robot", "Pneumatic", "Electrical", "Cooling", "Hydraulic", "Mold")
FAKE_TITLES = (
    "Sensor drift",
    "Robot ready fault",
    "Pneumatic pressure low",
    "Cooling flow alarm",
    "Hydraulic pressure warning",
    "Mold clamp alarm",
    "Vacuum cup fault",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a fake BeeLine performance test database.")
    default_db = AppPaths.from_environment().data_dir / "beeline_perf.sqlite"
    parser.add_argument("--db-path", type=Path, default=default_db, help=f"Output SQLite path. Default: {default_db}")
    parser.add_argument("--machines", type=int, default=100)
    parser.add_argument("--active", type=int, default=5000)
    parser.add_argument("--resolved", type=int, default=50000)
    parser.add_argument("--force", action="store_true", help="Overwrite an existing perf/demo database.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = args.db_path.expanduser().resolve()
    _prepare_target(db_path, force=args.force)

    machines = tuple(_machine_row(index) for index in range(1, max(1, args.machines) + 1))
    initialize_database(db_path, machines)
    _insert_fake_issues(db_path, machines, max(0, args.active), max(0, args.resolved))

    print(f"Created fake BeeLine performance database: {db_path}")
    print(f"Machines: {len(machines)}")
    print(f"Active issues: {max(0, args.active)}")
    print(f"Resolved issues: {max(0, args.resolved)}")
    print("No real plant data, operator names, issue descriptions, or archive workbooks were used.")
    return 0


def _prepare_target(db_path: Path, *, force: bool) -> None:
    if not db_path.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return
    safe_name = db_path.name.casefold()
    if not force:
        raise SystemExit(f"{db_path} already exists. Re-run with --force to replace this perf database.")
    if "perf" not in safe_name and "demo" not in safe_name:
        raise SystemExit("Refusing to overwrite a database whose filename does not contain 'perf' or 'demo'.")
    db_path.unlink()


def _machine_row(index: int) -> tuple[str, str, str, str, str, int, str, str, str, str, str, str]:
    machine_number = f"DEMO-{index:03d}"
    return (
        machine_number,
        f"Demo Machine {index:03d}",
        f"Demo Area {((index - 1) % 5) + 1}",
        f"Cell {((index - 1) % 10) + 1}",
        f"DEMO-ASSET-{index:03d}",
        index * 10,
        "Demo Manufacturer",
        f"Demo Model {((index - 1) % 8) + 1}",
        f"IMM-DEMO-{index:05d}",
        "Demo Robot",
        f"Demo Robot Model {((index - 1) % 6) + 1}",
        f"ROBOT-DEMO-{index:05d}",
    )


def _insert_fake_issues(
    db_path: Path,
    machines: tuple[tuple[str, str, str, str, str, int, str, str, str, str, str, str], ...],
    active_count: int,
    resolved_count: int,
) -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    machine_numbers = [machine[0] for machine in machines]
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO active_issues
                (issue_id, machine_number, logged_by, title, description, severity, category, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _active_issue_row(index, machine_numbers, base)
                for index in range(1, active_count + 1)
            ),
        )
        conn.executemany(
            """
            INSERT INTO resolved_issues_cache
                (
                    issue_id,
                    original_issue_id,
                    machine_number,
                    logged_by,
                    title,
                    description,
                    severity,
                    category,
                    created_at,
                    resolved_at,
                    resolved_by,
                    solution,
                    archive_status,
                    archive_error
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'archived', '')
            """,
            (
                _resolved_issue_row(index, machine_numbers, base)
                for index in range(1, resolved_count + 1)
            ),
        )


def _active_issue_row(index: int, machine_numbers: list[str], base: datetime) -> tuple[str, str, str, str, str, str, str, str, str]:
    machine = machine_numbers[(index - 1) % len(machine_numbers)]
    created = base + timedelta(minutes=index)
    title = FAKE_TITLES[index % len(FAKE_TITLES)]
    category = FAKE_CATEGORIES[index % len(FAKE_CATEGORIES)]
    severity = "Line Down" if index % 17 == 0 else "Non-Critical"
    return (
        f"PERF-A-{index:06d}",
        machine,
        FAKE_USERS[index % len(FAKE_USERS)],
        title,
        f"Fake performance issue {index}: {title.lower()} on {machine}.",
        severity,
        category,
        created.isoformat(),
        created.isoformat(),
    )


def _resolved_issue_row(index: int, machine_numbers: list[str], base: datetime) -> tuple[str, int, str, str, str, str, str, str, str, str, str, str]:
    machine = machine_numbers[(index - 1) % len(machine_numbers)]
    created = base - timedelta(days=index % 365, minutes=index)
    resolved = created + timedelta(minutes=15 + (index % 240))
    title = FAKE_TITLES[index % len(FAKE_TITLES)]
    category = FAKE_CATEGORIES[index % len(FAKE_CATEGORIES)]
    severity = "Line Down" if index % 23 == 0 else "Non-Critical"
    return (
        f"PERF-R-{index:06d}",
        100000 + index,
        machine,
        FAKE_USERS[index % len(FAKE_USERS)],
        title,
        f"Fake resolved performance issue {index}: {title.lower()} on {machine}.",
        severity,
        category,
        created.isoformat(),
        resolved.isoformat(),
        FAKE_USERS[(index + 1) % len(FAKE_USERS)],
        f"Demo corrective action {index % 19}: verified {category.lower()} system and returned machine to service.",
    )


if __name__ == "__main__":
    raise SystemExit(main())
