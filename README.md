# Going Bananas — local training analytics

A private, single-user local training dashboard built with React/TypeScript,
FastAPI, and PostgreSQL. It combines Garmin activity/recovery history with an
imported Strong lifting snapshot and a reviewed running research library. Strong
remains the lifting workflow; the app reads its CSV export and does not write
workouts back to Strong.

The running coach uses the repo-local
[`going-bananas-coach` Codex skill](.codex/skills/going-bananas-coach/SKILL.md).
It reads compact training snapshots and verified research, then saves a **pending
changeset**. Review each change in the app before applying it. The dashboard,
imports, metrics, and validation run locally without model calls.

## Daily and weekly use

Frontend implementation conventions are in [the UI system guide](docs/ui-system.md).

Open **User guide** in the app for copyable coaching prompts and the daily,
Sunday, and training-block workflows. The same guide is maintained in
[docs/user-guide.md](docs/user-guide.md) and can be downloaded from the app.

1. Open **http://127.0.0.1:8000**. Home shows today's plan, open effort/response
   prompts, projected weekly mileage, and the next two weeks. Record check-ins
   and actual effort there.
2. Ask Codex to use **`$going-bananas-coach`** for a weekly review, today's
   adjustment, a block review, calibration, or a race/goal change. If there is no
   training block yet, start with a block review.
3. Open **Pending proposal → Review proposal**. Select the session changes,
   block change, and calibration anchors you want to accept. Unselected session
   changes are rejected. Nothing applies when you open the page or submit a
   proposal from Codex.
4. Inspect accepted sessions and revision history in Calendar. Completed,
   historical, and locked sessions remain protected when undoing a change.
   A check-in or new import can make a proposal stale; request a fresh review.
5. Use Trends and activity details to inspect timer-based volume, effort load,
   long runs, intensity, interval execution, and recovery. Missing observations
   remain unknown and metric explanations retain the original evidence.

Weekly mileage uses Monday–Sunday in your profile timezone: recorded running
distance so far plus remaining accepted runs. Time-based runs use workout speed
targets or median observed speed from the last 28 days and are marked as
estimates. Missing data or incomplete plan coverage is labeled; past unrecorded
runs are not added to the forecast. Pending proposals do not affect the total.

Use Sunday evening as the normal weekly coaching review; initiate it in Codex.
Extra reviews are for material changes, symptoms, or new goals. To adjust a
pending proposal, tell the coach what to change and include its review link.
The coach edits that draft under the same link, with a saved revision history.
Refresh and review the latest revision before accepting; selections reset when
the draft changes. Stale drafts need refreshed context, but keep their link.
Accepted or rejected proposals stay fixed; later plan changes use a new proposal.
Only one draft can be open at a time, including stale or invalid drafts. Use
**Discard proposal** on its review page to clear it and start fresh. Discarding
removes it from the open list and preserves its history; it does not change the
calendar. The coach checks for the active draft before submitting a new one.

Strength stays in Strong; import its CSV snapshot in the local app. Confirm the
weekly or alternating strength/mobility schedule in Data & settings. Plans,
source observations, and legacy coaching history are retained during the
calendar migration. New coaching changes always require explicit review.

FIT decoding supplies timer segments, laps, steps, streams, and watch RPE when
available. Source coverage, calibration, and stream quality determine whether a
metric can be assessed. Synthetic tests do not establish device support: local
Garmin sample decoding and timer/RPE comparisons have passed; broader repeat/lap
mapping and non-worn-night behavior remain explicitly unverified. The app shows
unavailable or partial evidence rather than filling those gaps.

Historical Strong sessions and exact recorded sets are in Strength. The app
uses only the preceding **18 calendar months** of Strong sessions for current
running context; older workouts remain browsable. The export has no verified
weight unit or dumbbell convention-change date, so the app does not compare
weights or derive PR targets across that change.

## Run on this Mac

From the repository root:

```sh
make doctor
make db-start
make migrate
make build
make start
```

Open **http://127.0.0.1:8000**. `Ctrl+C` stops the app and its worker; database
contents persist. `make db-stop` stops this project's PostgreSQL cluster.
The app is loopback-only. Phone access and hosting are deferred.

For development, `make dev` starts the API, worker (real mode), and Vite at
http://127.0.0.1:5173. Do not run `make dev` and `make start` simultaneously.

## Fresh setup

Prerequisites: Python 3.12+, uv, Node.js 22+, npm, and PostgreSQL 17 tools.
`scripts/env.sh` recognizes the Homebrew locations on this Mac and otherwise
uses PATH. Dependencies are resolved in `backend/uv.lock` and
`frontend/package-lock.json`.

```sh
make setup
make db-start
make migrate
make seed-demo
make build
make start
```

`make db-start` creates a **project-local** PostgreSQL cluster under ignored
`private/postgres/`, bound to 127.0.0.1:55432, with separate `garmin_demo`,
`garmin_test`, and `garmin_real` databases. It appends missing local settings to
`.env` without replacing existing secrets and protects that file. It does not
install system packages or register a login service. `compose.yaml` is an
alternative PostgreSQL service; don't start both on the same port. For Compose,
configure `POSTGRES_PASSWORD` locally and create the test/real databases when
needed. PostgreSQL is the only database backend.

`.env.example` documents the settings. Keep `.env` private (0600); it must never
be committed. `APP_MODE` must match the database suffix (`_demo`, `_test`, `_real`).
Demo seeding is refused in real mode. Demo and real raw-file directories are
also separate.

## Garmin ingestion

Configure `GARMIN_API_KEY` in the protected root `.env`, or `GARMIN_KEY_FILE`
pointing to a protected file. Never put credentials in `VITE_*`, a command-line
argument, a screenshot, or a model prompt. The backend manages the short-lived
access-token cache privately. Keys can expire or be revoked independently.

Switching modes for a single command does not rewrite `.env`:

```sh
./scripts/with-mode real bash -c 'cd backend && uv run alembic upgrade head'
./scripts/with-mode real bash -c 'cd backend && uv run python -m app.cli sync'
./scripts/with-mode real python3 scripts/serve.py
```

The real-mode Data & settings screen offers manual sync. `make sync` runs a
standalone sync for the mode configured in `.env`. Explicit historical window:

```sh
./scripts/with-mode real bash -c 'cd backend && uv run python -m app.cli sync --start 2026-10-14 --end 2026-11-10'
```

Activities and sleep/HRV/resting HR sync independently. A partial failure does
not discard successful records. Inspect status and coverage instead of assuming
that a successful connection means complete history. Source-invalid records
remain excluded and visibly affect coverage. Missing recovery observations are
unknown. Re-imports preserve source revisions and avoid double-counting.

Startup catch-up and the worker use the same persistent jobs as manual sync.
For a daily macOS schedule, `scripts/com.local.garmin-sync.plist.example` is a
secret-free template pointing to `scripts/launchd-sync.sh`; see
[operations](docs/operations.md) for installation/status. Scheduling never runs
through an LLM. Official integration details and remaining provider uncertainties
are documented in [the capability inventory](docs/garmin-capabilities.md).

The local CLI also accepts the inspected Garmin account-export format. It checks
archive safety, account identity, and overlap with existing activities before
writing. The first command is a read-only preflight; `--apply` commits the import:

```sh
./scripts/with-mode real bash -c 'cd backend && uv run python -m app.cli import-export /absolute/path/to/export.zip'
./scripts/with-mode real bash -c 'cd backend && uv run python -m app.cli import-export /absolute/path/to/export.zip --apply'
```

The original ZIP and parsed source bytes are preserved in the private raw store.
The export adds historical observations without replacing newer API summaries.
Observed export dates are marked as partial coverage, since an account snapshot
does not prove complete watch wear or provider history. Repeating the import is
safe: the verified replay created no new source revisions or canonical changes.
This parser is specific to the inspected Garmin export schema; the browser does
not accept arbitrary ZIPs.

## Strong import

The inspected Strong CSV has already been imported into the real workspace.
For a later export, preview first and apply only after checking the source and
backup. Repeating identical bytes is idempotent:

```sh
./scripts/with-mode real bash -c 'cd backend && uv run python -m app.services.strong_import /absolute/path/to/strong_workouts.csv'
./scripts/with-mode real bash -c 'cd backend && uv run python -m app.services.strong_import /absolute/path/to/strong_workouts.csv --apply'
```

The original CSV and source rows are preserved privately. Source-local timestamps
have no timezone; duration timers over 24 hours remain visible as source text
but have unknown normalized duration. Same-day Garmin/manual strength candidates
are reported as ambiguous rather than silently counted twice. This importer
supports the inspected Strong format, not arbitrary CSVs.

## Feedback and planning

The reviewed skill source is `.codex/skills/going-bananas-coach`. Install that
package during the calendar migration using the manifest and backup procedure in
[operations](docs/operations.md); the older `skills/` package belongs to the
legacy workflow. Start a new Codex session after installation if skill discovery
needs refreshing.

Invoke `$going-bananas-coach` and describe the review you want. The invoking
Codex model supplies the reasoning; the app does not need a separate model key
or runner. Select real mode for your training. Proposal payloads remain in
private local storage, and submission always stops at pending review.

The helper also provides explicit read commands:

```sh
python3 .codex/skills/going-bananas-coach/scripts/coach_app.py --mode real schema
python3 .codex/skills/going-bananas-coach/scripts/coach_app.py --mode real snapshot --operation proceed_or_modify_today
python3 .codex/skills/going-bananas-coach/scripts/coach_app.py --mode real history
```

Use Calendar revision history to restore eligible sessions, or explicitly ask
the skill to undo a change. Protected rollback creates a new version and keeps
completed, historical, and locked facts. Old imported revisions remain stored;
undo of pre-migration agent revisions is deferred.

Exception and post-run check-ins record fatigue, illness, gait change, symptoms,
and effort when supplied. Unreported observations remain unknown. Associations
show preceding sessions and elapsed time; they do not establish causation.
Confirmed weekly or alternating strength/mobility schedules survive migration.
Inspect or update them in Data & settings; optional manual strength entries are
available, but duplicate entry from Strong is not required. Coaching history
remains readable through the navigation link.

## Verification

```sh
make check                 # backend lint/types/unit tests + frontend checks/build
make test-integration      # PostgreSQL integration tests in garmin_test
python3 scripts/test_coach_skill_v2.py  # reviewed helper contract tests; no live writes
```

Browser acceptance uses an isolated demo database and built frontend on port
18000. Use a disposable demo environment, never real credentials or data:

```sh
./scripts/with-mode demo bash -c 'cd backend && uv run alembic upgrade head && uv run python -m app.cli seed-demo --calendar-preview'
make build
APP_PORT=18000 ./scripts/with-mode demo bash -c 'cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 18000'
# In another terminal:
PLAYWRIGHT_BASE_URL=http://127.0.0.1:18000 make test-e2e
```

The P0-A and P0-B suites use calendar-mode fixtures. Run the older legacy suite
against a separate ordinary demo seed. Browser and API requests use the same
origin and verify demo mode before mutations.

Browser tests refuse non-demo mode before mutations. They create synthetic
feedback/plans/manual sessions in the demo database. `scripts/verify-demo.py`
provides additional API acceptance checks; `scripts/smoke.py --mode real` is
read-only except for an intentionally rejected foreign-origin request.

Release outcomes and limitations are in [the release checklist](docs/release-checklist.md).
Never run tests with real data substituted for synthetic fixtures.

## Backups and coaching scope

`make backup` writes a private PostgreSQL/raw/profile archive with checksums,
excluding credentials. `coach snapshot` writes a privacy-filtered, versioned
training snapshot for the selected operation. The retained `make context` command
exports the legacy format. Restore only into a new target; commands are in [operations](docs/operations.md).

The reviewed `running_coach_kb/` loads selectively: guide, requested workflow,
and relevant topics/policies/sources. The AI coach must distinguish observed
response, research, and athlete-specific inference, cite actual evidence, and
state uncertainty. Summary-only records do not establish intrarun zones, drift,
or interval structure. FIT-based detail is available where verified streams,
workout matching, and calibration support it; route/weather adjustment remains
outside this MVP. No model or wearable can diagnose or
provide an injury guarantee. See [research scope](docs/research-integration.md),
[contracts](docs/contracts.md), [P0 implementation](docs/p0-implementation.md),
[release evidence](docs/release-checklist.md), and [handoff](docs/handoff.md).
