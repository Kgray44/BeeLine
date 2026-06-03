from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from beeline_issue_tracker.config import load_runtime_config
from beeline_issue_tracker.security import hash_pin, verify_pin


class SecurityTest(unittest.TestCase):
    def test_hash_pin_and_verify_pin(self) -> None:
        stored = hash_pin("1234", "fixed-test-salt", iterations=10_000)
        self.assertTrue(verify_pin("1234", stored))
        self.assertFalse(verify_pin("9999", stored))
        self.assertFalse(verify_pin("1234", "not-a-valid-hash"))

    def test_default_config_preserves_no_security_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "beeline_config.json"
            config_path.write_text(json.dumps({"version": 1, "machines": []}), encoding="utf-8")

            config = load_runtime_config(config_path)

            self.assertFalse(config.resolve_requires_pin())
            self.assertFalse(config.verify_pin_for_roles("1234", ("technician", "admin")))

    def test_role_config_requires_and_verifies_technician_pin(self) -> None:
        stored = hash_pin("2468", "role-test-salt", iterations=10_000)
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "beeline_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "roles": {
                            "operator": {"enabled": True, "pin_hash": ""},
                            "technician": {"enabled": True, "pin_hash": stored},
                            "admin": {"enabled": False, "pin_hash": ""},
                        },
                        "machines": [],
                    }
                ),
                encoding="utf-8",
            )

            config = load_runtime_config(config_path)

            self.assertTrue(config.resolve_requires_pin())
            self.assertFalse(config.verify_pin_for_roles("1357", ("technician", "admin")))
            self.assertTrue(config.verify_pin_for_roles("2468", ("technician", "admin")))


if __name__ == "__main__":
    unittest.main()

