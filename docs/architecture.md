# Architecture

Open the [visual architecture guide](architecture-map.html) in a browser for diagrams of the local system, training week, coaching decisions, and iPhone check-ins.

Read each directory’s `AGENTS.md` for entry points and [contracts.md](contracts.md) for field-level contracts.

Go serves the React app’s same-origin `/api/v1` in demo, test, and real mode. PostgreSQL stores each workspace separately. The supervisor starts the Go API, Vite in development, and a separate sync worker in real mode. [Startup supervisor](../scripts/serve.py) · [Operating procedures](operations.md)

## Go entry points

| Surface | Entry point |
| --- | --- |
| Desktop API and built React app | `going-bananas serve` registers handlers on `net/http` and binds to loopback. [Executable](../backend-go/cmd/going-bananas/main.go) · [HTTP composition](../backend-go/cmd/going-bananas/routes.go) |
| Worker and operator commands | The same executable dispatches `worker`, `sync`, migrations, preflight, imports, metrics, backup and restore. [Command dispatch](../backend-go/cmd/going-bananas/main.go) · [Operator CLI wrapper](../scripts/backend-cli) |
| Coaching | The dashboard runs a local Codex app-server with six coaching tools. The repo helper uses the Go coaching CLI for snapshots, queries and pending draft writes. [Dashboard launcher and tools](../backend-go/internal/coachdashboardhttp) · [Coaching CLI wrapper](../scripts/coach-cli) |
| iPhone check-ins | A separately bound Go gateway serves phone assets and forwards the scoped ingest request to the loopback API. [Gateway](../backend-go/cmd/phone-gateway) · [iPhone setup](iphone-setup.md) |
| PostgreSQL | Go uses pgx and generates named queries with sqlc where configured. The native baseline initializes fresh databases. Upgrades of older stamped schemas use the retained Alembic migration history. [SQL baseline and migration stamps](../backend-go/sql) · [sqlc configuration](../backend-go/sqlc.yaml) · [Migration command](../backend-go/internal/migratecli) · [Historical migrations](../backend/migrations) |

The Go API registers its routes in the server executable. Checked-in OpenAPI files generate TypeScript wire models, strict Go handlers for the base contract, and Go wire models for the calendar schema. Other route families use hand-written Go handlers and validation. [API schemas](../backend-go/api) · [Generator](../scripts/api-types.py) · [Rewrite readiness](go-rewrite-readiness.md)

- API data responses use `{schema_version, data_revision, mode, data}`. Error responses use `{error: {code, message, retryable, request_id, fields}}`.
- Writes require `X-Local-Request: 1`. The server rejects non-local origins when an `Origin` is supplied and binds to loopback only.
- Ordinary requests, metrics, imports, and calendar expansion run locally. An explicit send on Coach starts a Codex turn, and the dashboard reads the saved conversation and partial reply as they update. Coach tools read filtered snapshots and save pending proposals using the same services as the repo-local Codex skill. The athlete accepts changes on the proposal page.

## Write → refresh lifecycle

Go commands explicitly open write transactions and pass the same `pgx.Tx` through source changes and their required refresh callbacks. The planning and completion commands acquire the shared PostgreSQL advisory lock, apply the change, and call the applicable rematch, metric and prompt work before commit. An error in that work rolls back the command. Provider replay and phone check-ins also pass the transaction into their refresh work. Desktop completion and desktop check-in run exception detection in a separate transaction after the source write. [Calendar commands](../backend-go/internal/calendarhttp/commands.go) · [Completion handler](../backend-go/internal/completionhttp/handler.go) · [Source refresh](../backend-go/internal/metrics/refresh/source.go) · [Check-in store](../backend-go/internal/checkins/store.go)

Handlers and commands derive refresh scopes from the affected records. A date gains or loses activity coverage when the union of complete, fully enumerated activity intervals changes. Travel edits advance the data revision. The shared revision helper advances it once per write transaction. [Revision helper](../backend-go/internal/db) · [Metric refresh](../backend-go/internal/metrics/refresh)

Metric reads use current stored results or compute missing or outdated results in memory. In-memory results have a null ID. Server startup refreshes metrics and prompts. The workout progression views and weekly digest serve stored rows. After a metric configuration change, use `metrics-recompute` to refresh those rows. [Operating procedures](operations.md#reviewed-coaching-mvp)

Sleep, HRV and resting-HR corrections can affect a night's 60-day baseline and the seven-day summaries containing that night. With today's training windows already present, these writes refresh only the affected recovery subjects. Repeating complete activity coverage advances time-based prompts without recalculating metrics. Both paths can initialize the current day's training windows on rollover.

Marking a scheduled workout complete without a recording, or undoing that mark, updates the session assessment and prompts. For a session that contributes to hard-session spacing, the affected spacing windows share one read of workout history. A recording association change still triggers the broader refresh. Coach snapshots include self-reported lifting days with their planned slot when known. Measured duration and RPE remain unknown until supplied by a workout record.

A coaching snapshot pins the calendar version and a source fingerprint. A change to either can make a pending proposal stale. Accepting a proposal re-checks freshness and writes any calendar edits atomically in a new version.

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
- `scripts/with-mode MODE COMMAND` swaps the database name and `PRIVATE_DIR` for one command without editing `.env`. Use it for demo commands. `make test-go-integration` sets its own test mode and database URLs.
- `make start`, `make sync`, and `make migrate` follow the mode in `.env`. In real mode `make migrate` backs up first and stops if the backup fails; the daily launchd sync writes one backup per day and prunes old ones (see [operations.md](operations.md)).
- Never run tests, seeds, or experiments against real data. Credentials, raw files, and athlete payloads stay under `private/` and out of git.
