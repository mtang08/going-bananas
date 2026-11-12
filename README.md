# Going Bananas — local training analytics

A private, single-user local training dashboard built with React/TypeScript,
FastAPI, and PostgreSQL. It combines Garmin activity/recovery history with an
imported Strong lifting snapshot and a reviewed running research library. Strong
remains the lifting workflow; the app reads its CSV export and does not write
workouts back to Strong.

The AI running coach runs through the
[`going-bananas-coach` Codex skill](skills/going-bananas-coach/SKILL.md). It reads
live activities, recovery, check-ins, baseline comparisons, accepted plans, and
selected reviewed research; then saves validated two-week running prescriptions
or today's confirmation/adjustment directly into the app. No separate model API
key or dashboard chat is required. Routine sync, metrics, calendar rendering,
and labels use deterministic code and spend no model tokens.

## Daily and weekly use

1. Start the app at **http://127.0.0.1:8000** and sync Garmin in Data & settings
   when needed. Check actual observation coverage; a successful sync does not
   prove last night's sleep is available.
2. In Codex, invoke **`$going-bananas-coach review-week`**. The coach reviews
   actual training, response, strength placement, and selected KB evidence, then
   saves a complete rolling two-week running plan. Validation activates it
   automatically under the athlete's standing preference; no manual dated
   session entry or second routine acceptance is needed.
3. Each morning use **`$going-bananas-coach today`**, reporting current
   symptoms/function and energy. The coach starts from the saved session,
   retains the weekly strategy, and saves either a confirmation or a justified
   adjustment. Missing reports stay unknown. One poor wearable score does not
   automatically cancel training.
4. Inspect active prescriptions and revision diffs in the app. Runs sync as
   actuals; link an unambiguous actual to its planned session and record effort,
   modifications, and later response. The next review reads the same history.

The saved run anchor and Week A/B strength/mobility rotation project automatically.
Strong remains the lifting workflow. Legacy `local_rules.v1` recommendations
retain their own provenance/history; they are not AI prescriptions or a second
AI coaching entry point. Current scope is P0 running guidance from existing
summary data; detailed FIT/lap/HR-zone/drift analytics and further research
refinements are deferred. See [workflow and limits](docs/running-coach-workflow.md).

Historical runs receive a **programmatic, provisional** easy/quality/long
suggestion only when enough earlier comparable runs support it. The rule uses
relative whole-run distance, time, moving pace, and average heart rate over the
preceding 12 weeks. A heuristic long suggestion is limited to weekends. Missing
or conflicting data stays unknown; manual correction always wins. The app
spends no model tokens on individual activity labels. The activity detail shows
its short reason and limitations, including unmeasured route/weather and the
absence of heart-rate series or interval analysis.

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

Install or refresh the versioned skill from the repository:

```sh
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills/going-bananas-coach"
cp -R skills/going-bananas-coach/. "${CODEX_HOME:-$HOME/.codex}/skills/going-bananas-coach/"
```

Start a new Codex session if needed to refresh skill discovery, then invoke
`$going-bananas-coach review-week` or `$going-bananas-coach today`. The app must
be running in real mode for athlete coaching. The invoking Codex model supplies
the AI reasoning; no `OPENAI_API_KEY` or separate model runner is required.
These are manual invocations, not an installed coaching scheduler. Personal
proposal payloads and confirmed memory remain in private local storage.

The helper can inspect context/schema/history without generating advice:

```sh
python3 skills/going-bananas-coach/scripts/coach_app.py today
python3 skills/going-bananas-coach/scripts/coach_app.py schema
python3 skills/going-bananas-coach/scripts/coach_app.py inspect
```

To undo a revision, ask the skill to revert it, or use its documented
[`revert` command](skills/going-bananas-coach/references/app-access.md).
Rollback checks the current revision and records history. Exploratory or
read-only conversations do not activate a plan. Goals and strength configuration
remain explicit athlete decisions. Feature ideas remain in [the backlog](docs/backlog.md).

“No issues; usual energy” explicitly records no symptoms, normal gait, and usual
feeling. Unreported days remain unknown. Detailed check-ins support corrections,
effort, and notes. Associations show preceding sessions and elapsed time; they do
not establish what caused symptoms.

The alternating strength and mobility pattern is confirmed in the real
profile: Week A full-body strength Monday/Friday and required gym mobility
Wednesday; Week B full-body strength Tuesday/Saturday and required gym mobility
Thursday. Sunday mobility is optional in both weeks. Week A begins Monday,
November 9, 2026. Projection starts from the saved profile date, without
creating retrospective completion debt. The current real run-cycle anchor is
confirmed as November 10, 2026; read the live profile for later changes.
The recurring pattern generates dated calendar context automatically; no new
weekly plan entry is needed. An explicitly accepted dated plan takes precedence on its covered dates
and serves as an exception to recurrence. Manual drafts remain available for
those exceptions; acceptance is explicit. Actual off-cycle activities remain
observations. Optional manual strength entries are available, but duplicate
entry from Strong is not required. The older manual draft/acceptance API
requires exact-range replacement. Agent
revisions support rolling windows while preserving accepted dates outside the
window, existing session links, and immutable revision history.

## Verification

```sh
make check                 # backend lint/types/unit tests + frontend checks/build
make test-integration      # PostgreSQL integration tests in garmin_test
python3 scripts/test_coach_skill.py  # isolated helper contract tests; no live writes
```

Browser acceptance uses synthetic data only. Stop a running real app first,
start the demo app, then run the browser suite (Google Chrome is used):

```sh
./scripts/with-mode demo bash -c 'cd backend && uv run alembic upgrade head && uv run python -m app.cli seed-demo'
./scripts/with-mode demo python3 scripts/serve.py --dev
# In another terminal:
make test-e2e
```

To test an already-running isolated demo server on another port, use
`PLAYWRIGHT_BASE_URL=http://127.0.0.1:8019 make test-e2e`. Browser and API
requests use that same origin; the server must report demo mode.

Browser tests refuse non-demo mode before mutations. They create synthetic
feedback/plans/manual sessions in the demo database. `scripts/verify-demo.py`
provides additional API acceptance checks; `scripts/smoke.py --mode real` is
read-only except for an intentionally rejected foreign-origin request.

Release outcomes and limitations are in [the release checklist](docs/release-checklist.md).
Never run tests with real data substituted for synthetic fixtures.

## Backups and coaching scope

`make backup` writes a private PostgreSQL/raw/profile archive with checksums,
excluding credentials. `make context` writes a local privacy-filtered
`coach_context.v1` snapshot; nothing is submitted to a model. Restore only into a
new target; commands are in [operations](docs/operations.md).

The reviewed `running_coach_kb/` loads selectively: guide, requested workflow,
and relevant topics/policies/sources. The AI coach must distinguish observed
response, research, and athlete-specific inference, cite actual evidence, and
state uncertainty. Existing average HR and whole-run pace/distance/time support
P0 decisions; they do not establish intrarun zones, drift, interval structure,
or route/weather-adjusted adaptation. No model or wearable can diagnose or
provide an injury guarantee. See [research scope](docs/research-integration.md),
[contracts](docs/contracts.md), [P0 implementation](docs/p0-implementation.md),
[release evidence](docs/release-checklist.md), and [handoff](docs/handoff.md).
