from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts import verify_safe_for_github as safety


class SafetyScannerTest(unittest.TestCase):
    def test_safe_warning_text_passes(self) -> None:
        text = (
            "Never commit real machine data, employee names, badge IDs, issue history, "
            "or secrets. This is warning text only."
        )
        self.assertEqual([], safety.scan_text_for_sensitive_content("README.md", text))

    def test_fake_email_fails(self) -> None:
        text = "Contact " + "person" + "@example" + ".com for details."
        issues = safety.scan_text_for_sensitive_content("notes.txt", text)
        self.assertTrue(any("Email address" in issue for issue in issues))

    def test_fake_sharepoint_url_fails(self) -> None:
        text = "See " + "https://demo." + "sharepoint" + ".com/sites/private"
        issues = safety.scan_text_for_sensitive_content("notes.txt", text)
        self.assertTrue(any("SharePoint" in issue for issue in issues))

    def test_fake_env_token_text_fails(self) -> None:
        text = "OPENAI_API_KEY" + "=" + "sk-" + ("A" * 30)
        issues = safety.scan_text_for_sensitive_content(".env.example", text)
        self.assertTrue(any("Credential" in issue or "OpenAI" in issue for issue in issues))

    def test_screenshot_filename_fails_but_placeholder_logo_passes(self) -> None:
        failures: list[str] = []
        safety._check_git_sensitive_files({"screenshots/line-stop.png"}, failures)
        self.assertTrue(any("NDA-sensitive generated folder" in failure for failure in failures))

        failures = []
        safety._check_git_sensitive_files({"assets/branding/nolato_logo_placeholder.png"}, failures)
        self.assertEqual([], failures)

    def test_sanitized_templates_pass(self) -> None:
        failures: list[str] = []
        safety._check_templates(failures)
        self.assertEqual([], failures)


if __name__ == "__main__":
    unittest.main()

