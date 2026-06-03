from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from beeline_issue_tracker.permissions import (
    can_archive_issue,
    can_close_issue,
    can_create_issue,
    can_delete_issue,
    can_dismiss_predictive_alert,
    can_edit_issue,
    can_manage_machine_intelligence,
    can_manage_users,
    can_open_settings,
    can_resolve_issue,
    can_use_database_tools,
)


class PermissionsTest(unittest.TestCase):
    def test_issue_creation_is_open_to_every_role(self) -> None:
        for role in (None, "viewer", "basic", "operator", "technician", "admin"):
            with self.subTest(role=role):
                self.assertTrue(can_create_issue(role))

    def test_restricted_actions_stay_restricted(self) -> None:
        for role in (None, "viewer", "basic", "operator"):
            with self.subTest(role=role):
                self.assertFalse(can_edit_issue(role))
                self.assertFalse(can_resolve_issue(role))
                self.assertFalse(can_close_issue(role))
                self.assertFalse(can_archive_issue(role))
                self.assertFalse(can_delete_issue(role))
                self.assertFalse(can_dismiss_predictive_alert(role))
                self.assertFalse(can_manage_machine_intelligence(role))
                self.assertFalse(can_open_settings(role))
                self.assertFalse(can_manage_users(role))
                self.assertFalse(can_use_database_tools(role))

        for role in ("technician", "admin"):
            with self.subTest(role=role):
                self.assertTrue(can_edit_issue(role))
                self.assertTrue(can_resolve_issue(role))
                self.assertTrue(can_close_issue(role))
                self.assertTrue(can_dismiss_predictive_alert(role))

        self.assertFalse(can_archive_issue("technician"))
        self.assertTrue(can_archive_issue("admin"))
        self.assertFalse(can_delete_issue("technician"))
        self.assertTrue(can_delete_issue("admin"))
        self.assertFalse(can_manage_machine_intelligence("technician"))
        self.assertTrue(can_manage_machine_intelligence("admin"))
        self.assertFalse(can_open_settings("technician"))
        self.assertTrue(can_open_settings("admin"))
        self.assertFalse(can_manage_users("technician"))
        self.assertTrue(can_manage_users("admin"))
        self.assertFalse(can_use_database_tools("technician"))
        self.assertTrue(can_use_database_tools("admin"))


if __name__ == "__main__":
    unittest.main()
