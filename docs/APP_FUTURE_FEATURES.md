# BeeLine Future App

`app_future/` is an isolated copy of the BeeLine app for the next major feature set. The production app under `app/` remains the current runtime path. Use the future launcher when testing this version:

```powershell
python run_beeline_future.py --check
python run_beeline_future.py
```

For Raspberry Pi kiosk mode:

```powershell
$env:BEELINE_PI_MODE = "1"
python run_beeline_future.py
```

## Features Added

- Priority Board: lazy-loaded, SQLite-only active issue ranking capped at 50 rows.
- Suggested Fixes, Related History, and Recurring Patterns on Issue Detail using the existing predictive service and local resolved history.
- Issue aging flags: New, Aging, Stale, and Critical Aging across Priority Board, Open Issues, machine issue lists, and Issue Detail.
- Shift Handoff: on-demand summaries for Last 8 Hours, Last 12 Hours, or Today with copy and TXT export.
- Known Fixes on Machine Info: machine-level repeated fixes grouped from resolved SQLite history, capped at 10.
- Smart Issue Intake: optional What Changed and Tried Already fields plus debounced local suggestions capped at 5.
- Admin Data Health in Settings: SQLite/path-only default health, explicit Excel check/repair buttons, archive retry, and recent performance guardrails.
- Machine Config Manager in Settings: add/update/deactivate local machines with timestamped config backups and restart-to-apply messaging.
- Raspberry Pi mode via `BEELINE_PI_MODE=1`: reduced motion and special effects disabled by default.

## Intentionally Reused

The future app does not duplicate systems that already existed. It reuses the current SQLite database layer, archive worker/retry logic, roles, Machine Info, Issue Detail, quick/deep search, predictive service, related matching, fix suggestion logic, page transitions, settings, and trend data.

## Performance Rules

- Normal pages use SQLite only.
- Excel is opened only when an admin explicitly clicks Check Excel Archive or Repair Archive, or when Deep Search/archive CLI actions are requested.
- New pages load only on navigation, manual refresh, or after issue save/resolve.
- Result limits are enforced in queries and UI loaders.
- Typing-based search/suggestion debounce is 400 ms.
- Heavy page loads use existing background worker pools.
- Performance samples are kept in a small in-memory ring buffer.

## Known Limitations

- Attachment intake was not added because the current attachment model attaches files after an issue exists; the future form avoids holding unsaved file references.
- Machine config edits write the local config and require restarting BeeLine Future to apply safely.
- The Shift Handoff TXT export writes to the ignored `exports/` folder; PDF export was intentionally not added.
