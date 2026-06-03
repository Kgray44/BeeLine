from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from beeline_issue_tracker.analytics.models import FixSuggestion, RelatedIssueMatch
from beeline_issue_tracker.domain import Issue, ResolvedIssue


STOP_WORDS = {
    "the",
    "and",
    "or",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "it",
    "this",
    "that",
    "not",
    "machine",
    "issue",
    "problem",
}


def normalize_text(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.casefold())
    return " ".join(words)


def tokenize(text: str) -> set[str]:
    return {
        token
        for token in normalize_text(text).split()
        if token and token not in STOP_WORDS and len(token) >= 3
    }


def keyword_overlap_score(a: str, b: str) -> int:
    left = tokenize(a)
    right = tokenize(b)
    if not left or not right:
        return 0
    overlap = left & right
    if not overlap:
        return 0
    ratio = len(overlap) / max(1, min(len(left), len(right)))
    return min(40, int(round(ratio * 40)))


def category_match_score(current_category: str, candidate_category: str) -> int:
    if not current_category.strip() or not candidate_category.strip():
        return 0
    return 15 if current_category.strip().casefold() == candidate_category.strip().casefold() else 0


def severity_match_score(current_severity: str, candidate_severity: str) -> int:
    if not current_severity.strip() or not candidate_severity.strip():
        return 0
    return 5 if current_severity.strip().casefold() == candidate_severity.strip().casefold() else 0


def machine_match_score(current_machine: str, candidate_machine: str) -> int:
    if not current_machine.strip() or not candidate_machine.strip():
        return 0
    return 15 if current_machine.strip().casefold() == candidate_machine.strip().casefold() else 0


def find_related_resolved_issues(
    current_issue: Issue,
    resolved_history: list[ResolvedIssue] | tuple[ResolvedIssue, ...],
    limit: int = 5,
) -> list[RelatedIssueMatch]:
    matches: list[RelatedIssueMatch] = []
    current_title_tokens = tokenize(current_issue.title)
    current_desc_tokens = tokenize(current_issue.description)

    for candidate in resolved_history:
        score = 0
        reasons: list[str] = []

        title_score = keyword_overlap_score(current_issue.title, candidate.title)
        if title_score:
            score += title_score
            similar = sorted(current_title_tokens & tokenize(candidate.title))[:5]
            reasons.append(f"Similar title keywords: {', '.join(similar)}")

        description_score = min(25, keyword_overlap_score(current_issue.description, candidate.description))
        if description_score:
            score += description_score
            overlap = current_desc_tokens & tokenize(candidate.description)
            if overlap:
                reasons.append("Similar problem description")

        category_score = category_match_score(current_issue.category, candidate.category)
        if category_score:
            score += category_score
            reasons.append("Same category")

        severity_score = severity_match_score(current_issue.severity, candidate.severity)
        if severity_score:
            score += severity_score
            reasons.append("Same severity")

        same_machine_score = machine_match_score(current_issue.machine_number, candidate.machine_number)
        if same_machine_score:
            score += same_machine_score
            reasons.append("Same machine")

        recent_score = _recentness_score(candidate.resolved_at)
        if recent_score:
            score += recent_score
            reasons.append("Recent resolved issue")

        if candidate.solution.strip():
            score += 5
            reasons.append("Resolved solution available")

        if score >= 20 and _has_meaningful_problem_overlap(current_issue, candidate):
            matches.append(
                RelatedIssueMatch(
                    issue_id=candidate.id,
                    original_issue_id=candidate.original_issue_id,
                    machine_number=candidate.machine_number,
                    title=candidate.title,
                    description_preview=_preview(candidate.description),
                    solution_preview=_preview(candidate.solution),
                    severity=candidate.severity,
                    category=candidate.category,
                    created_at=candidate.created_at,
                    resolved_at=candidate.resolved_at,
                    match_score=min(100, score),
                    match_reasons=tuple(dict.fromkeys(reasons)),
                )
            )

    matches.sort(key=lambda item: (item.match_score, item.resolved_at or "", item.issue_id), reverse=True)
    return matches[: max(0, int(limit))]


def build_fix_suggestions(
    related_matches: list[RelatedIssueMatch] | tuple[RelatedIssueMatch, ...],
    resolved_history: list[ResolvedIssue] | tuple[ResolvedIssue, ...],
    limit: int = 5,
) -> list[FixSuggestion]:
    related_ids = {match.issue_id for match in related_matches}
    if not related_ids:
        return []

    by_id = {issue.id: issue for issue in resolved_history}
    candidates = [by_id[issue_id] for issue_id in related_ids if issue_id in by_id and by_id[issue_id].solution.strip()]
    if not candidates:
        return []

    grouped: dict[str, list[ResolvedIssue]] = {}
    labels: dict[str, str] = {}
    for issue in candidates:
        key = normalize_text(issue.solution)
        if not key:
            continue
        grouped.setdefault(key, []).append(issue)
        labels.setdefault(key, issue.solution.strip())

    ordered = sorted(
        grouped.items(),
        key=lambda item: (len(item[1]), max(_timestamp(issue.resolved_at) for issue in item[1])),
        reverse=True,
    )

    suggestions: list[FixSuggestion] = []
    for key, issues in ordered[: max(0, int(limit))]:
        solution = labels[key]
        categories = Counter(issue.category for issue in issues if issue.category.strip())
        category_note = categories.most_common(1)[0][0] if categories else "related issue"
        confidence = _confidence(len(issues))
        suggestions.append(
            FixSuggestion(
                title=f"Past fix for {category_note}",
                suggestion=_preview(solution, max_length=220),
                confidence=confidence,
                based_on_count=len(issues),
                supporting_issue_ids=tuple(sorted(issue.id for issue in issues)),
                caution="Based on past resolved issues. Verify before applying.",
            )
        )
    return suggestions


def _has_meaningful_problem_overlap(current_issue: Issue, candidate: ResolvedIssue) -> bool:
    if tokenize(current_issue.title) & tokenize(candidate.title):
        return True
    if tokenize(current_issue.description) & tokenize(candidate.description):
        return True
    if current_issue.category and current_issue.category.casefold() == candidate.category.casefold():
        return True
    return False


def _recentness_score(value: str) -> int:
    parsed = _parse_iso(value)
    if parsed is None:
        return 0
    age_days = (datetime.now(timezone.utc) - parsed).days
    if age_days <= 30:
        return 5
    if age_days <= 90:
        return 3
    return 0


def _confidence(count: int) -> str:
    if count >= 3:
        return "High"
    if count == 2:
        return "Medium"
    return "Low"


def _preview(value: str, max_length: int = 140) -> str:
    text = " ".join((value or "").split())
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)].rstrip() + "..."


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamp(value: str) -> float:
    parsed = _parse_iso(value)
    return parsed.timestamp() if parsed else 0.0
