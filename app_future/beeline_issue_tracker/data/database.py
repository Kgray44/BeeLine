from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from beeline_issue_tracker.domain import generate_issue_id, issue_id_date_key
from beeline_issue_tracker.perf import elapsed_ms, log as perf_log, now as perf_now


ISSUE_ID_MIGRATION_TABLES = ("issues", "active_issues", "resolved_issues_cache")
ISSUE_ID_SCHEMA_TABLES = ("active_issues", "resolved_issues_cache")


SCHEMA = """
CREATE TABLE IF NOT EXISTS machines (
    machine_number TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    area TEXT NOT NULL,
    cell TEXT NOT NULL DEFAULT '',
    asset_tag TEXT NOT NULL DEFAULT '',
    display_order INTEGER NOT NULL DEFAULT 0,
    manufacturer TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    imm_serial TEXT NOT NULL DEFAULT '',
    robot_type TEXT NOT NULL DEFAULT '',
    robot_model TEXT NOT NULL DEFAULT '',
    robot_serial TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS active_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id TEXT NOT NULL DEFAULT '',
    machine_number TEXT NOT NULL,
    logged_by TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('Line Down', 'Non-Critical')),
    category TEXT NOT NULL DEFAULT '',
    what_changed TEXT NOT NULL DEFAULT '',
    tried_already TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (machine_number) REFERENCES machines(machine_number)
);

CREATE INDEX IF NOT EXISTS idx_active_issues_machine
    ON active_issues(machine_number, severity, created_at);

CREATE INDEX IF NOT EXISTS idx_active_issues_machine_created
    ON active_issues(machine_number, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_active_issues_machine_severity_created
    ON active_issues(machine_number, severity, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_active_issues_public_issue_id
    ON active_issues(issue_id)
    WHERE issue_id <> '';

CREATE TABLE IF NOT EXISTS resolved_issues_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id TEXT NOT NULL DEFAULT '',
    original_issue_id INTEGER NOT NULL,
    machine_number TEXT NOT NULL,
    logged_by TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    what_changed TEXT NOT NULL DEFAULT '',
    tried_already TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    resolved_at TEXT NOT NULL,
    resolved_by TEXT NOT NULL DEFAULT '',
    solution TEXT NOT NULL,
    archive_status TEXT NOT NULL DEFAULT 'pending',
    archive_error TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_resolved_machine_recent
    ON resolved_issues_cache(machine_number, resolved_at DESC);

CREATE INDEX IF NOT EXISTS idx_resolved_issues_machine_resolved
    ON resolved_issues_cache(machine_number, resolved_at DESC);

CREATE INDEX IF NOT EXISTS idx_resolved_issues_machine_title
    ON resolved_issues_cache(machine_number, title COLLATE NOCASE);

CREATE INDEX IF NOT EXISTS idx_resolved_issues_machine_category
    ON resolved_issues_cache(machine_number, category COLLATE NOCASE);

CREATE INDEX IF NOT EXISTS idx_resolved_issues_archive_status
    ON resolved_issues_cache(archive_status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_resolved_public_issue_id
    ON resolved_issues_cache(issue_id)
    WHERE issue_id <> '';

CREATE TABLE IF NOT EXISTS issue_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER,
    original_issue_id INTEGER,
    machine_number TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_issue_events_machine_recent
    ON issue_events(machine_number, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_issue_events_issue
    ON issue_events(original_issue_id, issue_id);

CREATE TABLE IF NOT EXISTS issue_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER,
    resolved_issue_id INTEGER,
    machine_number TEXT NOT NULL,
    file_path TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_issue_attachments_issue
    ON issue_attachments(issue_id, resolved_issue_id);

CREATE TABLE IF NOT EXISTS predictive_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_number TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    suggested_action TEXT NOT NULL DEFAULT '',
    alert_type TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    dismissed_at TEXT NOT NULL DEFAULT '',
    dismissed_by TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_predictive_alerts_dedupe
    ON predictive_alerts(machine_number, alert_type, title, risk_level);

CREATE INDEX IF NOT EXISTS idx_predictive_alerts_machine_recent
    ON predictive_alerts(machine_number, created_at DESC);
"""


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path, timeout=5)
    configure_connection(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def configure_connection(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -20000")


def initialize_database(
    db_path: Path,
    machines: tuple[tuple[object, ...], ...] = (),
) -> None:
    started_at = perf_now()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        # CREATE TABLE IF NOT EXISTS leaves old tables unchanged, so migrate
        # columns referenced by indexes before running the schema script.
        _migrate_issue_id_columns(conn)
        conn.executescript(SCHEMA)
        _ensure_machine_metadata_columns(conn)
        _ensure_issue_id_columns(conn)
        _ensure_future_issue_context_columns(conn)
        _normalize_archive_status_values(conn)
        machine_rows = tuple(_normalize_machine_row(machine) for machine in machines)
        if machine_rows:
            configured_numbers = [str(machine[0]) for machine in machine_rows]
            placeholders = ", ".join("?" for _ in configured_numbers)
            if placeholders:
                conn.execute(
                    f"""
                    UPDATE machines
                    SET is_active = 0
                    WHERE machine_number NOT IN ({placeholders})
                    """,
                    configured_numbers,
                )
            conn.executemany(
                """
                INSERT INTO machines
                    (
                        machine_number,
                        name,
                        area,
                        cell,
                        asset_tag,
                        display_order,
                        manufacturer,
                        model,
                        imm_serial,
                        robot_type,
                        robot_model,
                        robot_serial,
                        is_active
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(machine_number) DO UPDATE SET
                    name = excluded.name,
                    area = excluded.area,
                    cell = excluded.cell,
                    asset_tag = excluded.asset_tag,
                    display_order = excluded.display_order,
                    manufacturer = excluded.manufacturer,
                    model = excluded.model,
                    imm_serial = excluded.imm_serial,
                    robot_type = excluded.robot_type,
                    robot_model = excluded.robot_model,
                    robot_serial = excluded.robot_serial,
                    is_active = excluded.is_active
                """,
                machine_rows,
            )
    perf_log("database.initialize", path=db_path, machines=len(machines), elapsed_ms=elapsed_ms(started_at))


def _ensure_machine_metadata_columns(conn: sqlite3.Connection) -> None:
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(machines)").fetchall()}
    for column in (
        "manufacturer",
        "model",
        "imm_serial",
        "robot_type",
        "robot_model",
        "robot_serial",
    ):
        if column not in existing:
            conn.execute(f"ALTER TABLE machines ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")


def _ensure_future_issue_context_columns(conn: sqlite3.Connection) -> None:
    for table in ("active_issues", "resolved_issues_cache"):
        if not _table_exists(conn, table):
            continue
        existing = _table_columns(conn, table)
        for column in ("what_changed", "tried_already"):
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")


def _ensure_issue_id_columns(conn: sqlite3.Connection) -> None:
    for table in ISSUE_ID_SCHEMA_TABLES:
        if not _table_exists(conn, table):
            continue
        existing = _table_columns(conn, table)
        if "issue_id" not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN issue_id TEXT NOT NULL DEFAULT ''")
    _backfill_missing_issue_ids(conn)
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_active_issues_public_issue_id
            ON active_issues(issue_id)
            WHERE issue_id <> ''
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_resolved_public_issue_id
            ON resolved_issues_cache(issue_id)
            WHERE issue_id <> ''
        """
    )


def _normalize_archive_status_values(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "resolved_issues_cache"):
        return
    conn.execute(
        """
        UPDATE resolved_issues_cache
        SET archive_status = 'failed'
        WHERE archive_status = 'archive_error'
        """
    )


def _migrate_issue_id_columns(conn: sqlite3.Connection) -> None:
    for table in ISSUE_ID_MIGRATION_TABLES:
        if not _table_exists(conn, table):
            continue
        if "issue_id" not in _table_columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN issue_id TEXT NOT NULL DEFAULT ''")
    _backfill_missing_issue_ids(conn)


def _backfill_missing_issue_ids(conn: sqlite3.Connection) -> None:
    existing_issue_ids = _existing_issue_ids(conn)
    for table in ISSUE_ID_MIGRATION_TABLES:
        if not _table_exists(conn, table):
            continue
        columns = _table_columns(conn, table)
        if "id" not in columns or "issue_id" not in columns:
            continue
        date_expression = _first_existing_column(
            columns,
            ("created_at", "submitted_at", "logged_at", "reported_at", "resolved_at", "updated_at"),
        )
        select_date = date_expression if date_expression is not None else "'' AS migrated_issue_date"
        rows = conn.execute(
            f"""
            SELECT id, issue_id, {select_date}
            FROM {table}
            WHERE issue_id IS NULL OR issue_id = ''
            ORDER BY id
            """
        ).fetchall()
        for row in rows:
            created_at = row[date_expression] if date_expression is not None else ""
            public_issue_id = generate_issue_id(
                _issue_id_source_date(created_at),
                existing_issue_ids,
            )
            conn.execute(
                f"""
                UPDATE {table}
                SET issue_id = ?
                WHERE id = ?
                """,
                (public_issue_id, row["id"]),
            )
            existing_issue_ids.add(public_issue_id)


def _existing_issue_ids(conn: sqlite3.Connection) -> set[str]:
    issue_ids: set[str] = set()
    for table in ISSUE_ID_MIGRATION_TABLES:
        if not _table_exists(conn, table) or "issue_id" not in _table_columns(conn, table):
            continue
        rows = conn.execute(
            f"""
            SELECT issue_id
            FROM {table}
            WHERE issue_id IS NOT NULL AND issue_id <> ''
            """
        ).fetchall()
        issue_ids.update(str(row["issue_id"]).strip() for row in rows if str(row["issue_id"]).strip())
    return issue_ids


def _issue_id_source_date(value: object) -> str:
    text = str(value or "").strip()
    if text:
        try:
            issue_id_date_key(text)
            return text
        except ValueError:
            pass
    return date.today().strftime("%Y%m%d")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _first_existing_column(columns: set[str], candidates: tuple[str, ...]) -> str | None:
    return next((column for column in candidates if column in columns), None)


def _normalize_machine_row(row: tuple[object, ...]) -> tuple[object, ...]:
    if len(row) == 13:
        return row
    if len(row) == 12:
        return (*row, 1)
    if len(row) == 6:
        return (*row, "", "", "", "", "", "", 1)
    raise ValueError("Machine rows must have 6 base fields, 12 metadata fields, or 13 fields with active state.")
