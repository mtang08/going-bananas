# Going Bananas — local training analytics

A private, single-user training dashboard with a React/TypeScript frontend,
a choice of Go or FastAPI backend, and PostgreSQL storage. It combines Garmin
activity and recovery history with an imported Strong lifting snapshot and a
reviewed running research library. Strong
remains the lifting workflow; the app reads its CSV export and does not write
workouts back to Strong.

The running coach uses the repo-local
[`going-bananas-coach` Codex skill](.codex/skills/going-bananas-coach/SKILL.md).
It reads compact training snapshots and verified research, then saves a **pending
changeset**. Review each change in the app before applying it. The dashboard,
imports, metrics, and validation run locally without model calls.

## Daily and weekly use

Frontend implementation conventions are in [the UI system guide](docs/ui-system.md).

Open **User guide** in the app for the Sunday, exception, race, and training-block
workflows and example coaching prompts. The same guide is maintained in
[docs/user-guide.md](docs/user-guide.md) and can be downloaded from the app.

1. Open **http://127.0.0.1:8000**. Home shows sync status, what needs attention,
   today's plan, projected weekly mileage, planned vs done, recorded sessions this week, and the training
   block. Record check-ins and actual effort there.
2. On Home, choose **Talk to coach**, **Start Sunday review**, or **Discuss today’s run**.
   Enter what changed and send your message. Use **Continue review** to return to
   the conversation and **New Sunday review** on the coach page when you are ready
   to start a fresh one.
3. Open **Review proposal** in the coach conversation or **Needs attention → Review** on Home. Valid session changes start checked. Uncheck any you want to skip,
   select any block or anchor changes, then choose **Accept selected**. Unselected session
   changes are rejected. Saving a draft leaves the accepted plan intact until you
   apply it from the proposal page.
4. Inspect accepted sessions and **Plan versions** in Calendar. Completed,
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

Use Sunday evening as the normal weekly coaching review and start it from Home.
Extra reviews are for material changes, symptoms, or new goals. Discuss adjustments in the same chat. The coach reuses the review context and
publishes once you agree or ask to save. Updates to an open draft keep its link and revision history.
Refresh and review the latest revision before accepting; selections reset when
the draft changes. Stale drafts need refreshed context, but keep their link.
Accepted or rejected proposals stay fixed; later plan changes use a new proposal.
Only one draft can be open at a time, including stale or invalid drafts. Use
**Discard proposal** on its review page to clear it and start fresh. Discarding
removes it from the open list and preserves its history; it does not change the
calendar. The coach checks for the active draft before submitting a new one.

Between Sunday reviews, a deterministic detector turns check-ins, post-run RPE against the session's intent, completions, and races into findings with a category, a severity, and evidence. One HRV, resting-HR, sleep, or pace value never raises a finding above **Logged**. Logged findings wait for the Sunday review. **Caution** or **Hold** findings put an exception-review prompt on Home; the coach then patches only the committed week (days 1–7), leaving day 8 onward provisional, with the smallest change, and each accepted patch is tracked until it is resolved, escalated, or superseded. A block ends with a benchmark (a time trial or a race) when the last result is about 6 weeks old or a race falls in it; the result drives the block review and anchor recalibration, and other blocks are judged on training indicators. The user guide has the prompts.

Strength stays in Strong; import its CSV snapshot in the local app. Confirm the
strength routine in Settings. New coaching changes always require explicit review.

FIT decoding supplies timer segments, laps, steps, streams, and watch RPE when
available. Source coverage, calibration, and stream quality determine whether a
metric can be assessed. Synthetic tests do not establish device support: local
Garmin sample decoding and timer/RPE comparisons have passed; split laps within one workout step and an omitted warm-up, recovery, or cool-down step are handled and verified on synthetic data; broader device coverage and non-worn-night behavior remain explicitly unverified. The app shows
unavailable or partial evidence rather than filling those gaps.

Strong sessions stay in the database. The app uses the preceding **18 calendar months** for current running context and has no Strength browsing page. The export has no verified weight unit or dumbbell convention-change date, so the app does not compare weights or derive PR targets across that change.

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
The desktop app listens on loopback. For offline morning ankle check-ins on an iPhone, follow the [private phone setup guide](docs/iphone-setup.md).

To start Going Bananas automatically in real mode when you sign in to your Mac,
open **Settings → Start Going Bananas when I log in**. Turning it off keeps the
current dashboard and worker running.

For development, `make dev` starts the API, the worker in real mode, and Vite at
http://127.0.0.1:5173. Use `./scripts/with-mode demo make dev` for a demo
workspace with a migrated database. Stop the running dashboard before switching
modes or changing between `make dev` and `make start`.

The dashboard, coaching helper, and operational CLI use `GOING_BANANAS_BACKEND`.
With the setting unset, demo and test use native Go and real uses the Python
reference backend. An explicit `go` or `python` selects that backend for the
command. Use the same selection for startup and commands that write to its
workspace. The real-mode switch is documented in [local operations](docs/operations.md#reviewed-coaching-mvp).

## Fresh setup

Development prerequisites include Python 3.12+, uv, Node.js 22+, npm, Go and PostgreSQL 17 tools.
The Go backend pins Go 1.27.4. Install that version, or use a Go installation that supports automatic toolchain selection.
`scripts/env.sh` recognizes the Homebrew locations on this Mac and otherwise
uses PATH. Dependencies are resolved in `backend/uv.lock` and
`frontend/package-lock.json` and `backend-go/go.sum`. Setup installs the pinned
Go generators and linter under `private/go-tools/bin/`.

```sh
make setup
make db-start
make seed-demo
./scripts/with-mode demo make build
./scripts/with-mode demo make start
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
./scripts/with-mode real make migrate
./scripts/with-mode real ./scripts/backend-cli sync
./scripts/with-mode real make build
./scripts/with-mode real make start
```

In real mode, **Sync now** is on Home's status strip and in Settings. `make sync`
runs a standalone sync for the mode configured in `.env`. Both start each
dataset at its most recent fully covered day and include that day to pick up
late uploads. A dataset without prior complete coverage starts with 14 days for
activities or seven for recovery. To request a specific historical window, pass
both dates:

```sh
./scripts/with-mode real ./scripts/backend-cli sync --start 2026-10-14 --end 2026-11-10
```

Activities and sleep/HRV/resting HR sync independently. A partial failure does
not discard successful records. Inspect status and coverage instead of assuming
that a successful connection means complete history. Source-invalid records
remain excluded and visibly affect coverage. Missing recovery observations are
unknown. Re-imports preserve source revisions and avoid double-counting.

When sync finds a new treadmill run, open its pace review from the sync panel.
Check the Garmin laps, enter a pace for each interval you want to correct, and
confirm to import the run. You can also confirm the recorded paces as shown.
Confirmation saves the run and triggers its metric calculations. Interval
corrections preserve the overall distance and pace calibrated on your watch.

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
./scripts/with-mode real ./scripts/backend-cli import-export /absolute/path/to/export.zip
./scripts/with-mode real ./scripts/backend-cli import-export /absolute/path/to/export.zip --apply
```

The original ZIP and parsed source bytes are preserved in the private raw store.
The export adds historical observations without replacing newer API summaries.
Observed export dates are marked as partial coverage, since an account snapshot
does not prove complete watch wear or provider history. Repeating the import is
safe: the verified replay created no new source revisions or canonical changes.
This parser is specific to the inspected Garmin export schema; the browser does
not accept arbitrary ZIPs.

## Google Calendar travel

The app reads the primary Google Calendar, read-only, to find trips from Gmail flight reservations and calendar entries with flight numbers and routes. It stores a reduced copy of each event: title, times and timezones, busy or free, your own response, a category, and up to four airport codes from the location. The request selects only the attendee `self` and `responseStatus` fields needed to retain your own response; it does not request descriptions, attendee names, or email addresses, and stores no raw locations or raw responses. Nothing from Google is written to logs.

For a personal Google account, start at [Google Auth Platform personal setup](https://console.cloud.google.com/auth/overview/personal). The autogenerated project name is fine. Enable the Google Calendar API, configure the consent screen for personal use, and create a Desktop OAuth client with the read-only scope. Connect once in real mode: save its JSON as `private/real/google-calendar-client.json` and run `chmod 600` on it. The token is written next to it with owner-only permissions. Neither file is included in backups.

```sh
./scripts/with-mode real ./scripts/backend-cli calendar-connect
./scripts/with-mode real ./scripts/backend-cli calendar-probe --days 120
```

`calendar-probe` prints a redacted summary (event types, timezones, and masked title shapes) for checking trip detection without exposing details. In real mode, **Sync calendar** under Settings → **Travel and Google Calendar** fetches 30 days back and 180 days ahead, marks events deleted in Google as removed, and re-detects trips. Detected trips wait for you to confirm, edit, or dismiss them, and a sync never overwrites your edits. You can also add a trip by hand. The coach sees confirmed and unconfirmed trips with dates, timezones, local flight times, and the access and availability you entered. When both ends of a flight use the same calendar zone, or a zone is missing, Settings labels the times as calendar times. Check the destination time zone in **Edit** before confirming. The coach can use the elapsed flight time and leaves overnight travel and time-zone shift unknown for that leg. App dates stay in your home timezone during trips.

Before migrating real mode to `0025_coach_output_v2`, accept any open coach draft you want to keep and copy any session notes you need. The migration discards open drafts and clears existing session notes. Back up, migrate, and restart the app before your first sync. See [the migration instructions](docs/operations.md).

To revoke access, remove the app under myaccount.google.com → Security → Third-party access. To reconnect, run `calendar-connect` again.

## Strong import

The inspected Strong CSV has already been imported into the real workspace.
For a later export, preview first and apply only after checking the source and
backup. Repeating identical bytes is idempotent:

```sh
./scripts/with-mode real ./scripts/backend-cli strong-import /absolute/path/to/strong_workouts.csv
./scripts/with-mode real ./scripts/backend-cli strong-import /absolute/path/to/strong_workouts.csv --apply
```

The original CSV and source rows are preserved privately. Source-local timestamps
have no timezone; duration timers over 24 hours remain visible as source text
but have unknown normalized duration. Same-day Garmin/manual strength candidates
are reported as ambiguous rather than silently counted twice. This importer
supports the inspected Strong format, not arbitrary CSVs.

## Feedback and planning

Dashboard chat needs a compatible Codex installation on the Mac running Going
Bananas and internet access for model replies. On **Coach**, choose **Sign in with
ChatGPT**, open the sign-in link, and return to the conversation. You can read the
saved conversation and use the calendar, check-ins, and proposals while the local
app and database are running, even if the coach connection is unavailable.

In a Codex session opened in this checkout, invoke `$going-bananas-coach` and describe the review you want. The reviewed skill lives in `.codex/skills/going-bananas-coach`. Select real mode for your own training and demo or test for rehearsal. [Coaching setup and backend selection](docs/operations.md#reviewed-coaching-mvp)

The helper can show its schema, create a filtered evidence snapshot, and read calendar history. Creating a snapshot saves its evidence in the selected database.

```sh
python3 .codex/skills/going-bananas-coach/scripts/coach_app.py --mode real schema
python3 .codex/skills/going-bananas-coach/scripts/coach_app.py --mode real snapshot --operation exception_review
python3 .codex/skills/going-bananas-coach/scripts/coach_app.py --mode real history
```

Use Calendar’s **Plan versions** to restore eligible sessions, or explicitly ask
the skill to undo a change. Protected rollback creates a new version and keeps
completed, historical, and locked facts. Old imported revisions remain stored;
undo of pre-migration agent revisions is deferred.

Exception and post-run check-ins record fatigue, illness, gait change, symptoms,
and effort when supplied. Unreported observations remain unknown. Associations
show preceding sessions and elapsed time; they do not establish causation.
Confirmed weekly or alternating strength/mobility schedules survive migration.
Inspect or update them in Settings.

## Verification

```sh
make check                 # docs, Python, Go and frontend checks
make check-go              # generated code, build, lint, and race-enabled tests
make check-go-vuln         # check the Go module against the current vulnerability database
make generate-api-types    # regenerate Go and React HTTP types and sqlc queries
make api-schema            # print the bundled OpenAPI contract
make test-proposal-go      # compare Python and Go with PostgreSQL, Home and Settings
make test-integration      # provision the isolated database and run PostgreSQL integration tests
make test-integration TESTS=tests/integration/test_proposals.py
python3 scripts/test_coach_skill_v2.py  # reviewed helper contract tests; no live writes
```

The proposal list and goal edit share a checked-in OpenAPI contract. Go and React
compile against its request and response types. `make check-api-types` also checks
sqlc output and works with PostgreSQL stopped. To exercise both compilers, run
`python3 scripts/rewrite/check_contract_rename.py`. It renames a proposal field
in a temporary copy and checks that both consumers fail to build.
The bundle collects the [checked-in HTTP contracts](backend-go/api) into one
OpenAPI document.

The native API, worker, coach commands, imports and metric commands share the
`going-bananas` executable. `scripts/backend-cli` runs the selected backend and
preserves its exit code. For example, refresh the synthetic demo workspace with
`./scripts/with-mode demo ./scripts/backend-cli metrics-refresh-today`.
The phone gateway runs on its separate listener.

The development proxy sends every API request to one local backend. For a
demo with a migrated database, run `./scripts/with-mode demo make dev`.
The Go server can also serve the built frontend from the same port.

`make test-proposal-go` compares HTTP responses and persisted goal, revision
and metric state on independent copies of the migrated test database. It also
runs competing-writer and rollback tests. A shared disposable schema exercises
the Go-backed UI with a 52-proposal fixture. Home renders the open, empty
and failed-list states, and Settings creates, edits and reloads a goal.
The default browser is installed Chrome. Set `PROPOSAL_HOME_ENGINE=chromium` for
Playwright's installed Chromium or `PROPOSAL_HOME_ENGINE=dom` for Vitest/jsdom.
For the dedicated external test cluster use `make test-proposal-go-external`.

The integration runner uses a checkout-local PostgreSQL cluster under
`private/integration-postgres/55439/` on `127.0.0.1:55439`. It provisions
`garmin_test` for app and ingestion tests and `mvp1_migration_test` for migration
fixtures. It sets the application mode and connection URLs for the test process
without loading `.env`. `make test-db-start` provisions the same cluster without
running tests. `make test-db-stop` stops it. If the port is occupied, set
`TEST_DATABASE_PORT` to a free port for each command. The app and test clusters
use separate ports and data directories.

For an existing dedicated integration cluster, export `TEST_DATABASE_URL` and
`MIGRATION_TEST_DATABASE_URL` as `postgresql+psycopg://` URLs for the two databases,
then run `make test-integration-external`. The runner verifies the loopback port
and database names before testing. Use only disposable synthetic data.

Browser acceptance uses an isolated demo database and built frontend on port
18000. Use a disposable demo environment, never real credentials or data:

```sh
make seed-demo
./scripts/with-mode demo make build
APP_PORT=18000 ./scripts/with-mode demo make start
# In another terminal:
PLAYWRIGHT_BASE_URL=http://127.0.0.1:18000 make test-e2e
```

The demo database must be fresh; on an empty synthetic database,
`seed-demo` seeds the calendar preview data. It refuses databases that already contain user data.

The P0-A, P0-B, and P1 exception suites run in that order against one fresh
calendar preview database. Browser and API requests use the same
origin and verify demo mode before mutations.

Browser tests refuse non-demo mode before mutations. They create synthetic
check-ins, proposals, findings, patches, and a block benchmark in the demo
database. `scripts/verify-demo.py`
provides additional API acceptance checks; `scripts/smoke.py --mode real` is
read-only except for an intentionally rejected foreign-origin request.

The coach browser test uses the same demo app and PostgreSQL with a scripted
Codex protocol fixture. For that test, start a fresh seeded demo with the
fixture server in place of the ordinary demo server.

```sh
GB_COACH_BROWSER_TEST=1 APP_PORT=18000 ./scripts/with-mode demo bash -c 'cd backend && PYTHONPATH=. uv run python ../e2e/coach_browser_server.py'
# In another terminal:
cd frontend
GB_COACH_BROWSER_TEST=1 NODE_PATH="$PWD/node_modules" PLAYWRIGHT_BASE_URL=http://127.0.0.1:18000 npx playwright test coach-chat.spec.ts
```

Release outcomes and limitations are in [the release checklist](docs/release-checklist.md).
Never run tests with real data substituted for synthetic fixtures.

## Backups and coaching scope

`make backup` writes a private PostgreSQL/raw/profile archive with checksums,
excluding credentials. `coach snapshot` writes a privacy-filtered, versioned
training snapshot for the selected operation. Restore only into a new target;
commands are in [operations](docs/operations.md).

The reviewed `running_coach_kb/` loads selectively: guide, requested workflow,
and relevant topics/policies/sources. The AI coach must distinguish observed
response, research, and athlete-specific inference, cite actual evidence, and
state uncertainty. Summary-only records do not establish intrarun zones, drift,
or interval structure. FIT-based detail is available where verified streams,
workout matching, and calibration support it; route/weather adjustment remains
outside this MVP. No model or wearable can diagnose or
provide an injury guarantee. See [research scope](docs/research-integration.md),
[contracts](docs/contracts.md), [architecture](docs/architecture.md),
[release evidence](docs/release-checklist.md), and [handoff](docs/handoff.md).
