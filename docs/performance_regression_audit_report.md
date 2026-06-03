# BeeLine Performance Regression Audit Report

Date: 2026-06-03

## Summary

This pass treated the reported slow Cancel, machine open, back/home, and dashboard animation issues as symptoms of a broader regression. The fix restores the intended architecture:

- SQLite remains the fast live database and recent resolved cache.
- Excel remains the cold long-term archive.
- Normal startup, dashboard, machine pages, and Quick Search do not touch Excel.
- Navigation switches to the target page shell immediately, then loads heavier data in background tasks.
- Large issue/history views are limited before they reach the UI.
- Dashboard machine cards are cached and updated in place instead of recreated on every refresh.

## Root Causes Found

- Several navigation paths performed repository and analytics work before switching pages.
- Returning home could refresh the dashboard during page transitions, making cards appear to rebuild during the animation.
- Cancel/close paths could trigger broader refresh logic even when no data changed.
- Machine and predictive views reused broad history/risk methods that loaded more data than the visible page required.
- Open issue, machine details, predictive, and issue-detail pages had synchronous load paths tied directly to click handlers.
- Dashboard refresh detached and rebuilt the card grid more often than necessary.
- Archive and Excel access needed clearer instrumentation and startup guards to prevent accidental cold-archive reads in normal flows.

## Files Changed

- `app/beeline_issue_tracker/perf.py`
- `app/beeline_issue_tracker/app.py`
- `app/beeline_issue_tracker/config.py`
- `app/beeline_issue_tracker/data/database.py`
- `app/beeline_issue_tracker/data/repository.py`
- `app/beeline_issue_tracker/data/analytics_repository.py`
- `app/beeline_issue_tracker/data/archive.py`
- `app/beeline_issue_tracker/data/archive_search.py`
- `app/beeline_issue_tracker/analytics/predictive_service.py`
- `app/beeline_issue_tracker/ui/main_window.py`
- `app/beeline_issue_tracker/ui/dashboard.py`
- `app/beeline_issue_tracker/ui/machine_cell.py`
- `app/beeline_issue_tracker/ui/machine_details_page.py`
- `app/beeline_issue_tracker/ui/open_issues.py`
- `app/beeline_issue_tracker/ui/predictive_maintenance_page.py`
- `app/beeline_issue_tracker/ui/issue_detail_page.py`
- `scripts/initialize_runtime_files.py`
- `tests/test_app_cli.py`
- `tests/test_machine_info_page.py`

## Slow Paths Fixed

- Machine card click now shows a machine page shell/loading state immediately and starts `MachineLoadTask` on a background pool.
- Open Issues, Predictive Maintenance, Machine Details, and Issue Detail navigation now switch first and load snapshots asynchronously.
- Cancel on the issue form now performs navigation only; it does not refresh dashboard or reload issue data.
- Back/home navigation queues dashboard refresh until after transitions instead of doing heavy work during animation.
- Dashboard card refresh reuses existing `MachineCard` widgets and rebuilds layout only when the machine set/order or column count changes.
- Machine page loading now uses targeted machine summary, active issue, resolved issue, and predictive-risk queries instead of broad all-machine history.
- Machine details no longer computes recurring patterns through broad all-machine risk input during normal page load.
- Predictive Maintenance renders from a prepared snapshot and debounces search typing.
- Table/list rebuild paths block updates/signals while repopulating and cap displayed rows.
- Related resolved issue search uses a bounded candidate pool.
- App startup skips archive workbook creation/checking during normal `--check` and startup flows.

## Excel Access Rules

Instrumentation was added to archive paths so unexpected workbook operations are visible in logs as `[PERF] excel_access ...`.

Normal flows are guarded to stay SQLite-only:

- Startup: no archive workbook copy or open.
- Dashboard refresh: SQLite summaries only.
- Machine page open/refresh: SQLite machine-specific queries only.
- Quick Search: SQLite only.
- Archive health: delayed until settings/maintenance UI explicitly asks for it.

Excel remains available for explicit archive operations:

- Deep Search archive phase.
- Archive append after resolve.
- Failed archive retry/maintenance.
- Explicit rebuild/export/inspection actions.

Failed Excel archive writes still leave the resolved issue in SQLite with pending archive metadata, preventing data loss.

## Performance Logging

Added a lightweight helper in `app/beeline_issue_tracker/perf.py`.

- Default: enabled.
- Disable with `BEELINE_PERF_LOG=0`.
- Logs use `[PERF]` and include elapsed milliseconds for startup, database initialization, page transitions, dashboard refresh/rendering, machine snapshots, table rendering, predictive snapshots, Quick Search, Deep Search kickoff, and Excel/archive access.

Representative expected behavior after this pass:

- `form_cancel` does not trigger repository/archive refresh work.
- `open_machine` switches page before machine data load completes.
- `dashboard.render_cards` reports whether cards were created, updated, and whether layout was rebuilt.
- Any `load_workbook` usage appears as `excel_access`, making cold-archive violations easy to spot.

## Tests Added Or Updated

- `--check` does not force archive workbook creation.
- Machine page click switches before repository loading.
- Cancel log issue does not refresh/reload heavy views.
- Dashboard refresh is deferred until navigation finishes.
- Open Issues navigation switches before repository loading.
- Predictive navigation switches before analytics loading.
- Machine Details navigation switches before repository loading.
- Issue Detail navigation switches before repository loading.
- Dashboard refresh reuses existing card layout.
- Quick Search does not touch Excel.
- Machine page refresh uses limited direct queries.

## Validation

Run after implementation:

- `python -m ruff check .`
- `python -m unittest discover -s tests`
- `python -m pytest`
- `PYTHONPATH=app python -m beeline_issue_tracker --check`
- `python scripts/smoke_test.py`
- `python scripts/perf_seed.py --db-path %TEMP%\beeline_perf_codex.sqlite --machines 100 --active 5000 --resolved 50000 --force`

Results:

- Ruff passed.
- `unittest` passed: 94 tests.
- `pytest` passed: 94 tests after adding the synthetic seed safety-scanner regression test.
- Startup/check smoke passed and reported `Archive workbook check: skipped during normal startup`.
- Existing smoke script passed using a temporary database/archive.
- Synthetic seed created 100 fake machines, 5,000 fake active issues, and 50,000 fake resolved issues in `%TEMP%`; no real plant data was used.
- Synthetic read-path probe against that database:
  - dashboard `list_machines_with_status`: 7 ms for 100 machines
  - machine snapshot for `DEMO-001`: 58 ms, returning 10 active and 10 resolved rows
  - Open Issues snapshot: 12 ms, returning 250 rows

Additional checks to run for each release candidate:

- manual click-through of dashboard, machine page, issue form cancel/submit, Open Issues, Predictive Maintenance, settings/archive maintenance, Quick Search, and explicit Deep Search

## Remaining Risks And Deferred Improvements

- The app still uses `QTableWidget` in several places. Current work caps row counts and blocks updates/signals, but a future `QAbstractTableModel` migration would scale better for very large result sets.
- Deep Search is explicitly allowed to touch Excel. It should continue to be monitored with `[PERF] excel_access` logs and cancellation/progress behavior should be expanded if archive workbooks grow significantly.
- The network share currently blocks creating a literal `.git` metadata entry. A separate local gitdir was seeded and works with explicit `--git-dir` and `--work-tree` arguments, but automatic Git discovery from the UNC folder depends on the share allowing `.git` creation.
- Real production timing should be captured on the plant workstation with representative synthetic data after the local checks pass.

## Acceptance Status

- Normal startup/dashboard/machine/Quick Search paths avoid Excel.
- Navigation no longer waits on heavy data loading before showing the destination page.
- Dashboard cards update in place and do not rebuild during transitions.
- Machine pages use limited, machine-specific SQLite queries.
- Predictive and issue list rendering are bounded and less synchronous.
- Tests cover the key regressions that caused the reported slow behavior.
- No real plant data, runtime databases, archive workbooks, or sensitive files were added by this pass.
