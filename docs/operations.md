# Local operations

Never print `.env` or pass keys/database passwords in command-line arguments.
All commands run from the repository root unless shown inside the backend CLI.
Private files and generated reports are ignored by Git.

## Mode and services

`make start` uses `.env`; `scripts/with-mode demo|real|test COMMAND` temporarily
selects the corresponding database and private directory. Backend data modes
cannot be switched by a browser control. Stop the current app before starting
another mode on port 8000. Tests use PostgreSQL, never SQLite.

Use `make db-start` / `make db-stop` for the project-local cluster. This does not
stop other PostgreSQL installations. Application shutdown signals only the
processes its launcher created. The database is intentionally independent.

## Backup / restore

```sh
make backup
make context
```

Explicit real-mode backup and restore (replace the archive path and new target):

```sh
./scripts/with-mode real bash -c 'cd backend && uv run python -m app.cli backup "$PRIVATE_DIR/backups/my-backup.tar.gz"'
./scripts/with-mode real bash -c 'cd backend && uv run python -m app.cli restore "$PRIVATE_DIR/backups/my-backup.tar.gz" --target-database-name garmin_restored_real --target-private-dir ../private/restored-real'
```

For this release, `scripts/verify-restore.py --database NEW_NAME_test --private-dir
NEW_PRIVATE_DIR` compares source and restored table counts, full profile/Strong/coaching row
contents, raw checksums, and private research originals. Run it in real mode.
The restore refuses existing database/directory targets and verifies archive
paths/checksums before use. It derives database connection credentials from the
current protected environment, never arguments. Select a restored database only
after verification. Keep the old database until satisfied. Restore failures may
leave a new incomplete target for inspection; they do not overwrite the source.
Credentials and token cache are excluded: configure Garmin access separately.
Backups contain sensitive activity/health records and must remain private.

## Daily sync on macOS

Installed locally for this checkout on 2026-11-10 at 08:30.

The supplied launchd template uses an explicit absolute checkout path and runs
`scripts/launchd-sync.sh` daily at 08:30 local time. That wrapper loads protected
configuration, enqueues bounded sync jobs, and drains them even if the web app
is closed. Worker and standalone runs coordinate using PostgreSQL advisory locks.
The wrapper starts the existing project-local database if necessary. Startup catch-up covers missed schedules;
failed/partial datasets remain visible.

To install manually, replace `REPLACE_WITH_ABSOLUTE_CHECKOUT` in
`scripts/com.local.garmin-sync.plist.example`, save it as
`~/Library/LaunchAgents/com.local.garmin-sync.plist`, and use:

```sh
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.local.garmin-sync.plist
launchctl print "gui/$(id -u)/com.local.garmin-sync"
```

Remove the schedule without deleting training data:

```sh
launchctl bootout "gui/$(id -u)/com.local.garmin-sync"
```

The template contains no secrets. Logs live under `private/` and contain safe
job statuses/error codes. Do not infer an import succeeded from launchd alone;
inspect the app's dataset status and coverage.

## Troubleshooting

- `make doctor`: availability only, never credential values.
- Readiness unavailable: start the database and run migrations for the active mode.
- Credential attention: replace/renew the private Garmin key; don't paste it into
  chat. Imported history stays readable.
- Partial dataset: inspect the safe reason and coverage; valid records remain.
- Same sync requested twice: use the existing job. Rate limits use bounded retries
  and delayed retry timestamps. Failed jobs can be explicitly re-requested.
- Missing lifting: inspect the Strong import date/coverage and unresolved overlaps.
  A snapshot gap does not establish skipped lifting.
- Recurring strength setup: enter the weekly pair or Week A/B rotation once in
  Data & settings. Confirm the Week A Monday reference, required mobility, and
  optional mobility separately. The app uses this dated pattern for calendar
  and Coach context. Accepted dated plans override recurrence on covered dates.
- Unknown run cycle: confirm the anchor when known. Coach can still show
  provisional options without it; no fitness/race/rehab assumptions are filled in.
- Historical run label seems wrong: open the activity detail and save a
  manual label. The relative suggestion is provisional; missing data remains
  unknown. No per-activity model call is used.
- Coach advice appears stale: generate again after check-in, plan, source, or
  research changes; tomorrow previews need a fresh day-of review. Recording an
  outcome does not alter the accepted manual plan.
