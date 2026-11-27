# Architecture

Open the [visual architecture guide](architecture-map.html) in a browser for diagrams of the local system, training week, coaching decisions, and iPhone check-ins.

Read each directory’s `AGENTS.md` for entry points and [contracts.md](contracts.md) for field-level contracts.

Go is the default backend in demo and test. Real mode defaults to Python until the owner selects Go. Both serve the React app’s same-origin `/api/v1` and use PostgreSQL. The supervisor starts the selected API, Vite in development, and a separate sync worker in real mode. [Startup supervisor](../scripts/serve.py) · [Operating procedures](operations.md)

## Go entry points

| Surface | Entry point |
| --- | --- |
| Desktop API and built React app | `going-bananas serve` registers handlers on `net/http` and binds to loopback. [Executable](../backend-go/cmd/going-bananas/main.go) · [HTTP composition](../backend-go/cmd/going-bananas/routes.go) |
| Worker and operator commands | The same executable dispatches `worker`, `sync`, migrations, preflight, imports, metrics, backup and restore. [Command dispatch](../backend-go/cmd/going-bananas/main.go) · [Backend selector](../scripts/backend-cli) |
| Coaching | The dashboard runs a local Codex app-server with six coaching tools. The repo helper uses the selected backend’s coaching CLI for snapshots, queries and pending draft writes. [Dashboard launcher and tools](../backend-go/internal/coachdashboardhttp) · [CLI selector](../scripts/coach-cli) |
| iPhone check-ins | A separately bound Go gateway serves phone assets and forwards the scoped ingest request to the loopback API. [Gateway](../backend-go/cmd/phone-gateway) · [iPhone setup](iphone-setup.md) |
| PostgreSQL | Go uses pgx and generates named queries with sqlc where configured. The native baseline initializes fresh databases. Upgrades of older stamped schemas use historical Alembic migrations. [SQL baseline and migration stamps](../backend-go/sql) · [sqlc configuration](../backend-go/sqlc.yaml) · [Migration command](../backend-go/internal/migratecli) |

The Go API registers all 81 reference operations. Checked-in OpenAPI files generate TypeScript wire models, strict Go handlers for the base contract, and Go wire models for the calendar schema. Other route families use hand-written Go handlers and validation. [API schemas](../backend-go/api) · [Generator](../scripts/api-types.py) · [Rewrite readiness](go-rewrite-readiness.md)

- API data responses use `{schema_version, data_revision, mode, data}`. Error responses use `{error: {code, message, retryable, request_id, fields}}`.
- Writes require `X-Local-Request: 1`. The server rejects non-local origins when an `Origin` is supplied and binds to loopback only.
- The Python reference uses FastAPI handlers over services, shared reads, metrics, domain rules, and provider adapters. SQLAlchemy models and Alembic migrations describe its persistence. The reference layering test checks those Python dependency rules. [Python API](../backend/app/api) · [Layering test](../backend/tests/unit/test_layering.py)
- Ordinary requests, metrics, imports, and calendar expansion run locally. An explicit send on Coach starts a Codex turn, and the dashboard reads the saved conversation and partial reply as they update. Coach tools read filtered snapshots and save pending proposals using the same services as the repo-local Codex skill. The athlete accepts changes on the proposal page.

## Write → refresh lifecycle

Go commands explicitly open write transactions and pass the same `pgx.Tx` through source changes and their required refresh callbacks. The planning and completion commands acquire the shared PostgreSQL advisory lock, apply the change, and call the applicable rematch, metric and prompt work before commit. An error in that work rolls back the command. Provider replay and phone check-ins also pass the transaction into their refresh work. Desktop completion and desktop check-in preserve the reference’s separate exception-detection transaction after the source write. [Calendar commands](../backend-go/internal/calendarhttp/commands.go) · [Completion handler](../backend-go/internal/completionhttp/handler.go) · [Source refresh](../backend-go/internal/metrics/refresh/source.go) · [Check-in store](../backend-go/internal/checkins/store.go)

The Python reference uses a SQLAlchemy session and flush/commit listeners to collect source changes and trigger derived refresh. Its lifecycle remains relevant while real mode uses Python and for cross-language comparisons. [Derived listeners](../backend/app/services/derived.py)


1. A request handler, the sync worker, or the CLI changes source rows (activities, check-ins, completions, calendar revisions, planning rows, profile versions, recovery observations, Strong and manual workouts, coverage) through one SQLAlchemy session and commits.
2. The API and CLI call `services.derived.install()`. Its session listeners use the old and new values of changed rows to emit refresh scopes (`activity`, `checkin`, `strength`, `plan`, `manual_completion`, `date`, `since`, `coverage_date`, `recovery_dates`, `timezone`, `revision`). Planning-only rows and Google Calendar events, trips, and trip legs emit only `revision`. A date gains or loses activity coverage when the union of complete, fully enumerated activity intervals changes across the transaction.
3. At commit, the listeners take `db.global_write_lock` and bump `data_revision`. When the scopes require refresh, they rematch affected days, recompute metrics through `metrics/refresh.py`, and update prompts in the same transaction. A refresh failure rolls back the source write.
4. Metric GETs take the shared advisory lock and serve current stored results or compute missing results and results from an outdated configuration in memory. In-memory results have a null ID. `metrics-refresh-today` refreshes metrics and prompts at server startup. The workout-progression views and weekly digest serve stored rows. After a metric configuration change, use `metrics-recompute` to refresh those rows.

Sleep, HRV and resting-HR corrections can affect a night's 60-day baseline and the seven-day summaries containing that night. With today's training windows already present, these writes refresh only the affected recovery subjects. Repeating complete activity coverage advances time-based prompts without recalculating metrics. Both paths can initialize the current day's training windows on rollover.

Marking a scheduled workout complete without a recording, or undoing that mark, updates the session assessment and prompts. For a session that contributes to hard-session spacing, the affected spacing windows share one read of workout history. A recording association change still triggers the broader refresh. Coach snapshots include self-reported lifting days with their planned slot when known. Measured duration and RPE remain unknown until supplied by a workout record. The [completion benchmark](../backend/tests/integration/test_manual_completion_refresh.py) times the full API request and checks which metrics it recalculates.
In both backends, a coaching snapshot pins the calendar version and a source fingerprint. A change to either can make a pending proposal stale. Accepting a proposal re-checks freshness and writes any calendar edits atomically in a new version.

## Metric identity

A stored result is identified by `metric_id`, `method_version`, and `subject_key`, plus three hashes:

- `method_version` (for example `v1`) names the calculation semantics. A change of meaning needs a new version. Rows of the old version stay.
- `config_hash` is the SHA-256 of the metric's canonical config JSON. Configs are stored in `metric_configs`. A config change produces a new hash and therefore new rows.
- `anchor_set_hash` represents the anchors used by the calculation, including each anchor's kind, key, and content hash. It is null when no anchors are used.
- `dependency_hash` covers the source references, config hash, anchor-set hash, timezone, and the calculator's own dependency hash. A result whose provenance is incomplete is stored as `invalid` with reason `MISSING_PROVENANCE` and no value.

Two unique indexes enforce this: `uq_metric_results_identity` (all identity fields, with a null `anchor_set_hash` indexed as an empty string) and `uq_metric_results_current` (one `is_current` row per metric, version, and subject). Upserting an identity that already exists marks that row current. A different identity keeps the previous row with `is_current = false`. Current-result reads filter on `is_current` and the registered method version.

## Modes

| Mode | Database | Private directory | Use |
| --- | --- | --- | --- |
| `demo` | `garmin_demo` | `private/demo` | Synthetic data, browser acceptance, `make seed-demo` |
| `test` | `garmin_test`, `mvp1_migration_test` | `private/integration-postgres/<port>/` with the managed runner | App tests use test transactions. Migration tests use isolated schemas. |
| `real` | `garmin_real` | `private/real` | The athlete's data; `make start` also runs the sync worker |

- `APP_MODE` must be `demo`, `real`, or `test`, and each server requires the database name to end in `_<mode>`.
- `scripts/with-mode MODE COMMAND` swaps the database name and `PRIVATE_DIR` for one command without editing `.env`. Use it for demo commands. `make test-integration` sets its own test mode and database URLs.
- `make start`, `make sync`, and `make migrate` follow the mode in `.env`. In real mode `make migrate` backs up first and stops if the backup fails; the daily launchd sync writes one backup per day and prunes old ones (see [operations.md](operations.md)).
- Never run tests, seeds, or experiments against real data. Credentials, raw files, and athlete payloads stay under `private/` and out of git.
