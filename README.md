# BeeLine Issue Tracker

BeeLine is a plant-floor kiosk issue tracker MVP with a Hive Dashboard, Machine Cell pages, issue reporting, SQLite runtime storage, and openpyxl-based Excel archive writing.

This repository is prepared for GitHub with application code and safe, empty template files only. Real plant runtime data belongs in ignored local folders.

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

`--check` initializes safe runtime files and validates startup without opening the UI. It does not force a full Excel grouped-view refresh. `--archive-status` prints the archive path, workbook sheets, row count, latest archived issue, and SQLite archive status counts. `--repair-archive` rebuilds the readable grouped Excel view on demand.

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
- secrets, credentials, tokens, private links, `.env` files, or approved/private branding assets

## Roles and PINs

Role security is optional. If no technician/admin role is enabled with a PIN hash, BeeLine keeps the current no-PIN MVP behavior.

Local config can define roles:

```json
{
  "roles": {
    "operator": {"enabled": false, "pin_hash": ""},
    "technician": {"enabled": false, "pin_hash": ""},
    "admin": {"enabled": false, "pin_hash": ""}
  }
}
```

PIN hashes use PBKDF2-SHA256 and should be generated locally. Do not commit production PIN hashes. When technician/admin role security is enabled, resolving an issue prompts for an authorized PIN.

## Operator Workflow

The Hive Dashboard supports machine search, Plant Layout/Severity/Open Issues/Machine A-Z/Machine Z-A sorting, area/cell filters when values exist, responsive machine cards, and summary pills. Machine A-Z/Z-A sorts by machine number.

Use `View All Open Issues` to open the global Open Issues page. That page shows active issues across all machines with search, severity, machine, area/cell, sort, and latest filters.

Machine Cell pages include `Report Problem`, active and resolved issue lists, table/kiosk list modes, and a Troubleshooting Memory panel. Issue rows can be opened with the `Open` button, double-click, or Enter on the selected row.

Issue details open as a full page inside BeeLine, not a small modal. The detail page supports active and resolved issues, Back, Go to Machine, metadata, attachments, related-issue/future suggestion sections, and Resolve Issue for active issues. Resolving from the detail page navigates to the resolved issue detail page while the Excel archive worker runs.

## Archive Behavior

Resolved issues are cached in SQLite and appended to the raw Excel sheet. BeeLine prevents duplicate raw archive rows by cache ID.

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

GitHub Actions runs the same validation on `windows-latest` with Python 3.12 for push and pull request events.

## Branding

BeeLine uses one shared header/logo location across major pages.

- Commit-safe placeholder: `assets/branding/nolato_logo_placeholder.png`
- Local approved logo path: `assets/branding/nolato_logo.png`

`nolato_logo.png` and generated images are ignored by Git. Place an approved real logo there only on local machines where that use is allowed.
