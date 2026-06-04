from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from beeline_issue_tracker.config import AppPaths


class PackagingPathsTest(unittest.TestCase):
    def test_source_mode_defaults_templates_to_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"BEELINE_ROOT_DIR": str(root)}, clear=True):
                paths = AppPaths.from_environment()

        self.assertEqual(root.resolve(), paths.root_dir)
        self.assertEqual((root / "templates").resolve(), paths.template_dir)
        self.assertEqual((root / "assets" / "branding").resolve(), paths.branding_dir)
        self.assertEqual((root / "data" / "beeline.sqlite").resolve(), paths.db_path)

    def test_frozen_mode_reads_bundle_resources_and_writes_to_local_app_data(self) -> None:
        with tempfile.TemporaryDirectory() as bundle_tmp, tempfile.TemporaryDirectory() as local_tmp:
            bundle_root = Path(bundle_tmp)
            local_app_data = Path(local_tmp)
            with (
                patch.dict(os.environ, {"LOCALAPPDATA": str(local_app_data)}, clear=True),
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "_MEIPASS", str(bundle_root), create=True),
            ):
                paths = AppPaths.from_environment()

        runtime_root = (local_app_data / "BeeLine Issue Tracker").resolve()
        self.assertEqual(runtime_root, paths.root_dir)
        self.assertEqual((bundle_root / "templates").resolve(), paths.template_dir)
        self.assertEqual((bundle_root / "assets" / "branding").resolve(), paths.branding_dir)
        self.assertEqual((runtime_root / "config" / "beeline_config.json").resolve(), paths.runtime_config_path)
        self.assertEqual((runtime_root / "data" / "beeline.sqlite").resolve(), paths.db_path)
        self.assertEqual((runtime_root / "archive" / "beeline_resolved_archive.xlsx").resolve(), paths.archive_path)


if __name__ == "__main__":
    unittest.main()
