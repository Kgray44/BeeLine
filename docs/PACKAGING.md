# Windows Executable Packaging

BeeLine Issue Tracker can be packaged as a clickable Windows executable with PyInstaller. The packaged app launches the normal BeeLine UI without requiring users to install Python.

## Build Prerequisites

Use a Windows machine with Python installed for the build step.

```powershell
python -m pip install -r requirements.txt
```

`requirements.txt` includes the runtime dependencies plus PyInstaller for packaging.

## Build The Executable

Run the build script from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_tools\build_exe.ps1
```

By default the script removes old `build` and `dist` folders before building. To keep existing artifacts, use:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_tools\build_exe.ps1 -NoClean
```

The expected output is:

```text
dist\BeeLine Issue Tracker\BeeLine Issue Tracker.exe
```

Distribute the whole `dist\BeeLine Issue Tracker` folder. The executable depends on the bundled files next to it.

## What Gets Bundled

The PyInstaller spec bundles only commit-safe application resources:

- `templates/beeline_config.template.json`
- `templates/beeline.template.sqlite`
- `templates/beeline_archive.template.xlsx`
- approved branding images from `assets/branding`
- the BeeLine Python package and required PySide6, Qt, SQLite, and openpyxl runtime dependencies

The build intentionally does not bundle live runtime folders such as `config`, `data`, `archive`, `logs`, `backups`, `exports`, screenshots, or attachments.

## Runtime Data Location

When run from source, BeeLine keeps its current behavior and defaults runtime files to the repository folders.

When run from the packaged executable, BeeLine reads templates and branding from the bundled application resources, then writes user data under:

```text
%LOCALAPPDATA%\BeeLine Issue Tracker
```

That folder contains runtime config, SQLite data, archive workbooks, logs, backups, attachments, and local exports created by the app.

The same environment overrides still work if a deployment needs custom locations:

- `BEELINE_ROOT_DIR`
- `BEELINE_TEMPLATE_DIR`
- `BEELINE_CONFIG_DIR`
- `BEELINE_DATA_DIR`
- `BEELINE_ARCHIVE_DIR`
- `BEELINE_LOG_DIR`
- `BEELINE_BACKUP_DIR`
- `BEELINE_LOGO_PATH`

Packaged builds also support `BEELINE_RESOURCE_DIR` and `BEELINE_BRANDING_DIR` for advanced deployment layouts.

## Validation

Recommended validation before distributing a build:

```powershell
python scripts\verify_safe_for_github.py
python -m compileall .
python -m pytest
python scripts\smoke_test.py
powershell -ExecutionPolicy Bypass -File .\build_tools\build_exe.ps1
& ".\dist\BeeLine Issue Tracker\BeeLine Issue Tracker.exe" --check
```

The `--check` command initializes the packaged app's runtime files and exits without opening the UI.
Run the safety check before building, or after deleting ignored `build` and `dist` outputs, because PyInstaller copies safe SQLite and Excel templates into `dist`.
