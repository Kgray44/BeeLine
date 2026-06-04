from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from PySide6.QtCore import QSettings

from beeline_issue_tracker.ui_v2.theme import (
    CARD_COLOR_STYLE_BRIGHT,
    CARD_COLOR_STYLE_LEGACY,
    DARK_THEME,
    LIGHT_THEME,
    THEMES,
    ThemeManager,
)


class ThemeManagerTest(unittest.TestCase):
    def test_dark_theme_is_default_and_stylesheet_builds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = QSettings(str(Path(tmp) / "settings.ini"), QSettings.Format.IniFormat)
            manager = ThemeManager(settings)

            self.assertEqual(DARK_THEME, manager.current_theme_name)
            self.assertEqual(CARD_COLOR_STYLE_BRIGHT, manager.current_card_color_style)
            stylesheet = manager.build_stylesheet()
            self.assertIn(THEMES[DARK_THEME].background, stylesheet)
            self.assertIn(THEMES[DARK_THEME].status_line_down, stylesheet)

    def test_theme_selection_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.ini"
            manager = ThemeManager(QSettings(str(settings_path), QSettings.Format.IniFormat))
            manager.set_theme(LIGHT_THEME)

            restored = ThemeManager(QSettings(str(settings_path), QSettings.Format.IniFormat))
            self.assertEqual(LIGHT_THEME, restored.current_theme_name)
            self.assertIn(THEMES[LIGHT_THEME].background, restored.build_stylesheet())

    def test_card_color_style_selection_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.ini"
            manager = ThemeManager(QSettings(str(settings_path), QSettings.Format.IniFormat))
            manager.set_card_color_style(CARD_COLOR_STYLE_LEGACY)

            restored = ThemeManager(QSettings(str(settings_path), QSettings.Format.IniFormat))
            self.assertEqual(CARD_COLOR_STYLE_LEGACY, restored.current_card_color_style)
            self.assertIn("border-left: 5px solid", restored.build_stylesheet())


if __name__ == "__main__":
    unittest.main()
