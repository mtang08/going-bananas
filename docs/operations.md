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


## Reviewed coaching MVP

The source skill is `.codex/skills/going-bananas-coach`; its manifest pins every
artifact hash, protocol `coach_proposal.v1`, manual activation, and required
calendar authority. The installed skill must match that reviewed artifact.

The local migration is explicit: `python -m app.cli planning-cutover --dry-run`
previews the import; `--apply` commits it. Run through `scripts/with-mode real`
from the repository, with the backend working directory. Quiesce the API and
scheduled sync, take a database/private-files backup and verify a separate
restore, then stage and verify the new skill. Install the staged helper and
commit the cutover before resuming writers. If the database switch fails,
restore the prior helper before resuming the legacy workflow. Do not reset or
reseed the real database. Existing source rows and old history remain intact.

After migration, Home/Calendar/Trends/Block use the calendar workflow. The coach
CLI provides `coach schema`, `coach snapshot --operation OP`, `coach query NAME`,
and `coach submit --file PATH`. Submit creates a pending changeset. Accept or
reject it in the app; there is no CLI acceptance command. A partial selection is
validated again, including strength scheduling and anchor-dependent targets.
Identical decision retries return the stored result, including its version.

A stale proposal requires a fresh snapshot and review. Invalid selections show
field errors and preserve the current checkboxes. Research integrity failure
stops coaching without preventing training metrics from loading. Protected
calendar undo creates a new version and retains completed/locked/history facts.
The old automatic coaching writer is disabled after the switch; old history is
readable. Elaborate legacy undo compatibility is outside this local MVP.

Operational commands:

- `metrics-recompute --metric all --since YYYY-MM-DD --until YYYY-MM-DD` refreshes
  derived metrics; it does not fetch remote data.
- `fit-backfill --since YYYY-MM-DD` fetches available FIT evidence in real mode;
  unavailable or failed items remain explicit and can be inspected.
- `strong-import PATH` previews a CSV; add `--apply` to import it.

Synthetic acceptance uses the isolated PostgreSQL cluster on port 55439 and API port 18000.
It must never reset, seed, or migrate the real database on port 55432. Keep device
verification separate: successful synthetic interval/recovery tests do not
prove every watch export or non-worn-night behavior. Backups include source,
calendar, metric, proposal, and migration tables plus private raw objects.
