# BeeLine Predictive Maintenance

BeeLine predictive maintenance is a local analytics layer built from BeeLine's own SQLite issue history. It is intended to help maintenance teams notice risk, recurrence, and useful past fixes earlier.

It is heuristic, not a guaranteed prediction. It supports maintenance decisions and does not replace human judgment.

## Local-Only Privacy Rules

Predictive outputs are NDA-sensitive runtime data because they can reveal machine reliability, failure patterns, downtime indicators, maintenance practices, and operator activity.

BeeLine predictive maintenance does not use OpenAI, cloud AI, Microsoft Graph, external analytics APIs, telemetry, webhooks, or network calls. Risk scores, related issues, fix suggestions, charts, alerts, and reports are generated locally from SQLite.

Do not commit or paste into public issues, commits, or pull requests:

- generated predictive summaries or reports
- screenshots of real predictive dashboards
- real machine names, issue history, operator names, badge IDs, photos, attachments, or archive data
- predictive alert database contents

Generated summaries belong in the ignored local `exports/` folder.

## What It Does

The Predictive Maintenance page is visible after Admin login and shows:

- machine risk ranking
- predictive alerts
- recurring issue patterns
- global issue trends
- category breakdowns
- copy/export-ready plain text summaries

Machine Cell pages show a compact Maintenance Intelligence panel with risk level, risk score, confidence, predicted problem, suggested action, reasons, recurrence count, average time open, and last issue.

Issue Detail pages show related resolved issues and suggested fixes for active issues. Suggestions are based only on actual solution text from past resolved BeeLine records.

## Risk Scores

Risk scores are deterministic and explainable. The score is capped from `0` to `100`. Every machine risk summary includes human-readable reasons such as:

- open Line Down issue count
- open Non-Critical issue count
- issue activity in the last 7 and 30 days
- recent activity increase versus the prior window
- recurring categories or similar titles
- recent Line Down history
- increasing resolution time
- open issue age exceeding typical resolution history
- stability reductions for no recent issues

Risk levels:

- `Critical`: 85-100
- `High`: 65-84
- `Medium`: 40-64
- `Low`: 15-39
- `Stable`: 0-14
- `Unknown`: no history and no open issues

An open Line Down issue raises the risk floor to at least `High`. Multiple open Line Down issues raise it to `Critical`.

## Confidence

Confidence is based on how much issue history exists for the machine:

- `High`: 10 or more records
- `Medium`: 4-9 records
- `Low`: 1-3 records
- `Unknown`: 0 records

Low confidence does not mean the machine is safe. It means BeeLine has limited local history to analyze.

## Recurring Patterns

BeeLine detects recurrence with transparent grouping:

- same category repeating at least 3 times
- similar normalized issue title repeating at least 3 times
- recent windows such as 30 or 60 days
- longer-history category repetition

Each recurring pattern includes occurrence count, first/last seen timestamps, average gap in days when available, example titles, common solution snippets from resolved issues, and a short risk note.

Synthetic example:

`Machine DEMO-101: Sensor drift repeated 3 times. Common prior fix: Tightened sensor connector.`

## Related Issues

Related issue matching is local keyword and metadata scoring. It considers:

- title keyword overlap
- description keyword overlap
- same category
- same severity
- same machine
- recent resolved date
- solution availability

Common stop words are ignored. Same-machine alone is not enough to treat a resolved issue as related.

## Fix Suggestions

Fix suggestions are never invented. BeeLine only suggests text from actual past resolved issue solutions.

If no related resolved issues have solution text, BeeLine shows no fix suggestion. Each suggestion includes:

- title
- solution text snippet
- confidence
- supporting issue IDs
- caution: `Based on past resolved issues. Verify before applying.`

## Alerts and Dismissal

BeeLine can persist predictive alerts locally in SQLite when significant conditions appear, such as:

- a machine entering High or Critical risk
- a recurring pattern crossing the threshold
- Line Down recurrence

Alerts are deduplicated by machine, alert type, title, and risk level so they do not duplicate every refresh. Dismissed alerts stay dismissed locally. If risk worsens and creates a new risk level or new alert condition, BeeLine can create a new alert.

## Charts

Charts are Qt-native and local:

- Global Issue Trend shows bucketed issue counts.
- Category Breakdown shows issue counts by category.
- Risk Score Bar visualizes the current 0-100 machine risk score.

Charts handle empty data gracefully. More history improves chart usefulness.

## Configuration

Local runtime config supports:

```json
{
  "analytics": {
    "enabled": true,
    "risk_window_days": 30,
    "recurrence_window_days": 60,
    "high_risk_threshold": 65,
    "critical_risk_threshold": 85,
    "grouped_chart_periods": 8,
    "persist_predictive_alerts": true,
    "enable_fix_suggestions": true,
    "enable_related_issues": true
  }
}
```

Missing analytics config uses safe defaults. Partial config uses defaults for missing keys. Invalid values fall back to defaults instead of crashing the kiosk.

## Known Limitations

This is heuristic, not guaranteed prediction.

It depends on the quality and quantity of issue history. Vague titles, missing categories, or sparse solution text reduce usefulness.

It should support maintenance decisions, not replace human judgment.

Fix suggestions are based only on past BeeLine records and must be verified before applying.

This release does not use cloud AI or embeddings. Any future AI integration must be disabled by default, clearly marked future-only, and reviewed against BeeLine NDA rules.
