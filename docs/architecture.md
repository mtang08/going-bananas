# Architecture

Read each directory’s `AGENTS.md` for entry points and [contracts.md](contracts.md) for field-level contracts.

## Layers

```
frontend/src (React, React Query, hash routing)
   -> same-origin /api/v1                          backend/app/main.py: local-only guard, error envelope
        backend/app/api/        validate input, call services, wrap results in the response envelope
        backend/app/services/   orchestration: calendar, proposals, snapshot, sync, matching, check-ins
        backend/app/read/       shared database queries and read models
        backend/app/metrics/    calculators, result storage and reads, and recomputation
        backend/app/domain/     pure calculations (no database, no framework)
        backend/app/adapters/   parse Garmin, Strong, and Google Calendar formats
        backend/app/*_models.py SQLAlchemy models, with schema changes in backend/migrations/versions/
   -> PostgreSQL (the only supported database)
```

- API data responses use `{schema_version, data_revision, mode, data}`. Error responses use `{error: {code, message, retryable, request_id, fields}}`.
- Writes require `X-Local-Request: 1`. The server rejects non-local origins when an `Origin` is supplied and binds to loopback only.
- `backend/tests/unit/test_layering.py` enforces the one-way rules: services, metrics, domain, and adapters may depend only on layers below the API. Domain code is framework independent and the default timezone literal has one home.
- Ordinary requests, metrics, imports, and calendar expansion never call a model. Coaching reasoning happens in the repo-local Codex skill, which reads a filtered snapshot and submits a pending proposal that the athlete accepts in the app.

## Write → refresh lifecycle

Source writes and the refreshes they trigger share a transaction.

1. A request handler, the sync worker, or the CLI changes source rows (activities, check-ins, completions, calendar revisions, planning rows, profile versions, recovery observations, Strong and manual workouts, coverage) through one SQLAlchemy session and commits.
2. The API and CLI call `services.derived.install()`. Its session listeners use the old and new values of changed rows to emit refresh scopes (`activity`, `checkin`, `strength`, `plan`, `manual_completion`, `date`, `since`, `coverage_date`, `recovery_dates`, `timezone`, `revision`). Planning-only rows and Google Calendar events, trips, and trip legs emit only `revision`. A date gains or loses activity coverage when the union of complete, fully enumerated activity intervals changes across the transaction.
3. At commit, the listeners take `db.global_write_lock` and bump `data_revision`. When the scopes require refresh, they rematch affected days, recompute metrics through `metrics/refresh.py`, and update prompts in the same transaction. A refresh failure rolls back the source write.
4. Metric GETs take the shared advisory lock and serve current stored results or compute missing results and results from an outdated configuration in memory. In-memory results have a null ID. `metrics-refresh-today` refreshes metrics and prompts at server startup. The workout-progression views and weekly digest serve stored rows. After a metric configuration change, use `metrics-recompute` to refresh those rows.

Sleep, HRV and resting-HR corrections can affect a night's 60-day baseline and the seven-day summaries containing that night. With today's training windows already present, these writes refresh only the affected recovery subjects. Repeating complete activity coverage advances time-based prompts without recalculating metrics. Both paths can initialize the current day's training windows on rollover.

Marking a scheduled workout complete without a recording, or undoing that mark, updates the session assessment and prompts. For a session that contributes to hard-session spacing, the affected spacing windows share one read of workout history. A recording association change still triggers the broader refresh. Coach snapshots include self-reported lifting days with their planned slot when known. Measured duration and RPE remain unknown until supplied by a workout record. The [completion benchmark](../backend/tests/integration/test_manual_completion_refresh.py) times the full API request and checks which metrics it recalculates.
5. The coach loop consumes those results: a snapshot pins the calendar version and a source fingerprint. A change to either can make a pending proposal stale. Accepting a proposal re-checks freshness and writes any calendar edits atomically in a new version.

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

- `APP_MODE` must be `demo`, `real`, or `test`, and `config.py` refuses a database whose name does not end in `_<mode>`.
- `scripts/with-mode MODE COMMAND` swaps the database name and `PRIVATE_DIR` for one command without editing `.env`. Use it for demo commands. `make test-integration` sets its own test mode and database URLs.
- `make start`, `make sync`, and `make migrate` follow the mode in `.env`. In real mode `make migrate` backs up first and stops if the backup fails; the daily launchd sync writes one backup per day and prunes old ones (see [operations.md](operations.md)).
- Never run tests, seeds, or experiments against real data. Credentials, raw files, and athlete payloads stay under `private/` and out of git.
