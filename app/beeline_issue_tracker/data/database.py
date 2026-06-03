from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS machines (
    machine_number TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    area TEXT NOT NULL,
    cell TEXT NOT NULL DEFAULT '',
    asset_tag TEXT NOT NULL DEFAULT '',
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS active_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_number TEXT NOT NULL,
    logged_by TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('Line Down', 'Non-Critical')),
    category TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (machine_number) REFERENCES machines(machine_number)
);

CREATE INDEX IF NOT EXISTS idx_active_issues_machine
    ON active_issues(machine_number, severity, created_at);

CREATE TABLE IF NOT EXISTS resolved_issues_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_issue_id INTEGER NOT NULL,
    machine_number TEXT NOT NULL,
    logged_by TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    resolved_at TEXT NOT NULL,
    resolved_by TEXT NOT NULL DEFAULT '',
    solution TEXT NOT NULL,
    archive_status TEXT NOT NULL DEFAULT 'pending',
    archive_error TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_resolved_machine_recent
    ON resolved_issues_cache(machine_number, resolved_at DESC);

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
"""


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database(
    db_path: Path,
    machines: tuple[tuple[str, str, str, str, str, int], ...] = (),
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        machine_count = conn.execute("SELECT COUNT(*) FROM machines").fetchone()[0]
        if machine_count == 0 and machines:
            conn.executemany(
                """
                INSERT INTO machines
                    (machine_number, name, area, cell, asset_tag, display_order)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                machines,
            )
