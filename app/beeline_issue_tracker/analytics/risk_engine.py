from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from beeline_issue_tracker.analytics.models import (
    MachineRiskInput,
    MachineRiskSummary,
    RecurringIssuePattern,
    RISK_CRITICAL,
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    RISK_STABLE,
    RISK_UNKNOWN,
)
from beeline_issue_tracker.analytics.text_match import normalize_text, tokenize
from beeline_issue_tracker.domain import LINE_DOWN, NON_CRITICAL, Issue, ResolvedIssue


@dataclass(frozen=True)
class ScoreContribution:
    points: int
    reason: str


def build_machine_risk_summary(
    risk_input: MachineRiskInput,
    *,
    now: datetime | None = None,
) -> MachineRiskSummary:
    now = _coerce_now(now)
    active = tuple(issue for issue in risk_input.active_issues if isinstance(issue, Issue))
    resolved = tuple(issue for issue in risk_input.resolved_issues if isinstance(issue, ResolvedIssue))
    all_issues = active + resolved

    line_down_open_count = sum(1 for issue in active if issue.severity == LINE_DOWN)
    non_critical_open_count = sum(1 for issue in active if issue.severity == NON_CRITICAL)
    recent_7 = [issue for issue in all_issues if _within_days(_issue_created_at(issue), now, 7)]
    recent_30 = [issue for issue in all_issues if _within_days(_issue_created_at(issue), now, 30)]
    previous_30 = [
        issue
        for issue in all_issues
        if _between_days(_issue_created_at(issue), now, older_than_days=30, newer_than_days=60)
    ]
    recent_line_down = [issue for issue in recent_30 if issue.severity == LINE_DOWN]
    line_down_14 = [issue for issue in all_issues if issue.severity == LINE_DOWN and _within_days(_event_time(issue), now, 14)]
    line_down_60 = [issue for issue in all_issues if issue.severity == LINE_DOWN and _within_days(_event_time(issue), now, 60)]
    average_minutes = _average_resolution_minutes(resolved)
    patterns_30 = detect_recurring_patterns_for_machine(
        risk_input.machine_number,
        all_issues,
        now=now,
        days=30,
    )
    patterns_60 = detect_recurring_patterns_for_machine(
        risk_input.machine_number,
        all_issues,
        now=now,
        days=60,
    )
    patterns_all = detect_recurring_patterns_for_machine(
        risk_input.machine_number,
        all_issues,
        now=now,
        days=None,
    )

    contributions: list[ScoreContribution] = []
    if line_down_open_count:
        points = min(55, line_down_open_count * 35)
        contributions.append(ScoreContribution(points, f"{line_down_open_count} open Line Down issue(s): +{points}"))
    if non_critical_open_count:
        points = min(30, non_critical_open_count * 12)
        contributions.append(ScoreContribution(points, f"{non_critical_open_count} open Non-Critical issue(s): +{points}"))
    if recent_7:
        points = min(25, len(recent_7) * 5)
        contributions.append(ScoreContribution(points, f"{len(recent_7)} issue(s) in the last 7 days: +{points}"))
    if recent_30:
        points = min(20, len(recent_30) * 3)
        contributions.append(ScoreContribution(points, f"{len(recent_30)} issue(s) in the last 30 days: +{points}"))
    if recent_30 and len(recent_30) > len(previous_30):
        contributions.append(
            ScoreContribution(
                10,
                f"Recent activity increased versus the prior 30-day window ({len(recent_30)} vs {len(previous_30)}): +10",
            )
        )
    if _has_category_recurrence(patterns_30):
        label = _top_pattern_label(patterns_30)
        contributions.append(ScoreContribution(20, f"Recurring category in the last 30 days ({label}): +20"))
    if _has_title_recurrence(patterns_60):
        label = _top_pattern_label(patterns_60)
        contributions.append(ScoreContribution(15, f"Similar issue title repeated in the last 60 days ({label}): +15"))
    if _has_category_recurrence(patterns_all):
        label = _top_pattern_label(patterns_all)
        contributions.append(ScoreContribution(10, f"Longer-history category recurrence ({label}): +10"))
    if line_down_14:
        contributions.append(ScoreContribution(12, "Line Down occurred in the last 14 days: +12"))
    if len(line_down_60) >= 2:
        contributions.append(ScoreContribution(8, f"{len(line_down_60)} Line Down issue(s) in the last 60 days: +8"))
    if _resolution_time_is_increasing(resolved):
        contributions.append(ScoreContribution(10, "Average resolution time is increasing: +10"))
    if _open_age_exceeds_typical(active, resolved, now):
        contributions.append(ScoreContribution(8, "Current open issue age exceeds typical history: +8"))
    if all_issues and not recent_30:
        contributions.append(ScoreContribution(-10, "No issues in the last 30 days: -10"))
    if all_issues and not [issue for issue in all_issues if _within_days(_event_time(issue), now, 60)]:
        contributions.append(ScoreContribution(-15, "No issues in the last 60 days: -15"))

    raw_score = sum(item.points for item in contributions)
    if line_down_open_count >= 2 and raw_score < 85:
        contributions.append(ScoreContribution(85 - raw_score, "Multiple open Line Down issues raise risk floor to Critical."))
        raw_score = 85
    elif line_down_open_count and raw_score < 65:
        contributions.append(ScoreContribution(65 - raw_score, "Open Line Down raises risk floor to High."))
        raw_score = 65
    score = max(0, min(100, raw_score))

    historical_count = len(all_issues)
    risk_level = _risk_level(score, historical_count=historical_count, open_issue_count=len(active))
    confidence = _confidence(historical_count)
    predicted_problem = _predicted_problem(active, resolved, patterns_60)
    suggested_action = _suggested_action(active, resolved, patterns_60)
    predicted_window = _predicted_window(risk_level, line_down_open_count=line_down_open_count, has_recent_recurrence=bool(patterns_60))
    last_issue_at = _latest_issue_time(all_issues)
    reasons = tuple(item.reason for item in contributions) or ("No issue history recorded for this machine.",)

    return MachineRiskSummary(
        machine_number=risk_input.machine_number,
        machine_name=risk_input.machine_name,
        area=risk_input.area,
        cell=risk_input.cell,
        risk_score=score,
        risk_level=risk_level,
        risk_reasons=reasons,
        open_issue_count=len(active),
        line_down_open_count=line_down_open_count,
        non_critical_open_count=non_critical_open_count,
        recent_issue_count=len(recent_30),
        recent_line_down_count=len(recent_line_down),
        recurring_issue_count=len(patterns_60),
        average_time_open_minutes=average_minutes,
        last_issue_at=last_issue_at,
        predicted_problem=predicted_problem,
        suggested_action=suggested_action,
        predicted_window=predicted_window,
        confidence=confidence,
    )


def detect_recurring_patterns_for_machine(
    machine_number: str,
    issues: tuple[Issue | ResolvedIssue, ...] | list[Issue | ResolvedIssue],
    *,
    now: datetime | None = None,
    days: int | None = 60,
) -> list[RecurringIssuePattern]:
    now = _coerce_now(now)
    scoped = [issue for issue in issues if issue.machine_number == machine_number]
    if days is not None:
        scoped = [issue for issue in scoped if _within_days(_event_time(issue), now, days)]
    patterns: list[RecurringIssuePattern] = []
    patterns.extend(_patterns_from_group("category", scoped, minimum=3))
    patterns.extend(_patterns_from_group("title", scoped, minimum=3))
    patterns.sort(key=lambda pattern: (pattern.occurrence_count, pattern.last_seen_at), reverse=True)
    return patterns


def _patterns_from_group(
    pattern_type: str,
    issues: list[Issue | ResolvedIssue],
    *,
    minimum: int,
) -> list[RecurringIssuePattern]:
    grouped: dict[str, list[Issue | ResolvedIssue]] = defaultdict(list)
    labels: dict[str, str] = {}
    for issue in issues:
        if pattern_type == "category":
            key = normalize_text(issue.category)
            label = issue.category.strip()
        else:
            key = " ".join(sorted(tokenize(issue.title)))
            label = issue.title.strip()
        if not key or not label:
            continue
        grouped[key].append(issue)
        labels.setdefault(key, label)

    patterns: list[RecurringIssuePattern] = []
    for key, group in grouped.items():
        if len(group) < minimum:
            continue
        ordered = sorted(group, key=lambda issue: _event_time(issue) or datetime.min.replace(tzinfo=timezone.utc))
        category_counts = Counter(issue.category for issue in group if issue.category.strip())
        severity_counts = Counter(issue.severity for issue in group if issue.severity.strip())
        example_titles = tuple(dict.fromkeys(issue.title for issue in ordered if issue.title.strip()))[:3]
        common_solutions = tuple(
            solution
            for solution, _count in Counter(
                _solution_preview(issue.solution)
                for issue in group
                if isinstance(issue, ResolvedIssue) and issue.solution.strip()
            ).most_common(3)
            if solution
        )
        first_seen = _iso_or_empty(_event_time(ordered[0]))
        last_seen = _iso_or_empty(_event_time(ordered[-1]))
        average_days = _average_gap_days(ordered)
        display_label = labels[key]
        risk_note = f"{display_label} has repeated {len(group)} times."
        patterns.append(
            RecurringIssuePattern(
                machine_number=ordered[0].machine_number,
                pattern_key=f"{pattern_type}:{key}",
                display_label=display_label,
                category=category_counts.most_common(1)[0][0] if category_counts else "",
                severity=severity_counts.most_common(1)[0][0] if severity_counts else "",
                occurrence_count=len(group),
                first_seen_at=first_seen,
                last_seen_at=last_seen,
                average_time_between_days=average_days,
                example_titles=example_titles,
                common_solutions=common_solutions,
                risk_note=risk_note,
            )
        )
    return patterns


def _risk_level(score: int, *, historical_count: int, open_issue_count: int) -> str:
    if historical_count == 0 and open_issue_count == 0:
        return RISK_UNKNOWN
    if score >= 85:
        return RISK_CRITICAL
    if score >= 65:
        return RISK_HIGH
    if score >= 40:
        return RISK_MEDIUM
    if score >= 15:
        return RISK_LOW
    return RISK_STABLE


def _confidence(historical_count: int) -> str:
    if historical_count >= 10:
        return "High"
    if historical_count >= 4:
        return "Medium"
    if historical_count >= 1:
        return "Low"
    return "Unknown"


def _predicted_window(risk_level: str, *, line_down_open_count: int, has_recent_recurrence: bool) -> str:
    if line_down_open_count:
        return "Now / immediate"
    if risk_level in {RISK_HIGH, RISK_CRITICAL} and has_recent_recurrence:
        return "Next 1-3 days"
    if risk_level == RISK_MEDIUM and has_recent_recurrence:
        return "Next 1-2 weeks"
    if risk_level == RISK_LOW:
        return "Monitor"
    return "No current warning"


def _predicted_problem(
    active: tuple[Issue, ...],
    resolved: tuple[ResolvedIssue, ...],
    patterns: list[RecurringIssuePattern],
) -> str:
    open_line_down = next((issue for issue in active if issue.severity == LINE_DOWN), None)
    if open_line_down is not None:
        return open_line_down.title
    if patterns:
        title_pattern = next((pattern for pattern in patterns if pattern.pattern_key.startswith("title:")), None)
        return (title_pattern or patterns[0]).display_label
    repeated = _most_recent_repeated_resolved(resolved)
    if repeated:
        return repeated
    return "No clear recurring problem"


def _suggested_action(
    active: tuple[Issue, ...],
    resolved: tuple[ResolvedIssue, ...],
    patterns: list[RecurringIssuePattern],
) -> str:
    if any(issue.severity == LINE_DOWN for issue in active):
        return "Review current Line Down issue immediately."
    if patterns:
        pattern = patterns[0]
        if pattern.common_solutions:
            return f"Prepare parts/tools for {pattern.common_solutions[0]}."
        category = pattern.category or pattern.display_label
        return f"Inspect recurring {category} problems."
    if _most_recent_repeated_resolved(resolved):
        return "Monitor for repeat symptoms."
    return "No action needed beyond normal checks."


def _has_category_recurrence(patterns: list[RecurringIssuePattern]) -> bool:
    return any(pattern.pattern_key.startswith("category:") for pattern in patterns)


def _has_title_recurrence(patterns: list[RecurringIssuePattern]) -> bool:
    return any(pattern.pattern_key.startswith("title:") for pattern in patterns)


def _top_pattern_label(patterns: list[RecurringIssuePattern]) -> str:
    return patterns[0].display_label if patterns else "repeat pattern"


def _most_recent_repeated_resolved(resolved: tuple[ResolvedIssue, ...]) -> str:
    title_counts = Counter(normalize_text(issue.title) for issue in resolved if issue.title.strip())
    repeated_keys = {key for key, count in title_counts.items() if key and count >= 2}
    if not repeated_keys:
        return ""
    recent = sorted(resolved, key=lambda issue: _event_time(issue) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    for issue in recent:
        if normalize_text(issue.title) in repeated_keys:
            return issue.title
    return ""


def _average_resolution_minutes(resolved: tuple[ResolvedIssue, ...]) -> int | None:
    samples = _resolution_minutes(resolved)
    if not samples:
        return None
    return int(sum(samples) / len(samples))


def _resolution_time_is_increasing(resolved: tuple[ResolvedIssue, ...]) -> bool:
    if len(resolved) < 4:
        return False
    ordered = sorted(resolved, key=lambda issue: _event_time(issue) or datetime.min.replace(tzinfo=timezone.utc))
    midpoint = len(ordered) // 2
    older = _resolution_minutes(tuple(ordered[:midpoint]))
    newer = _resolution_minutes(tuple(ordered[midpoint:]))
    if not older or not newer:
        return False
    older_avg = sum(older) / len(older)
    newer_avg = sum(newer) / len(newer)
    return newer_avg > older_avg * 1.25 and newer_avg - older_avg >= 15


def _open_age_exceeds_typical(active: tuple[Issue, ...], resolved: tuple[ResolvedIssue, ...], now: datetime) -> bool:
    if not active or not resolved:
        return False
    category_samples: dict[str, list[int]] = defaultdict(list)
    for issue in resolved:
        created = _parse_iso(issue.created_at)
        resolved_at = _parse_iso(issue.resolved_at)
        if created is None or resolved_at is None:
            continue
        category_samples[normalize_text(issue.category)].append(max(0, int((resolved_at - created).total_seconds() // 60)))
    for issue in active:
        key = normalize_text(issue.category)
        samples = category_samples.get(key, [])
        if not samples:
            continue
        typical = sum(samples) / len(samples)
        created = _parse_iso(issue.created_at)
        if created is None:
            continue
        age = max(0, int((now - created).total_seconds() // 60))
        if age > typical * 1.5 and age - typical >= 30:
            return True
    return False


def _resolution_minutes(resolved: tuple[ResolvedIssue, ...]) -> list[int]:
    samples: list[int] = []
    for issue in resolved:
        created = _parse_iso(issue.created_at)
        resolved_at = _parse_iso(issue.resolved_at)
        if created is None or resolved_at is None:
            continue
        samples.append(max(0, int((resolved_at - created).total_seconds() // 60)))
    return samples


def _average_gap_days(issues: list[Issue | ResolvedIssue]) -> float | None:
    if len(issues) < 2:
        return None
    times = [_event_time(issue) for issue in issues]
    times = [time for time in times if time is not None]
    if len(times) < 2:
        return None
    gaps = []
    for left, right in zip(times, times[1:]):
        gaps.append(max(0.0, (right - left).total_seconds() / 86400))
    if not gaps:
        return None
    return round(sum(gaps) / len(gaps), 1)


def _latest_issue_time(issues: tuple[Issue | ResolvedIssue, ...]) -> str:
    times = [_event_time(issue) for issue in issues]
    times = [time for time in times if time is not None]
    if not times:
        return ""
    return max(times).isoformat()


def _issue_created_at(issue: Issue | ResolvedIssue) -> datetime | None:
    return _parse_iso(issue.created_at)


def _event_time(issue: Issue | ResolvedIssue) -> datetime | None:
    if isinstance(issue, ResolvedIssue):
        return _parse_iso(issue.resolved_at) or _parse_iso(issue.created_at)
    return _parse_iso(issue.created_at)


def _within_days(value: datetime | None, now: datetime, days: int) -> bool:
    if value is None:
        return False
    return now - timedelta(days=days) <= value <= now


def _between_days(value: datetime | None, now: datetime, *, older_than_days: int, newer_than_days: int) -> bool:
    if value is None:
        return False
    return now - timedelta(days=newer_than_days) <= value < now - timedelta(days=older_than_days)


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_or_empty(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _solution_preview(value: str) -> str:
    text = " ".join((value or "").split())
    if len(text) <= 90:
        return text
    return text[:87].rstrip() + "..."
