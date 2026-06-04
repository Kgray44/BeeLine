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

from beeline_issue_tracker.analytics.models import (
    MachineRiskSummary,
    MachineTrendPoint,
    PredictiveMaintenanceAlert,
    RecurringIssuePattern,
)
from beeline_issue_tracker.analytics.predictive_service import filter_machine_risks, sort_machine_risks
from beeline_issue_tracker.analytics.reporting import (
    build_machine_predictive_summary_text,
    build_predictive_summary_text,
)
from beeline_issue_tracker.config import load_runtime_config
from beeline_issue_tracker.ui_v2.charts import normalize_chart_values, risk_level_color


class PredictiveReportingConfigUiHelpersTest(unittest.TestCase):
    def test_global_summary_includes_top_risks_and_empty_state(self) -> None:
        risk = _risk("DEMO-101", 88, "Critical")
        alert = PredictiveMaintenanceAlert(
            machine_number="DEMO-101",
            machine_name="Demo Molder 101",
            risk_level="Critical",
            risk_score=88,
            title="Critical risk: Machine DEMO-101",
            message="Guard switch open",
            reasons=("Open Line Down",),
            suggested_action="Review current Line Down issue immediately.",
            created_at="2026-06-03T12:00:00+00:00",
            alert_type="machine_risk",
        )
        summary = build_predictive_summary_text([risk], [alert], [])
        self.assertIn("Machine DEMO-101", summary)
        self.assertIn("Generated locally from BeeLine issue history", summary)
        empty = build_predictive_summary_text([], [], [])
        self.assertIn("Not enough issue history", empty)

    def test_machine_summary_includes_reasons_actions_and_trend(self) -> None:
        risk = _risk("DEMO-101", 65, "High")
        pattern = RecurringIssuePattern(
            machine_number="DEMO-101",
            pattern_key="category:sensor",
            display_label="Sensor",
            category="Sensor",
            severity="Non-Critical",
            occurrence_count=3,
            first_seen_at="2026-05-01T12:00:00+00:00",
            last_seen_at="2026-06-01T12:00:00+00:00",
            average_time_between_days=10.0,
            example_titles=("Sensor drift",),
            common_solutions=("Tightened connector.",),
            risk_note="Sensor has repeated 3 times.",
        )
        trend = [
            MachineTrendPoint("05/27", "", "", 1, 2, 0, 3, 45),
            MachineTrendPoint("06/03", "", "", 2, 1, 1, 2, 30),
        ]
        summary = build_machine_predictive_summary_text(risk, [pattern], trend)
        self.assertIn("Suggested action", summary)
        self.assertIn("Sensor has repeated", summary)
        self.assertIn("06/03", summary)

    def test_analytics_config_defaults_partial_and_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"machines": [], "analytics": {"risk_window_days": "bad"}}), encoding="utf-8")
            config = load_runtime_config(path)
            self.assertTrue(config.analytics.enabled)
            self.assertEqual(30, config.analytics.risk_window_days)
            self.assertEqual(60, config.analytics.recurrence_window_days)

            path.write_text(
                json.dumps({"machines": [], "analytics": {"enabled": False, "grouped_chart_periods": 12}}),
                encoding="utf-8",
            )
            config = load_runtime_config(path)
            self.assertFalse(config.analytics.enabled)
            self.assertEqual(12, config.analytics.grouped_chart_periods)

    def test_chart_and_sort_filter_helpers(self) -> None:
        self.assertEqual([0.0, 0.5, 1.0], normalize_chart_values([0, 5, 10]))
        self.assertEqual([0.0, 0.0], normalize_chart_values([0, 0]))
        self.assertEqual("#d64545", risk_level_color("Critical"))
        risks = [_risk("DEMO-202", 20, "Low"), _risk("DEMO-101", 90, "Critical")]
        filtered = filter_machine_risks(risks, query="101", risk_level="")
        self.assertEqual(["DEMO-101"], [risk.machine_number for risk in filtered])
        sorted_risks = sort_machine_risks(risks, sort_key="risk_score")
        self.assertEqual(["DEMO-101", "DEMO-202"], [risk.machine_number for risk in sorted_risks])


def _risk(machine_number: str, score: int, level: str) -> MachineRiskSummary:
    return MachineRiskSummary(
        machine_number=machine_number,
        machine_name=f"Demo Machine {machine_number}",
        area="Demo Hive",
        cell="Cell A",
        risk_score=score,
        risk_level=level,
        risk_reasons=("Open Line Down issue: +35",),
        open_issue_count=1,
        line_down_open_count=1 if level in {"High", "Critical"} else 0,
        non_critical_open_count=0,
        recent_issue_count=1,
        recent_line_down_count=1 if level in {"High", "Critical"} else 0,
        recurring_issue_count=0,
        average_time_open_minutes=45,
        last_issue_at="2026-06-03T12:00:00+00:00",
        predicted_problem="Guard switch open",
        suggested_action="Review current Line Down issue immediately.",
        predicted_window="Now / immediate",
        confidence="Medium",
    )


if __name__ == "__main__":
    unittest.main()
