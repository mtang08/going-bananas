# Going Bananas — local training analytics

A private, single-user Garmin dashboard built with React/TypeScript, FastAPI,
Python, and PostgreSQL. Running and recovery data come from Garmin's official
Personal API and a validated historical Garmin account export. Lifting stays in Strong; its history is **not connected**, so the
app reports recorded strength sessions without treating missing records as
missed lifting. A future Strong CSV adapter is in [the backlog](docs/backlog.md).

The app provides weekly/rolling volume, recent activities and provenance,
recovery trends, quick editable check-ins, delayed symptom context, and a manual
continuing two-week plan/completion view. Metrics and weekly recaps are factual.
No model, research KB, or adaptive training prescription is active.

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
not accept arbitrary ZIPs, and Strong CSV import remains future work.

## Feedback and planning

“No issues; usual energy” explicitly records no symptoms, normal gait, and usual
feeling. Unreported days remain unknown. Detailed check-ins support corrections,
effort, and notes. Associations show preceding sessions and elapsed time; they do
not establish what caused symptoms.

The real run-cycle anchor and alternate strength schedule remain unconfirmed.
The UI therefore leaves the real calendar unassigned until you configure them.
Manual drafts preserve every-other-day running and twice-weekly strength;
acceptance is explicit. Actual off-cycle activities remain observations. Optional
manual strength entries are available, but duplicate entry from Strong is not
required. Replacing an accepted plan requires matching its entire date range;
partial overlaps are rejected to preserve other accepted sessions.

## Verification

```sh
make check                 # backend lint/types/unit tests + frontend checks/build
make test-integration      # PostgreSQL integration tests in garmin_test
```

Browser acceptance uses synthetic data only. Stop a running real app first,
start the demo app, then run the browser suite (Google Chrome is used):

```sh
./scripts/with-mode demo bash -c 'cd backend && uv run alembic upgrade head && uv run python -m app.cli seed-demo'
./scripts/with-mode demo python3 scripts/serve.py --dev
# In another terminal:
make test-e2e
```

Browser tests refuse non-demo mode before mutations. They create synthetic
feedback/plans/manual sessions in the demo database. `scripts/verify-demo.py`
provides additional API acceptance checks; `scripts/smoke.py --mode real` is
read-only except for an intentionally rejected foreign-origin request.

Release outcomes and limitations are in [the release checklist](docs/release-checklist.md).
Never run tests with real data substituted for synthetic fixtures.

## Backups and later coaching

`make backup` writes a private PostgreSQL/raw/profile archive with checksums,
excluding credentials. `make context` writes a local privacy-filtered
`coach_context.v1` snapshot; nothing is submitted to a model. Restore only into a
new target; commands are in [operations](docs/operations.md).

The later `running_coach_kb/` integration will selectively load the coaching
guide, daily/weekly workflow, and relevant topic sections/policies. Research prose
and uncertainty remain separate from dated athlete facts and live training data.
See [contracts](docs/contracts.md), [implementation plan](docs/implementation-plan.md),
[verification cases](docs/verification.md), and [handoff](docs/handoff.md).
