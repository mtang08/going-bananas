# Local operations

Never print `.env` or pass keys/database passwords in command-line arguments.
Run commands from the repository root unless an example changes directories.
Private files and generated reports are ignored by Git.

## Mode and services

`make start` and `make dev` use the workspace configured in `.env`.
`./scripts/with-mode demo|real|test COMMAND` selects the corresponding database
and private directory for one command. Demo and test default to native Go. Real
mode defaults to the Python reference backend until the owner switches it. Set
`GOING_BANANAS_BACKEND=go` or `GOING_BANANAS_BACKEND=python` in `.env` or in the
calling environment. The supervisor, operational CLI, and coaching helper use that
selection. Keep the API, worker, and commands that write to the workspace on the
same selection.

Use `./scripts/with-mode demo make start` to serve the built demo and
`./scripts/with-mode demo make dev` for the demo with Vite. Replace `demo` with
`real` for the real workspace after completing its setup. Real startup also runs
the provider worker. Stop the running app before starting another mode from this
checkout. The default API port is 8000. Integration tests use their own isolated
PostgreSQL cluster.

Use `./scripts/with-mode MODE ./scripts/backend-cli COMMAND` for one-off operations.
For Go, the wrapper builds and runs `going-bananas`. For Python, it runs the
reference command through `uv`. Use `./scripts/with-mode MODE make migrate` for
migration so the real-mode backup gate applies. The Go migrator handles fresh and
current databases natively and uses Alembic for a supported historical revision.
The Python selector uses Alembic directly.

Use `make db-start` / `make db-stop` for the project-local cluster. This does not
stop other PostgreSQL installations. Application shutdown signals only the
processes its launcher created. The database is intentionally independent.

## Open Going Bananas on macOS

After completing the local setup and building the app, double-click
**Going Bananas.command** in Finder. Choose **Open** to launch the configured
dashboard at `http://127.0.0.1:8000`. The launcher opens an already healthy
dashboard or starts the local service and waits for readiness. The Finder
menu identifies an already running demo or test dashboard before opening it.
After a software update, stop the dashboard from the session that originally
launched it, then open it again from Finder.

On macOS, open the real dashboard and turn on **Start Going Bananas when I log in**
in **Settings**. You can also choose **Enable at Login** from the Finder
launcher. Both set up startup for your next macOS login. The login agent uses
this checkout's `.env` and starts the existing project-local PostgreSQL cluster
when the configured database uses it. Keep the checkout at the same path while
login startup is enabled. Each login uses the current built frontend. Build and
migrate during setup or an update, before the next startup. Startup diagnostics
are recorded in `private/dashboard-launch.log`. If another process owns port
8000, the agent leaves it running and exits.

Turn off the switch or choose **Disable at Login** to prevent startup at the
next login. The current dashboard, worker, and PostgreSQL keep running. macOS
retains the disabled agent so you can re-enable it from either control. If
another checkout owns the login item, open that checkout to manage it. The
equivalent terminal status command is `./'Going Bananas.command' status`.

The Coach page uses the local Codex CLI and offers a ChatGPT sign-in button.
Complete sign-in in the OpenAI browser window, then return to the dashboard.
Codex keeps its dashboard credentials and thread state under
`private/coach-codex/`, a user-private directory ignored by Git. Personalized
coaching requires an account and workspace with access to Astra Medium. The
login agent only starts local services. An athlete message is required to start
a coaching turn.

## Backup / restore

```sh
make backup
```

In real mode, `make migrate` backs up to `$PRIVATE_DIR/backups/` and stops if the backup fails. Demo and test migrations run directly.

Training backups include saved proposals and accepted calendar history. After the native dashboard imports a review, the PostgreSQL backup also contains its conversation, thread reference and message receipts. Before that first import, the Python review files live under `$PRIVATE_DIR/coach-chat/`. Preserve those files at cutover. The separate Codex profile under `private/coach-codex/` holds local provider state and credentials and is excluded from the training backup.

Before applying `0022_race_goals` to the real database, check its current revision and retain a pre-migration backup. This migration deletes existing events, clears their links on retained benchmark and anchor records, and expires outstanding post-race review findings. Restoring the backup recovers the old events. After migrating, enter upcoming races under **Settings → Events**, choose their purposes, and put the goal race first. The next block review can link the accepted block to that race.

Before applying `0025_coach_output_v2` to the real database, run `make backup` and check the current revision. This migration moves every old coach rationale, follow-up, and block rationale into an **Earlier format** block on its proposal or block version, with ID tags removed from the coach text the app shows. The submitted documents keep their original wording, except that ID tags are also removed from their exception, race-review, and patch text, which the app shows. It discards every open proposal (pending, stale, or invalid), so accept anything you want to keep in the app first; the coach starts fresh at the next review. Copy any hand-entered session notes you want to keep before migrating. The migration clears every existing session note. New session notes belong to the athlete, and the coach writes its guidance in a separate brief. The coach protocol is now `coach_proposal.v2`: use the helper from the updated checkout, refresh any separately installed skill copy, and start a new coaching session. An old copy stops with `incompatible_coach_protocol`. The migration cannot be downgraded once new-format proposals, block reasons, or session briefs exist (`restore_required_coach_output_v2`); restore the backup instead.

Migrations `0026_workout_response` and `0027_rehab_sessions` preserve existing check-ins as unknown and allow a dated rehab slot. A downgrade refuses to drop an explicitly recorded pain answer or a calendar revision containing rehab.

For a named real-mode backup and restore, replace the archive name and choose a new target database and directory.

```sh
./scripts/with-mode real bash -c './scripts/backend-cli backup "$PRIVATE_DIR/backups/my-backup.tar.gz"'
./scripts/with-mode real bash -c './scripts/backend-cli restore "$PRIVATE_DIR/backups/my-backup.tar.gz" --target-database-name garmin_restored_real --target-private-dir "$PWD/private/restored-real"'
```

For a rehearsal, restore into a new database ending in `_test` and a new private
directory. From the real source workspace, run the Python verification utility.
It compares database rows, raw file checksums, and private research originals.

```sh
./scripts/with-mode real uv run --directory backend python ../scripts/verify-restore.py --database garmin_restored_test --private-dir /absolute/path/to/restored-test
```

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
configuration and uses the selected backend for sync and backup. It enqueues
bounded sync jobs and drains them even if the web app is closed. Worker and
standalone runs coordinate using PostgreSQL advisory locks. The wrapper starts
the existing project-local database if necessary. Startup catch-up covers
missed schedules, and failed or partial datasets remain visible. Native
scheduled sync requires `go` on the PATH loaded by `scripts/env.sh`.

After a successful sync the wrapper also writes one backup per local day to `$PRIVATE_DIR/backups/backup-YYYYMMDD-HHMMSS.tar.gz` (skipped if one exists for today), then runs `scripts/backup-prune.sh`. That script deletes `backup-*.tar.gz` files older than `BACKUP_RETENTION_DAYS` (default 14) and always keeps the newest `BACKUP_MIN_KEEP` (default 3). Set either variable in `.env` to change it. A failed backup makes the job exit nonzero and is recorded in `private/launchd-sync-error.log`; pruning is skipped in that case.

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

- `make doctor`: checks Go, frontend and PostgreSQL tools, and reports whether the checkout has a mode configuration and research library. It checks file presence without reading configuration values. The optional `uv` tool serves historical Alembic migrations and Python checks.
- Readiness unavailable: start the database and run migrations for the active mode.
- Credential attention: replace/renew the private Garmin key; don't paste it into
  chat. Imported history stays readable.
- Google Calendar sync says access expired, was revoked, or lacks read access:
  rerun `calendar-connect` in real mode (README, "Google Calendar travel").
  A rate-limit message means wait and press **Sync calendar** again. To revoke
  access, remove the app under myaccount.google.com → Security → Third-party
  access. The client file and token are not backed up; after a restore,
  copy the client file back into `private/real/` and reconnect.
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
artifact hash, protocol `coach_proposal.v2`, manual activation, and required
calendar authority. The installed skill must match that reviewed artifact.

Keep the real database and its historical tables when changing backends. The frozen planning and coaching tables are listed in [history_models.py](../backend/app/history_models.py). Current snapshots, proposals, decisions and dashboard receipts use the tables listed in [coach_v2_models.py](../backend/app/coach_v2_models.py). Back up before any real schema change.

Real coaching uses Python until the owner selects Go. At the scheduled switch, stop the running dashboard and keep a verified backup. Set `GOING_BANANAS_BACKEND=go` in the checkout’s private `.env`, then run `./scripts/with-mode real make migrate` and `./scripts/with-mode real make build` before reopening **Going Bananas.command**. A temporary shell override applies only to processes that inherit it. The first native launch imports the prior review and receipts for that mode. Open **Coach** and check the existing conversation and pending draft before sending a new message. [Native coaching rehearsal](go-rewrite-coaching.md#native-dashboard-handoff)

Home, Calendar, Trends and Block use the calendar workflow. From the repository root, `python3 .codex/skills/going-bananas-coach/scripts/coach_app.py --mode demo schema` shows the current contract in demo mode. Use the same prefix with `snapshot --operation OP`, `query NAME`, or `submit --file PATH`. Submit creates a pending changeset. Accept or
reject it in the app; there is no CLI acceptance command. A partial selection is
validated again, including strength scheduling and anchor-dependent targets.
Identical decision retries return the stored result, including its version.

A stale proposal requires a fresh snapshot and review. Invalid selections show
field errors and preserve the current checkboxes. Research integrity failure
stops coaching without preventing training metrics from loading. Protected
calendar undo creates a new version and retains completed/locked/history facts.

Run these subcommands with `./scripts/with-mode MODE ./scripts/backend-cli`.

- `metrics-assess-session --session-uid UUID` previews the reassessment of one session and its linked activity. Add `--apply` to save it. Existing matches and source data are preserved.
- `fit-reprocess --since YYYY-MM-DD` previews re-decoding of retained FIT files after a decoder change. Add `--apply` to save. Applying refreshes metrics and same-day matching for the touched dates.
- `metrics-recompute --metric all --since YYYY-MM-DD --until YYYY-MM-DD` refreshes
  derived metrics; it does not fetch remote data.
- `metrics-refresh-today` refreshes today’s windows and their source metrics and updates prompts using local data.
- `fit-backfill --since YYYY-MM-DD` fetches available FIT evidence in real mode;
  unavailable or failed items remain explicit and can be inspected.
- `strong-import /absolute/path/to/strong_workouts.csv` previews a Strong export. Add `--apply` to save the workouts and refresh their metrics.

Metric GET endpoints leave the database unchanged. Metric pages compute missing results and results with
outdated methods or configs in memory. Some calculations still read stored dependencies: intensity, long-run,
and aerobic windows read stored activity results, and planned-versus-actual assessments read stored interval
results. The weekly digest and workout progression also show stored assessments. After a method or config
change, run `metrics-recompute` for affected older dates that the startup pass does not cover.

Each server start (`make start`, `make dev`) runs `metrics-refresh-today` before serving. It refreshes the last 84 days of run metrics, session assessments within 13 days of today (including derived completion status), the last seven nights, and today's windows, then updates prompts. Take a backup before the first real-mode server start after a metric method change. `app.log` records a `refresh ...` line per write-time refresh and a `startup refresh ...` line per startup pass.

For an explicit connection outside the configured workspace, pass `APP_MODE`, `DATABASE_URL`, and `PRIVATE_DIR` together. The local runner preserves this complete destination and rejects a conflicting partial destination before running the command. The normal named-mode entry point is `scripts/with-mode`.

Synthetic acceptance uses the isolated PostgreSQL cluster on port 55439 and API port 18000.
It must never reset, seed, or migrate the real database on port 55432. Keep device
verification separate: successful synthetic interval/recovery tests do not
prove every watch export or non-worn-night behavior. Backups include source,
calendar, metric, proposal, and migration tables plus private raw objects.

## Read-only preflight for an owner-scheduled backend switch

Once the owner schedules the switch, stop the API, worker, automatic startup and other writers. Finish or reconcile in-flight jobs and verify the final backup. Run the native preflight explicitly against the real workspace.

```sh
GOING_BANANAS_BACKEND=go ./scripts/with-mode real ./scripts/backend-cli workspace-preflight -repo "$PWD"
```

A successful run exits zero and returns JSON with `ready: true`. It reads the profile, accepted calendar, active draft and weekly summary, verifies the migration stamp and expected columns, checks provider checkpoints and hashes the retained raw files. It reports whether provider configuration files are present and private using filesystem metadata. A pending draft that has become stale is reported for review. An absent optional provider credential is reported separately. Failures identify the check without exposing athlete records, filenames or credentials. Correct the reported failure and rerun the command before starting the normal supervisor.
