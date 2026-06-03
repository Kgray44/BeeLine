# BeeLine Issue Tracker

BeeLine is a plant-floor kiosk issue tracker MVP with a Hive Dashboard, Machine Cell pages, issue logging, SQLite runtime storage, and openpyxl-based Excel archive writing.

This repository is prepared for GitHub with application code and safe, empty template files only. Real plant runtime data belongs in ignored local folders.

## Run BeeLine

```powershell
python -m pip install -r requirements.txt
python run_beeline.py
```

Startup checks:

```powershell
python run_beeline.py --check
python run_beeline.py --archive-status
```

`--archive-status` prints the archive workbook path, sheet names, raw resolved row count, latest resolved timestamp, and whether the readable `Resolved_By_Date` sheet exists.

## Runtime Files

On first launch, BeeLine copies safe templates into local runtime locations if the runtime files are missing:

- `templates/beeline_config.template.json` -> `config/beeline_config.json`
- `templates/beeline.template.sqlite` -> `data/beeline.sqlite`
- `templates/beeline_archive.template.xlsx` -> `archive/beeline_resolved_archive.xlsx`

You can initialize those files manually:

```powershell
python scripts\initialize_runtime_files.py
```

To recreate missing safe templates during development:

```powershell
python scripts\initialize_runtime_files.py --create-templates
```

## Plant Configuration

Machine data is not hardcoded in the app. Add local machine configuration to `config/beeline_config.json` on the target machine.

Do not commit:

- real machine data
- real employee/operator names
- badge IDs
- issue history
- real SQLite data
- real Excel archive data
- logs, backups, exports, secrets, credentials, tokens, or `.env` files

## Templates

Committed templates are intentionally empty/sanitized:

- SQLite template includes schema only and no records.
- Excel archive template includes headers/sheets only and no issue rows.
- Config template includes placeholder documentation and an empty `machines` list.

The runtime Excel archive keeps raw source records in `Resolved_Issues` and refreshes a readable `Resolved_By_Date` view after each archive write. `Resolved_By_Date` is sorted newest date first, then newest resolved time first inside each date, with collapsible Excel outline groups by date.

## Branding

BeeLine uses one shared header/logo location across major pages.

- Commit-safe placeholder: `assets/branding/nolato_logo_placeholder.png`
- Local approved logo path: `assets/branding/nolato_logo.png`

`nolato_logo.png` is ignored by Git. Place the approved real logo there only on local machines where that use is allowed. If no approved logo exists, BeeLine falls back to the placeholder or text-only BeeLine branding.

## Safety Check

Run this before committing or pushing:

```powershell
python scripts\verify_safe_for_github.py
```

The safety check fails on common risky files, including runtime databases, runtime archives, logs, backups, secrets, real config files, and non-empty templates.

## GitHub

The intended remote is:

```text
https://github.com/Kgray44/BeeLine
```

Safe commit/push flow:

```powershell
python scripts\smoke_test.py
python run_beeline.py --check
python scripts\verify_safe_for_github.py

git status --short
git add .gitignore README.md requirements.txt run_beeline.py app assets templates scripts tests data/.gitkeep data/README.md archive/.gitkeep archive/README.md backups/.gitkeep backups/README.md logs/.gitkeep logs/README.md config/.gitkeep config/README.md
git status --short
python scripts\verify_safe_for_github.py
git commit -m "Prepare BeeLine for safe GitHub repository"
git push -u origin main
```

Do not use `git add -f` on ignored runtime data unless you are deliberately adding a safe placeholder/template and have rerun the safety check.
