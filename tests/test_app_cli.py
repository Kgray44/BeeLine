from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from beeline_issue_tracker import app as beeline_app
from beeline_issue_tracker.config import AppPaths
from scripts.initialize_runtime_files import create_templates


class AppCliTest(unittest.TestCase):
    def test_ui_version_defaults_to_v2(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            args = beeline_app.build_parser().parse_args([])

        self.assertEqual("v2", args.ui_version)

    def test_ui_version_can_come_from_environment(self) -> None:
        with patch.dict(os.environ, {"BEELINE_UI_VERSION": "v2"}, clear=False):
            args = beeline_app.build_parser().parse_args([])

        self.assertEqual("v2", args.ui_version)

    def test_ui_version_cli_accepts_current_ui(self) -> None:
        with patch.dict(os.environ, {"BEELINE_UI_VERSION": "v1"}, clear=False):
            args = beeline_app.build_parser().parse_args(["--ui-version", "v2"])

        self.assertEqual("v2", args.ui_version)

    def test_check_does_not_force_archive_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(Path(tmp))
            with patch.dict(os.environ, env, clear=False):
                paths = AppPaths.from_environment()
                create_templates(paths, force=True)
                with (
                    patch("beeline_issue_tracker.app.refresh_archive_workbook") as refresh,
                    patch("beeline_issue_tracker.app.inspect_archive") as inspect_archive,
                ):
                    result = beeline_app.main(["--check"])
                archive_exists_after_check = paths.archive_path.exists()

        self.assertEqual(0, result)
        refresh.assert_not_called()
        inspect_archive.assert_not_called()
        self.assertFalse(archive_exists_after_check)

    def test_repair_archive_forces_archive_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(Path(tmp))
            with patch.dict(os.environ, env, clear=False):
                create_templates(AppPaths.from_environment(), force=True)
                with patch("beeline_issue_tracker.app.refresh_archive_workbook") as refresh:
                    result = beeline_app.main(["--repair-archive"])

        self.assertEqual(0, result)
        refresh.assert_called_once()

    @staticmethod
    def _env(root: Path) -> dict[str, str]:
        return {
            "BEELINE_ROOT_DIR": str(root),
            "BEELINE_TEMPLATE_DIR": str(root / "templates"),
            "BEELINE_CONFIG_DIR": str(root / "config"),
            "BEELINE_DATA_DIR": str(root / "data"),
            "BEELINE_ARCHIVE_DIR": str(root / "archive"),
            "BEELINE_LOG_DIR": str(root / "logs"),
            "BEELINE_BACKUP_DIR": str(root / "backups"),
        }


if __name__ == "__main__":
    unittest.main()
