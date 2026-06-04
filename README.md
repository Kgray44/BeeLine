# BeeLine Issue Tracker

BeeLine is a plant-floor kiosk issue tracker MVP with a Hive Dashboard, Machine Cell pages, issue reporting, SQLite runtime storage, and openpyxl-based Excel archive writing.

This repository is prepared for GitHub with application code and safe, empty template files only. Real plant runtime data belongs in ignored local folders.

BeeLine now includes a local-only predictive maintenance layer. It analyzes the local SQLite issue history with deterministic heuristics for risk scores, recurring patterns, related resolved issues, fix suggestions, charts, and plain-text summaries. It does not send machine data, issue history, operator names, archive data, attachments, or predictive outputs to OpenAI, cloud AI, external analytics APIs, webhooks, or telemetry.

## Run BeeLine

```powershell
python -m pip install -r requirements.txt
python run_beeline.py
```

Startup and archive commands:

```powershell
python run_beeline.py --check
python run_beeline.py --archive-status
python run_beeline.py --repair-archive
```

`--check` initializes safe runtime files and validates startup without opening the UI. It does not open, scan, save, refresh, or rebuild the Excel archive. `--archive-status` is an explicit archive inspection command that can open the workbook read-only to print workbook sheets, row count, latest archived issue, and SQLite archive status counts. `--repair-archive` rebuilds the readable grouped Excel view on demand.

## Runtime Files

On first launch, BeeLine copies safe templates into local runtime locations if runtime files are missing:

- `templates/beeline_config.template.json` -> `config/beeline_config.json`
- `templates/beeline.template.sqlite` -> `data/beeline.sqlite`
- `templates/beeline_archive.template.xlsx` -> `archive/beeline_resolved_archive.xlsx`

You can initialize or regenerate safe templates during development:

```powershell
python scripts\initialize_runtime_files.py --create-templates
python scripts\initialize_runtime_files.py --force-templates
```

Committed templates are intentionally empty and sanitized. The config template has an empty `machines` list and disabled placeholder roles. The SQLite template has schema only. The Excel template has sheets and headers only.

## Plant Configuration

Machine data is not hardcoded in the app. Add local machine configuration to `config/beeline_config.json` on the target machine.

Do not commit:

- real machine data
- real employee/operator names
- badge IDs
- issue history
- real SQLite data
- real Excel archive data
- screenshots, captures, photos, exports, logs, backups, or local attachments
- secrets, credentials, tokens, private links, `.env` files, or non-approved private branding assets
- generated predictive maintenance summaries, reports, alert data, or screenshots of real predictive dashboards

## Roles and PINs

BeeLine starts in Viewer mode. Any user can report a new issue. Viewer can inspect machines, active issues, resolved history, and dashboard issue search. Technician can resolve issues. Admin can open Predictive Maintenance, Settings, manage app-level preferences, and log out.

Local config can define roles:

```json
{
  "roles": {
    "viewer": {"enabled": false, "pin_hash": ""},
    "technician": {"enabled": false, "pin_hash": ""},
    "admin": {"enabled": false, "pin_hash": ""}
  }
}
```

PIN hashes use PBKDF2-SHA256 and should be generated locally. Do not commit production PIN hashes. Admin login requires an enabled admin role with a hashed PIN. If no technician PIN is configured, local technician mode remains available for MVP use.

## Operator Workflow

The Hive Dashboard shows responsive machine cards when the search box is empty. When search text is entered, Quick Search is the default and searches SQLite only: open issues and recent resolved/archive cache records. Deep Search is explicit; it shows Quick Search results first, then searches the full Excel archive in the background using read-only/data-only workbook access. Results are labeled as Open Issue, Recent Archive, or Excel Archive.

Use `View All Open Issues` to open the global Open Issues page. That page shows active issues across all machines with search, severity, machine, area/cell, sort, and latest filters.

Admins can use `Predictive Maintenance` to open the global predictive maintenance page. It ranks machines by explainable local risk score, shows active predictive alerts, recurring patterns, a global trend chart, and category breakdown. Summaries can be copied or exported locally to the ignored `exports/` folder.

Machine Cell pages prioritize machine status, maintenance intelligence, active issues, and resolved issues. `Report Problem` appears with the Active/Open Issues section. Troubleshooting Memory appears lower on the page after the issue tables. Issue rows can be opened with the `Open` button, double-click, or Enter on the selected row.

Machine Details is the central detailed machine view. It includes machine overview metadata, current status, predictive maintenance, issue history, trend summaries, and troubleshooting memory. Machine page buttons route to this page and focus the predictive, trends, or issue-history section.

Admins can open Settings from the bottom-right login/status area. Theme mode, runtime paths, dashboard defaults, display counts, category dropdown values, and privacy-related path display settings are visible there. The main UI avoids showing raw local/UNC paths by default.

Issue details open as a full page inside BeeLine, not a small modal. The detail page supports active and resolved issues, Back, Go to Machine, metadata, attachments, related resolved issues, local fix suggestions based only on past resolved BeeLine records, and Resolve Issue for active issues. Resolving from the detail page navigates to the resolved issue detail page while the Excel archive worker runs.

See [`docs/PREDICTIVE_MAINTENANCE.md`](docs/PREDICTIVE_MAINTENANCE.md) for risk scoring, confidence levels, recurrence rules, alert dismissal behavior, chart interpretation, and predictive privacy requirements.

## Archive Behavior

Resolved issues are cached in SQLite and appended to the raw Excel sheet in the background. BeeLine prevents duplicate raw archive rows by cache ID. If Excel archive writing fails, the resolved issue remains in SQLite with `failed` archive status and an error message; it does not return to the open-issue list. Admin Settings shows SQLite-based archive health and can retry failed archive writes explicitly.

Recent resolved issues remain in SQLite for fast Quick Search. Cache trimming only runs after successful archive handling or explicit maintenance and never removes `pending`, `failed`, or `retry_pending` archive writes. Default retention keeps records from the last 180 days, at least the latest 1,000 archived records, and at least 25 archived records per machine.

For small workbooks, the readable `Resolved_By_Date` sheet refreshes immediately. For larger workbooks, BeeLine appends the raw row and defers grouped-view rebuilds to avoid slow kiosk writes. Run:

```powershell
python run_beeline.py --repair-archive
```

to rebuild the grouped view.

## Attachments

BeeLine includes a local-only attachment data model. Attachment paths are stored in SQLite only; photos/files should live under ignored local runtime storage such as `data/attachments/`. No sample photos or real attachments belong in Git.

## Safety Check

Run this before committing or pushing:

```powershell
python scripts\verify_safe_for_github.py
```

The safety check fails on runtime databases, runtime archives, logs, backups, generated media, secret-like files, unsafe filenames, non-empty templates, and likely sensitive text values in tracked/staged text files.

## Tests and CI

Run local validation:

```powershell
python -m unittest discover -s tests
python scripts\smoke_test.py
python run_beeline.py --check
python scripts\verify_safe_for_github.py
```

Create a large fake-only performance database without touching real runtime data:

```powershell
python scripts\perf_seed.py
python scripts\perf_seed.py --force
```

The default output is `data/beeline_perf.sqlite`. The script creates demo machine numbers, fake users, fake issue text, 5,000 active issues, and 50,000 resolved issues. It does not create or read the Excel archive.

GitHub Actions runs the same validation on `windows-latest` with Python 3.12 for push and pull request events.

## Branding

BeeLine uses one shared header/logo location across major pages.

- Approved logo path: `assets/branding/nolato_logo.png`
- Commit-safe fallback: `assets/branding/nolato_logo_placeholder.png`

The shared header renders the logo directly on the normal page background without a separate logo box. If a local logo image has its own white rectangle baked into the file, replace it with a transparent PNG/SVG-style asset.

Set `BEELINE_LOGO_PATH` for a local logo override without changing committed assets.
