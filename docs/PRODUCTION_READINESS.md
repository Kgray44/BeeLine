# BeeLine Production Readiness Notes

## Deployment Assumptions

- Target kiosk systems are Windows machines running Python 3.12.
- BeeLine runtime files are local to the kiosk or a controlled plant-floor runtime location.
- The public repository contains only source code, docs, tests, and sanitized empty templates.
- No external analytics, AI service, or network data-sharing path is used for issue details, troubleshooting memory, related issues, or future suggestion placeholders.

## Runtime Folders

Expected local runtime folders:

- `config/` for local machine and role configuration
- `data/` for SQLite runtime data
- `data/attachments/` for future local-only attachment storage
- `archive/` for the resolved issue Excel archive
- `logs/` for local logs
- `backups/` for local backups

These folders are ignored except for README and `.gitkeep` placeholders. Keep machine config, issue history, archives, photos, logs, and backups out of commits.

## Backup and Archive Recommendations

- Back up `data/beeline.sqlite` and `archive/beeline_resolved_archive.xlsx` using the site's approved local process.
- Run `python run_beeline.py --archive-status` during support checks.
- Run `python run_beeline.py --repair-archive` when the readable grouped Excel view needs to be rebuilt.
- Treat SQLite as the operating record and Excel as a local archive/export target.

## NDA-Safe GitHub Workflow

Before committing:

```powershell
python -m unittest discover -s tests
python scripts\smoke_test.py
python run_beeline.py --check
python scripts\verify_safe_for_github.py
git status --short
```

Confirm Git status does not include runtime config, SQLite databases, Excel archives, screenshots, photos, captures, exports, logs, backups, attachments, private links, secrets, real names, badge IDs, or approved/private branding assets.

## Recommended Role Setup

Default template roles are disabled. A practical kiosk setup is:

- Operator: enabled only if future operator-specific behavior needs it; issue reporting can remain PIN-free.
- Technician: enabled with a locally generated PIN hash for resolving issues.
- Admin: enabled only for trusted maintenance/admin users.

Do not commit production PIN hashes. Generate and store them only in the local runtime config.

## UI Workflow Notes

- Dashboard cards reflow by available width and can be searched, filtered, and sorted.
- The global Open Issues page is the supervisor/maintenance queue across all machines.
- Machine Cell pages keep active and resolved lists local to the selected machine.
- Full Issue Detail pages are the main record view for active and resolved issues.
- Resolving from an Issue Detail page opens the resolved detail record after the save, then the archive worker updates archive status in the background.

## Future Hooks

The Issue Detail page includes local-only sections for Related Issues, Suggested Fixes, Trends, and Attachments. The current related issue helper uses simple local keyword/category matching against resolved history. Future analytics should keep the same rule: no plant data leaves the local environment unless the deployment explicitly approves a new integration.

