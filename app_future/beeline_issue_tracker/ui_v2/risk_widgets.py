from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from beeline_issue_tracker.ui_v2.theme import repolish


_RISK_SCORE_PATTERN = re.compile(r"(?P<impact>[+-]\d+)\b")


@dataclass(frozen=True)
class ParsedRiskReason:
    text: str
    impact: int | None = None


def parse_risk_reasons(
    reasons: str | Iterable[str],
    *,
    sort_by_impact: bool = True,
) -> list[ParsedRiskReason]:
    parts: list[str] = []
    if isinstance(reasons, str):
        sources = (reasons,)
    else:
        sources = tuple(str(reason) for reason in reasons)
    for source in sources:
        parts.extend(part.strip() for part in source.split("|") if part.strip())

    parsed: list[ParsedRiskReason] = []
    for part in parts:
        matches = list(_RISK_SCORE_PATTERN.finditer(part))
        if not matches:
            parsed.append(ParsedRiskReason(text=part))
            continue
        match = matches[-1]
        impact = int(match.group("impact"))
        text = f"{part[:match.start()]}{part[match.end():]}".strip().rstrip(":- ")
        parsed.append(ParsedRiskReason(text=text or part, impact=impact))

    if not sort_by_impact or not any(reason.impact is not None for reason in parsed):
        return parsed

    indexed = enumerate(parsed)
    return [
        reason
        for _index, reason in sorted(
            indexed,
            key=lambda item: (item[1].impact is None, -(item[1].impact or 0), item[0]),
        )
    ]


def risk_impact_state(impact: int | None) -> str:
    if impact is None:
        return "low"
    if impact >= 25:
        return "high"
    if impact >= 10:
        return "medium"
    return "low"


def impact_text(impact: int) -> str:
    return f"+{impact}" if impact > 0 else str(impact)


def create_risk_reason_row(
    reason: ParsedRiskReason,
    *,
    object_name: str = "riskReasonRow",
) -> QFrame:
    row = QFrame()
    row.setObjectName(object_name)
    impact_state = risk_impact_state(reason.impact)
    row.setProperty("impactState", impact_state)
    row.setToolTip(reason.text)

    layout = QHBoxLayout(row)
    layout.setContentsMargins(12, 9, 12, 9)
    layout.setSpacing(10)
    if reason.impact is not None:
        score = QLabel(impact_text(reason.impact))
        score.setObjectName("reasonScoreBadge")
        score.setProperty("impactState", impact_state)
        score.setMinimumWidth(62)
        score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(score)

    text = QLabel(reason.text or "No risk reason available")
    text.setWordWrap(True)
    text.setToolTip(reason.text)
    layout.addWidget(text, 1)
    repolish(row)
    return row
