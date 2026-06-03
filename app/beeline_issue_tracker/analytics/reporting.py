from __future__ import annotations

from datetime import datetime, timezone

from beeline_issue_tracker.analytics.models import (
    MachineRiskSummary,
    MachineTrendPoint,
    PredictiveMaintenanceAlert,
    RecurringIssuePattern,
    RISK_CRITICAL,
    RISK_HIGH,
)


REPORT_NOTE = (
    "Generated locally from BeeLine issue history. Predictions are heuristic and "
    "should be verified by maintenance staff."
)


def build_predictive_summary_text(
    risks: list[MachineRiskSummary],
    alerts: list[PredictiveMaintenanceAlert],
    recurring_patterns: list[RecurringIssuePattern],
) -> str:
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    high_or_critical = [risk for risk in risks if risk.risk_level in {RISK_HIGH, RISK_CRITICAL}]
    lines = [
        "BeeLine Predictive Maintenance Summary",
        f"Generated: {generated}",
        "",
        f"Total machines analyzed: {len(risks)}",
        f"High/Critical risk machines: {len(high_or_critical)}",
        f"Active predictive alerts: {len(alerts)}",
        f"Recurring patterns: {len(recurring_patterns)}",
        "",
        "Top risks:",
    ]
    if risks:
        for risk in sorted(risks, key=lambda item: item.risk_score, reverse=True)[:5]:
            lines.append(
                f"- Machine {risk.machine_number} ({risk.risk_level}, {risk.risk_score}): "
                f"{risk.predicted_problem}; action: {risk.suggested_action}"
            )
    else:
        lines.append("- Not enough issue history yet to generate strong predictions.")

    lines.append("")
    lines.append("Recurring patterns:")
    if recurring_patterns:
        for pattern in recurring_patterns[:5]:
            lines.append(
                f"- Machine {pattern.machine_number}: {pattern.display_label} "
                f"({pattern.occurrence_count} occurrences, last seen {pattern.last_seen_at or '-'})"
            )
    else:
        lines.append("- None detected.")

    lines.append("")
    lines.append("Suggested preparation/actions:")
    actions = [risk.suggested_action for risk in high_or_critical if risk.suggested_action]
    if actions:
        for action in tuple(dict.fromkeys(actions))[:5]:
            lines.append(f"- {action}")
    else:
        lines.append("- Continue normal checks.")
    lines.extend(("", REPORT_NOTE))
    return "\n".join(lines)


def build_machine_predictive_summary_text(
    machine_risk: MachineRiskSummary,
    patterns: list[RecurringIssuePattern],
    trend: list[MachineTrendPoint],
) -> str:
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    lines = [
        f"BeeLine Machine Predictive Summary: {machine_risk.machine_number}",
        f"Generated: {generated}",
        "",
        f"Machine: {machine_risk.machine_name or '-'}",
        f"Area/Cell: {_area_cell(machine_risk)}",
        f"Risk: {machine_risk.risk_level} ({machine_risk.risk_score})",
        f"Confidence: {machine_risk.confidence}",
        f"Predicted problem: {machine_risk.predicted_problem}",
        f"Predicted window: {machine_risk.predicted_window}",
        f"Suggested action: {machine_risk.suggested_action}",
        "",
        "Reasons:",
    ]
    for reason in machine_risk.risk_reasons:
        lines.append(f"- {reason}")

    lines.append("")
    lines.append("Recurring patterns:")
    if patterns:
        for pattern in patterns[:5]:
            lines.append(f"- {pattern.display_label}: {pattern.risk_note}")
    else:
        lines.append("- None detected.")

    lines.append("")
    lines.append("Trend:")
    if trend:
        for point in trend[-5:]:
            lines.append(
                f"- {point.period_label}: open {point.open_count}, resolved {point.resolved_count}, "
                f"Line Down {point.line_down_count}"
            )
    else:
        lines.append("- No trend data available.")
    lines.extend(("", REPORT_NOTE))
    return "\n".join(lines)


def _area_cell(risk: MachineRiskSummary) -> str:
    return " / ".join(part for part in (risk.area, risk.cell) if part) or "-"

