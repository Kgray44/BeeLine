from __future__ import annotations

"""Tests for explainable predictive maintenance risk scoring."""

from datetime import datetime, timedelta, timezone
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"
for path in (APP_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from beeline_issue_tracker.analytics.models import MachineRiskInput
from beeline_issue_tracker.analytics.risk_engine import build_machine_risk_summary
from beeline_issue_tracker.domain import LINE_DOWN, NON_CRITICAL, Issue, ResolvedIssue


NOW = datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc)


class PredictiveRiskEngineTest(unittest.TestCase):
    def test_machine_with_no_history_is_unknown(self) -> None:
        risk = build_machine_risk_summary(_risk_input(), now=NOW)
        self.assertEqual("Unknown", risk.risk_level)
        self.assertEqual(0, risk.risk_score)
        self.assertEqual("Unknown", risk.confidence)

    def test_open_line_down_raises_risk_to_high_or_critical(self) -> None:
        issue = _active(1, "Guard switch open", LINE_DOWN, "Safety", NOW - timedelta(hours=1))
        risk = build_machine_risk_summary(_risk_input(active=(issue,)), now=NOW)
        self.assertGreaterEqual(risk.risk_score, 65)
        self.assertIn(risk.risk_level, {"High", "Critical"})
        self.assertIn("Review current Line Down issue immediately.", risk.suggested_action)
        self.assertEqual("Now / immediate", risk.predicted_window)

    def test_recurring_non_critical_issues_increase_risk(self) -> None:
        resolved = tuple(
            _resolved(
                index,
                "Nozzle heater drift",
                NON_CRITICAL,
                "Process",
                NOW - timedelta(days=days, hours=2),
                NOW - timedelta(days=days),
            )
            for index, days in enumerate((2, 8, 14), start=1)
        )
        risk = build_machine_risk_summary(_risk_input(resolved=resolved), now=NOW)
        self.assertGreaterEqual(risk.recurring_issue_count, 1)
        self.assertGreaterEqual(risk.risk_score, 40)
        self.assertIn("Nozzle heater drift", risk.predicted_problem)

    def test_recent_issue_spike_adds_reason(self) -> None:
        recent = tuple(
            _resolved(
                index,
                f"Sensor drift {index}",
                NON_CRITICAL,
                "Sensor",
                NOW - timedelta(days=index),
                NOW - timedelta(days=index, hours=-1),
            )
            for index in range(1, 4)
        )
        older = (_resolved(10, "Old oil weep", NON_CRITICAL, "Hydraulic", NOW - timedelta(days=45), NOW - timedelta(days=44)),)
        risk = build_machine_risk_summary(_risk_input(resolved=recent + older), now=NOW)
        self.assertTrue(any("Recent activity increased" in reason for reason in risk.risk_reasons))

    def test_stable_machine_with_old_history_gets_stability_reduction(self) -> None:
        resolved = (_resolved(1, "Old sensor issue", NON_CRITICAL, "Sensor", NOW - timedelta(days=100), NOW - timedelta(days=99)),)
        risk = build_machine_risk_summary(_risk_input(resolved=resolved), now=NOW)
        self.assertEqual("Stable", risk.risk_level)
        self.assertEqual(0, risk.risk_score)
        self.assertTrue(any("No issues in the last 60 days" in reason for reason in risk.risk_reasons))

    def test_score_caps_at_100(self) -> None:
        active = tuple(
            _active(index, f"Line down {index}", LINE_DOWN, "Safety", NOW - timedelta(hours=index))
            for index in range(1, 8)
        )
        risk = build_machine_risk_summary(_risk_input(active=active), now=NOW)
        self.assertEqual(100, risk.risk_score)

    def test_confidence_levels_follow_history_count(self) -> None:
        one = build_machine_risk_summary(_risk_input(resolved=(_resolved(1),)), now=NOW)
        four = build_machine_risk_summary(
            _risk_input(resolved=tuple(_resolved(index) for index in range(1, 5))),
            now=NOW,
        )
        ten = build_machine_risk_summary(
            _risk_input(resolved=tuple(_resolved(index) for index in range(1, 11))),
            now=NOW,
        )
        self.assertEqual("Low", one.confidence)
        self.assertEqual("Medium", four.confidence)
        self.assertEqual("High", ten.confidence)


def _risk_input(active=(), resolved=()) -> MachineRiskInput:
    return MachineRiskInput(
        machine_number="DEMO-101",
        machine_name="Demo Molder 101",
        area="Demo Hive",
        cell="Cell A",
        asset_tag="DEMO-ASSET-101",
        display_order=10,
        active_issues=tuple(active),
        resolved_issues=tuple(resolved),
    )


def _active(
    issue_id: int,
    title: str = "Sensor drift",
    severity: str = NON_CRITICAL,
    category: str = "Sensor",
    created_at: datetime | None = None,
) -> Issue:
    created = created_at or NOW - timedelta(days=1)
    return Issue(
        id=issue_id,
        machine_number="DEMO-101",
        logged_by="Synthetic Operator",
        title=title,
        description=f"{title} synthetic description",
        severity=severity,
        category=category,
        created_at=created.isoformat(),
        updated_at=created.isoformat(),
    )


def _resolved(
    issue_id: int,
    title: str = "Sensor drift",
    severity: str = NON_CRITICAL,
    category: str = "Sensor",
    created_at: datetime | None = None,
    resolved_at: datetime | None = None,
) -> ResolvedIssue:
    created = created_at or NOW - timedelta(days=1, hours=2)
    resolved = resolved_at or NOW - timedelta(days=1)
    return ResolvedIssue(
        id=issue_id,
        original_issue_id=issue_id,
        machine_number="DEMO-101",
        logged_by="Synthetic Operator",
        title=title,
        description=f"{title} synthetic description",
        severity=severity,
        category=category,
        created_at=created.isoformat(),
        resolved_at=resolved.isoformat(),
        resolved_by="Synthetic Tech",
        solution="Verified connection and reset controller.",
        archive_status="archived",
        archive_error="",
    )


if __name__ == "__main__":
    unittest.main()
