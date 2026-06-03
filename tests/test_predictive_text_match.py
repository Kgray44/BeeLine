from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from beeline_issue_tracker.analytics.text_match import (
    build_fix_suggestions,
    find_related_resolved_issues,
    keyword_overlap_score,
    normalize_text,
    tokenize,
)
from beeline_issue_tracker.domain import NON_CRITICAL, Issue, ResolvedIssue


NOW = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)


class PredictiveTextMatchTest(unittest.TestCase):
    def test_normalization_and_tokenizing_remove_stop_words(self) -> None:
        self.assertEqual("sensor drift on machine", normalize_text("Sensor drift on MACHINE!"))
        self.assertEqual({"sensor", "drift"}, tokenize("The sensor drift problem on machine"))

    def test_similar_issue_titles_match(self) -> None:
        current = _active("Nozzle temperature sensor drift", "Nozzle temp wanders after startup", "Sensor")
        history = [
            _resolved(1, "Nozzle temp sensor drifting", "Temperature wanders after heat soak", "Sensor"),
            _resolved(2, "Oil leak at clamp", "Hydraulic oil found under clamp", "Hydraulic"),
        ]
        matches = find_related_resolved_issues(current, history, limit=5)
        self.assertEqual([1], [match.issue_id for match in matches])
        self.assertTrue(any("Same category" in reason for reason in matches[0].match_reasons))

    def test_unrelated_issues_do_not_match(self) -> None:
        current = _active("Robot ready fault", "Robot not ready at cycle start", "Automation")
        history = [_resolved(1, "Oil leak at clamp", "Hydraulic oil under clamp", "Hydraulic", machine="DEMO-202")]
        self.assertEqual([], find_related_resolved_issues(current, history))

    def test_same_category_and_machine_increase_match_score(self) -> None:
        current = _active("Sensor noise", "Sensor value flickers", "Sensor")
        same = _resolved(1, "Sensor noise", "Sensor value flickers", "Sensor")
        other_machine = _resolved(2, "Sensor noise", "Sensor value flickers", "Sensor", machine="DEMO-202")
        matches = find_related_resolved_issues(current, [other_machine, same], limit=2)
        self.assertGreater(matches[0].match_score, matches[1].match_score)
        self.assertEqual("DEMO-101", matches[0].machine_number)

    def test_fix_suggestions_use_only_actual_solution_text(self) -> None:
        current = _active("Nozzle heater cold", "Nozzle heater is not reaching setpoint", "Process")
        history = [
            _resolved(1, "Nozzle heater cold", "Nozzle heater below setpoint", "Process", solution="Replaced heater band."),
            _resolved(2, "Robot ready fault", "Robot not ready", "Automation", solution="Reset robot controller."),
        ]
        related = find_related_resolved_issues(current, history)
        suggestions = build_fix_suggestions(related, history)
        self.assertEqual(1, len(suggestions))
        self.assertIn("Replaced heater band", suggestions[0].suggestion)
        self.assertNotIn("Reset robot controller", suggestions[0].suggestion)

    def test_no_related_history_means_no_invented_suggestion(self) -> None:
        self.assertEqual([], build_fix_suggestions([], [_resolved(1)]))
        self.assertEqual(0, keyword_overlap_score("guard switch", "oil leak"))


def _active(title: str, description: str, category: str) -> Issue:
    return Issue(
        id=99,
        machine_number="DEMO-101",
        logged_by="Synthetic Operator",
        title=title,
        description=description,
        severity=NON_CRITICAL,
        category=category,
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
    )


def _resolved(
    issue_id: int,
    title: str = "Nozzle temperature sensor drift",
    description: str = "Temperature sensor wanders.",
    category: str = "Sensor",
    *,
    machine: str = "DEMO-101",
    solution: str = "Tightened sensor connector.",
) -> ResolvedIssue:
    created = NOW - timedelta(days=3)
    resolved = NOW - timedelta(days=2)
    return ResolvedIssue(
        id=issue_id,
        original_issue_id=issue_id,
        machine_number=machine,
        logged_by="Synthetic Operator",
        title=title,
        description=description,
        severity=NON_CRITICAL,
        category=category,
        created_at=created.isoformat(),
        resolved_at=resolved.isoformat(),
        resolved_by="Synthetic Tech",
        solution=solution,
        archive_status="archived",
        archive_error="",
    )


if __name__ == "__main__":
    unittest.main()

