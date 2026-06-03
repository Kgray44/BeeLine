from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from beeline_issue_tracker.data.database import configure_connection, initialize_database


DEMO_MACHINES = (
    ("DEMO-101", "Demo Molder 101", "Demo Hive", "Cell A", "DEMO-ASSET-101", 10),
    ("DEMO-202", "Demo Press 202", "Demo Hive", "Cell B", "DEMO-ASSET-202", 20),
)


class DatabaseMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "beeline.sqlite3"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_fresh_empty_database_initializes_schema(self) -> None:
        initialize_database(self.db_path, DEMO_MACHINES)

        with _connect(self.db_path) as conn:
            active_columns = _columns(conn, "active_issues")
            resolved_columns = _columns(conn, "resolved_issues_cache")
            active_indexes = _indexes(conn, "active_issues")
            resolved_indexes = _indexes(conn, "resolved_issues_cache")

            self.assertIn("issue_id", active_columns)
            self.assertIn("issue_id", resolved_columns)
            self.assertIn("idx_active_issues_public_issue_id", active_indexes)
            self.assertIn("idx_active_issues_machine_created", active_indexes)
            self.assertIn("idx_active_issues_machine_severity_created", active_indexes)
            self.assertIn("idx_resolved_issues_machine_resolved", resolved_indexes)
            self.assertIn("idx_resolved_issues_machine_title", resolved_indexes)
            self.assertIn("idx_resolved_issues_archive_status", resolved_indexes)
            self.assertEqual("wal", conn.execute("PRAGMA journal_mode").fetchone()[0])
            self.assertEqual(1, conn.execute("PRAGMA foreign_keys").fetchone()[0])
            self.assertEqual(len(DEMO_MACHINES), conn.execute("SELECT COUNT(*) FROM machines").fetchone()[0])

    def test_old_database_without_active_issue_id_column_migrates(self) -> None:
        _create_old_issue_database(self.db_path)

        with _connect(self.db_path) as conn:
            self.assertNotIn("issue_id", _columns(conn, "active_issues"))

        initialize_database(self.db_path, DEMO_MACHINES)

        with _connect(self.db_path) as conn:
            self.assertIn("issue_id", _columns(conn, "active_issues"))
            rows = conn.execute(
                """
                SELECT id, issue_id
                FROM active_issues
                ORDER BY id
                """
            ).fetchall()

        self.assertEqual(
            ["ISS-20260601-001", "ISS-20260601-002", "ISS-20260602-001"],
            [row["issue_id"] for row in rows],
        )

    def test_literal_legacy_issues_table_without_issue_id_column_migrates(self) -> None:
        _create_literal_legacy_issues_table(self.db_path)

        initialize_database(self.db_path, DEMO_MACHINES)

        with _connect(self.db_path) as conn:
            self.assertIn("issue_id", _columns(conn, "issues"))
            rows = conn.execute(
                """
                SELECT id, issue_id
                FROM issues
                ORDER BY id
                """
            ).fetchall()

        self.assertEqual(["ISS-20260604-001", "ISS-20260604-002"], [row["issue_id"] for row in rows])

    def test_migrated_issue_ids_are_unique_across_active_and_resolved_history(self) -> None:
        _create_old_issue_database(self.db_path)

        initialize_database(self.db_path, DEMO_MACHINES)

        with _connect(self.db_path) as conn:
            issue_ids = [
                row["issue_id"]
                for row in conn.execute(
                    """
                    SELECT issue_id FROM active_issues
                    UNION ALL
                    SELECT issue_id FROM resolved_issues_cache
                    """
                ).fetchall()
            ]

        self.assertEqual(4, len(issue_ids))
        self.assertEqual(4, len(set(issue_ids)))
        self.assertEqual(sorted(issue_ids), sorted(set(issue_ids)))
        self.assertIn("ISS-20260601-003", issue_ids)

    def test_startup_allows_existing_issue_id_indexes(self) -> None:
        initialize_database(self.db_path, DEMO_MACHINES)

        initialize_database(self.db_path, DEMO_MACHINES)

        with _connect(self.db_path) as conn:
            self.assertIn("idx_active_issues_public_issue_id", _indexes(conn, "active_issues"))
            self.assertIn("idx_resolved_public_issue_id", _indexes(conn, "resolved_issues_cache"))


def _create_old_issue_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE machines (
                machine_number TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                area TEXT NOT NULL,
                cell TEXT NOT NULL DEFAULT '',
                asset_tag TEXT NOT NULL DEFAULT '',
                display_order INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE active_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_number TEXT NOT NULL,
                logged_by TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                severity TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE resolved_issues_cache (
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
            """
        )
        conn.executemany(
            """
            INSERT INTO machines
                (machine_number, name, area, cell, asset_tag, display_order)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            DEMO_MACHINES,
        )
        conn.executemany(
            """
            INSERT INTO active_issues
                (machine_number, logged_by, title, description, severity, category, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    "DEMO-101",
                    "Alex",
                    "First legacy issue",
                    "Old active issue",
                    "Non-Critical",
                    "Sensor",
                    "2026-06-01T08:00:00+00:00",
                    "2026-06-01T08:00:00+00:00",
                ),
                (
                    "DEMO-202",
                    "Jordan",
                    "Second legacy issue",
                    "Old active issue on same date",
                    "Line Down",
                    "Safety",
                    "2026-06-01T09:00:00+00:00",
                    "2026-06-01T09:00:00+00:00",
                ),
                (
                    "DEMO-101",
                    "Casey",
                    "Next day legacy issue",
                    "Old active issue on another date",
                    "Non-Critical",
                    "Hydraulic",
                    "2026-06-02T10:00:00+00:00",
                    "2026-06-02T10:00:00+00:00",
                ),
            ),
        )
        conn.execute(
            """
            INSERT INTO resolved_issues_cache
                (
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
                    archive_status
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                99,
                "DEMO-101",
                "Riley",
                "Resolved legacy issue",
                "Old resolved issue",
                "Non-Critical",
                "Process",
                "2026-06-01T07:30:00+00:00",
                "2026-06-01T08:15:00+00:00",
                "Taylor",
                "Reset sensor.",
                "archived",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _create_literal_legacy_issues_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                submitted_at TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO issues (title, submitted_at)
            VALUES (?, ?)
            """,
            (
                ("Legacy literal issue", "2026-06-04T08:00:00+00:00"),
                ("Second literal issue", "2026-06-04T09:00:00+00:00"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    configure_connection(conn)
    try:
        yield conn
    finally:
        conn.close()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _indexes(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA index_list({table})").fetchall()}


if __name__ == "__main__":
    unittest.main()
