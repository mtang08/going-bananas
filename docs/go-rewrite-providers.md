# Workstream 2 · Provider ingestion and FIT

Go owns Garmin normalization, persistence, replay and the worker in real mode. Go also handles Strong imports, Google Calendar and trip reconciliation, and the phone check-in gateway. The initial decoder shipped on `go/providers` at `258167c`, followed by the replay work on `go/provider-replay`. [Go client](../backend-go/internal/garmin) · [Shared specification](go-backend-rewrite.md)

## Original decoder assignment

Port **downloaded ZIP bytes to application-level decoded FIT data**. Put the production decoder and its tests under `backend-go/internal/garmin/fit/`. Give it an in-memory entry point that accepts the same downloaded bytes as Python. Use the Go decoder version pinned in the existing probe. Stream 2 owns the corresponding Go module dependency and checksum change for this slice. [Python decoder and output types](https://github.com/mtang08/going-bananas/blob/7e759fb510ad828b044911dfa969fa845f7dd7da/backend/app/adapters/garmin/fit.py) · [Probe dependency](../backend-go/go.mod)

| Deliverable | Completion check |
| --- | --- |
| ZIP member selection, size checks while streaming, FIT integrity checks and stable errors | The same synthetic archives produce the same error codes for zero or multiple FIT members, an oversized member, corrupt ZIP and bad FIT CRC. |
| Typed session, laps, steps, timer intervals, streams, quality flags and filtered metadata | Compare the Go outputs to Python's `decode_fit_zip` on the same synthetic bytes. Cover pauses, duplicate timestamps, missing channels, alternate speed/altitude fields, lap intensity and workout targets. Preserve nulls, ordering and the FIT payload hash. Record the native library's actual version in decoder provenance. |
| Reproducible parity fixtures and an isolated test command | Keep the Python fixture builder as the reference. Assert that coordinates, device serials and other excluded fields stay out of normalized results. The port compared Python reference cases. Current checks use committed synthetic cases and the Go race suite. |

The existing Go probe compares primitive decoder messages. Passing it alone does not exercise the normalized values consumed by ingestion. This first deliverable needs synthetic files only. [Synthetic FIT builder](../backend/tests/fixtures/fit/synthetic.py) · [Decoder scenarios](https://github.com/mtang08/going-bananas/blob/7e759fb510ad828b044911dfa969fa845f7dd7da/backend/tests/unit/test_fit_decode.py)

### Stream 1 handoff

Pass the bytes from `garmin.Client.DownloadActivity` to `fit.DecodeZIP(archive []byte) (*fit.DecodedFit, error)`. The import path is `github.com/mtang08/going-bananas/backend-go/internal/garmin/fit`. The result includes the uncompressed FIT SHA-256, the header profile version, and the native decoder version. Read a failure code with `errors.As` into a `*fit.DecodeError`. The native worker persists decoded files through the transactional ingestion path described below. [Entry point](../backend-go/internal/garmin/fit/decode.go) · [Observation types](../backend-go/internal/garmin/fit/types.go)

The normalized comparison rebuilt deterministic archives, called Python’s `decode_fit_zip`, and compared every result field or error code with the Go decoder. The focused Go test uses the checked-in reference fixtures. [Normalized fixture](../backend-go/internal/garmin/fit/testdata/normalized.json) · [Go parity test](../backend-go/internal/garmin/fit/parity_test.go)

The native decoder accepts stored, Deflate, BZIP2 and LZMA members. A local-header filename that differs from the central directory produces `bad_zip`. The activity export reader uses the same member checks and retains the original archive and member hashes alongside each normalized row. [ZIP reader](../backend-go/internal/garmin/zipinput/reader.go) · [Activity normalization tests](../backend-go/internal/garmin/activities_test.go)

Run the checks from a configured checkout with Go on `PATH`.

```sh
(cd backend-go && go test -race -count=1 ./internal/garmin/fit)
make check-go
```

## Provider scope and integration

Stream 2 owns Garmin JSON and export normalization, FIT reprocessing, Strong preview/apply, Google Calendar event and trip reconciliation, and provider job fetch/retry/checkpoint logic. Keep provider-specific tests and fixtures with these packages. Cover precedence in either import order, repeated delivery, partial or failed pages, and preserved manual trip edits. [Garmin/export precedence](https://github.com/mtang08/going-bananas/blob/7e759fb510ad828b044911dfa969fa845f7dd7da/backend/tests/integration/test_export_precedence.py) · [FIT reprocessing](https://github.com/mtang08/going-bananas/blob/7e759fb510ad828b044911dfa969fa845f7dd7da/backend/tests/integration/test_fit_reprocess.py) · [Strong import](https://github.com/mtang08/going-bananas/blob/7e759fb510ad828b044911dfa969fa845f7dd7da/backend/tests/integration/test_strong_import.py) · [Google Calendar](https://github.com/mtang08/going-bananas/blob/7e759fb510ad828b044911dfa969fa845f7dd7da/backend/tests/integration/test_gcal_sync.py)

The provider transaction passes typed observations, provenance, affected source identities and dates, and the job checkpoint to shared persistence and refresh. A replay unit commits source history, the winning values and its checkpoint together. Stream 1 owns the shared router, schema, Makefile and supervisor. The real cutover keeps one worker active at a time. [Cutover and rollback](go-backend-rewrite.md#data-handoff-and-rollback)

## Original replay assignment

The assignment followed a Garmin activity page, FIT archive or export through normalized observations, field precedence, persisted source history and the job checkpoint. This was the original verification plan. The Python fixtures and implementation are historical references. The current native commands follow below.

1. The FIT comparison identified LZMA and local-header filename differences. The port resolved them and normalized Garmin JSON, FIT and export inputs with typed provenance and explicit missing values.
2. The original test ran API-first and export-first replays in independently migrated schemas, compared the canonical activity and source history with Python, and checked that duplicate input preserved identity and provenance.
3. The failure scenario injected an error after a source write, restarted the job, and checked the durable state, checkpoint and affected IDs and dates, including a partial page.
4. The replay matrix served as the handoff for the worker and its affected-date refresh.

[Ingestion and precedence tests](https://github.com/mtang08/going-bananas/blob/7e759fb510ad828b044911dfa969fa845f7dd7da/backend/tests/integration/test_export_precedence.py) · [Job implementation](https://github.com/mtang08/going-bananas/blob/7e759fb510ad828b044911dfa969fa845f7dd7da/backend/app/services/sync.py)

## Continuation prompt

> The existing provider lead plans, integrates and reviews the work. Assign new or reassigned implementation and verification to workers using `gpt-6.2-sol`. Start from the integrated Go candidate and use native tests and committed synthetic fixtures for changes to normalization, persistence, replay or recovery. Report the commands run, comparison results, commits and any remaining integration work.

## Running a synthetic activity replay

The two-order PostgreSQL comparison used independent Alembic-migrated schemas for Python and Go. It checked immutable raw payload hashes, winning values and source links, the FIT observations and the job checkpoint. It also interrupted the checkpoint write, restarted the same job and checked retained-file reprocessing after corruption.

For a downloaded JSON page, put this manifest beside the page and FIT ZIP. Supply a new job UUID for each independent replay. Subsequent pages increment `index` from zero. Use `export` with an account-export ZIP filename to import its activity summaries. A FIT-only delivery can identify an existing source account with `account_scope` and activity IDs in `fit`.

```json
{
  "job_id": "c5a44696-4094-4dc9-95e7-cfe7172e448b",
  "index": 0,
  "final": true,
  "activity_page": "activities.json",
  "fit": {"70": "activity.zip"}
}
```

Build once, then run the manifest in the selected synthetic workspace. The CLI accepts test and demo database names with matching mode suffixes.

```sh
(cd backend-go && go build -o ../private/garmin-replay ./cmd/garmin-replay)
./scripts/with-mode demo private/garmin-replay -page private/fixtures/delivery.json
./scripts/with-mode demo private/garmin-replay -reprocess "$ACTIVITY_UUID"
```

The synthetic replay entry point is `replay.Apply(ctx, pool, privateDir, page)`. It takes previously fetched inputs, including API records or `ScanExport` results and optional FIT bytes keyed by Garmin activity ID. It returns cumulative counters, next page, offset, and the changed activity IDs and dates for this delivery. A local-date move includes both dates. The checkpoint also retains the job-wide union of affected dates. The terminal status is `partial` when the job has rejected records or failed FIT attempts. A duplicate committed page returns its checkpoint with empty change sets. A changed redelivery or skipped page index fails.

The integrated native worker handles scheduling, unconfirmed treadmill runs, coverage and downstream refresh. The standalone command uses its own replay job dataset. It imports the activity portion of an account export. [Replay transaction](../backend-go/internal/garmin/replay/page.go) · [Native replay package](../backend-go/internal/garmin/replay)

## Strong workout CSV import

Preview a Strong export in the selected workspace, then apply the same file. The database name must match the explicit mode. Preview validates every row and compares source identities against PostgreSQL without creating a batch, a raw file, or a workout. The command emits a JSON summary and the IDs and local dates of changed workouts.

```sh
./scripts/with-mode demo ./scripts/backend-cli strong-import private/fixtures/strong.csv
./scripts/with-mode demo ./scripts/backend-cli strong-import private/fixtures/strong.csv --apply
```

`strong.Import(ctx, pool, privateDir, csvPath, apply)` preserves the exact source strings and set order. Apply retains the immutable CSV before committing its SHA-256, a source record for each distinct workout revision, and the batch outcome in one database transaction. A changed workout stays linked to its original canonical sets and enters revision conflict for review. Manual completions and recorded RPE keep their workout IDs. Each changed workout triggers matching, metric recomputation and prompt generation within the import transaction. Repeated files create an import batch while preserving the existing workout and source identities. Timezone, weight units and the dumbbell-weight convention remain unknown. A rollback can leave an unreferenced immutable file, which a retry verifies and reuses.

Run the Go parser tests from the repository root.

```sh
(cd backend-go && go test -race ./internal/strong)
```

The database comparison exercised read-only preview, first import, duplicate and changed exports, manual associations, rollback after the workouts were written, restart, competing import processes, and mixed-account rejection. [Scanner](../backend-go/internal/strong/scan.go) · [Transaction](../backend-go/internal/strong/import.go) · [Native Strong package](../backend-go/internal/strong)

## Google Calendar replay and trip reconciliation

`travel.Apply(ctx, pool, delivery)` accepts a fetch timestamp and the complete sequence of Google Calendar list responses. On every page after the first, include the request token as `page_token`. The final page has no next token. The decoder verifies the chain before treating absent events in the fetch window as removed. The window runs from 30 days before to 180 days after the fetch date in the athlete's timezone.

Replay commits event versions, detected trips, ordered flight legs, the data revision and the import batch together under the shared writer lock. A repeated window preserves event versions and trip identities. Changed or cancelled flights flag trips the athlete edited and preserve their dates, destination and availability. A failed fetch records a failed batch. A database failure rolls the reconciliation back. [Transaction](../backend-go/internal/travel/replay.go) · [Trip reconciliation](../backend-go/internal/travel/reconcile.go)

The PostgreSQL comparison used a Python reference on a separate schema. The native replay also accepts a local synthetic manifest.

```sh
(cd backend-go && go build -o ../private/gcal-replay ./cmd/gcal-replay)
./scripts/with-mode test private/gcal-replay -input private/fixtures/calendar-window.json
```

The manifest has the following form. An empty terminal page completes a window, so replay it only when the captured fetch is complete.

```json
{"now":"2026-11-22T15:00:00Z","pages":[{"items":[],"nextPageToken":"p2"},{"page_token":"p2","items":[]}]}
```

### Travel HTTP integration

Mount `travelhttp.Handler{Pool: pool, Mode: mode, PrivateDir: dir, Provider: provider}.Register(mux)` on the central mux behind the application's host, origin and write guards. It serves the three Google Calendar reads/writes under `/api/v1/google-calendar`, the event-category patch, and trip list/create/patch under `/api/v1/trips`. Set the request ID response header before dispatch. Each response carries the revision observed with its data.

The injected provider supplies connection status and complete primary-calendar pages. Sync uses the existing PostgreSQL fetch lock, releases database connections during the fetch, and uses the captured window for reconciliation. Its public route requires real mode. The original comparison exercised all seven routes using loopback fixtures in isolated schemas, including the real-mode route contract. [Native handlers](../backend-go/internal/travelhttp/handler.go) · [Contract](../backend-go/api/travel.openapi.json)

## Native Garmin sync jobs

`providerjobs.Runner.RunOne(ctx)` claims one due job under the same PostgreSQL session lock as Python. `Work(ctx)` also enqueues catch-up windows in the athlete's timezone, drains the queue and polls until cancellation. The runner fetches activity pages and bounded sleep, HRV and resting-heart-rate windows outside the writer transaction. It commits source records, winning observations, pending treadmill reviews, counters and page progress together. A short retry waits locally. A longer Retry-After persists a due time and releases the worker. Coverage records distinguish completed enumeration, rejected records and failures. [Queue and runner](../backend-go/internal/providerjobs) · [Source importer](../backend-go/internal/garmin/replay/job.go)

For the synthetic worker, build `backend-go/cmd/provider-jobs`. It supports `-dataset activities -start YYYY-MM-DD -end YYYY-MM-DD enqueue`, `run` for one claim and `worker` for catch-up and polling. The command requires a local `garmin_test` connection, a test private directory and a loopback fixture at `GARMIN_PERSONAL_API_BASE_URL`. The original scenario compared persisted state against the Python worker, interrupted an activity page and restarted in a fresh process.

The unified executable runs `going-bananas sync [--start YYYY-MM-DD] [--end YYYY-MM-DD]` or `going-bananas worker` in the selected real workspace. The sync command reports job IDs and individual outcomes. The worker uses the existing Garmin key, private token cache and PostgreSQL claim lock. `garmincli.SourceRefresh(time.Now, refresh.Runs)` rematches affected days, computes metrics and regenerates prompts within the source transaction. FIT downloads get a separate best-effort transaction per run. [Worker and CLI](../backend-go/internal/garmincli) · [Native worker tests](../backend-go/internal/providerjobs/runner_test.go)

Preview an account export with `going-bananas import-export ARCHIVE` and apply it with `--apply`. Import stores the original archive, canonical activities, supported recovery observations and observed coverage in one database transaction. The synthetic comparison covered preflight, apply and duplicate delivery. [Export importer](../backend-go/internal/garmin/replay/import_export.go)

### FIT maintenance commands

Run these commands from the repository root. Replace the date and optional activity ID with the desired selection. [FIT CLI](../backend-go/internal/fitcommand)

```sh
./scripts/with-mode real ./scripts/backend-cli fit-backfill --since 2026-01-01
./scripts/with-mode real ./scripts/backend-cli fit-reprocess --since 2026-01-01
```

Backfill downloads files immediately and commits one activity at a time. It selects running activities whose stored local date meets the cutoff and whose FIT status is `not_fetched` or `decode_error`. It prints attempted, decoded, unavailable and failed counts. The command requires real mode and the existing Garmin credential configuration.

Reprocessing uses retained ZIPs in the selected private directory. It selects previously decoded activities with an older or missing decoder version, using midnight in the athlete’s time zone as the inclusive start cutoff. The default dry run rolls back the batch. Append `--apply` to commit it and refresh affected metrics in one transaction. Adding `--activity-id UUID` selects that activity regardless of date, although `--since` is still required. Reprocessing also supports demo and test mode. The CLI behavior was compared with the Python reference on synthetic PostgreSQL. [Selection and transaction logic](../backend-go/internal/garmin/replay/fit_batch.go) · [FIT command](../backend-go/internal/fitcommand)

### Google Calendar provider and travel contracts

Pass `googlecalendar.New(privateDir)` to the travel HTTP service. In the selected real workspace, `going-bananas calendar-connect [--no-browser]` uses loopback OAuth consent with PKCE and writes a private token. `going-bananas calendar-probe --days 60` prints masked calendar and event diagnostics. Both commands require explicit real mode for operation. The client checks file permissions, rotates expired or rejected credentials and follows event pages until it has a complete window. Use `NewWithConfig` for a synthetic HTTP endpoint and clock. From the repository root, run `make check-api-types` to verify the [Go-owned seven-route contract](../backend-go/api/travel.openapi.json) against its [generated TypeScript](../frontend/src/api/generated/travel.ts). [Client and tests](../backend-go/internal/googlecalendar)

### Phone and check-in integration

Register `checkinhttp.Handler{Store: checkins.NewStore(pool, nil, refresh.Runs), Mode: mode}` with the guarded API mux. It serves `PUT /api/v1/phone/checkins/{entry_id}`, `GET` and `POST /api/v1/v2/checkins`, and `PATCH /api/v1/v2/checkins/{checkin_id}`. A duplicate phone submission returns its receipt without writing another observation or rerunning detection. The private phone gateway forwards its single write route to the local API. The original synthetic comparison covered duplicate receipts, gateway guards, history, concurrency, metric refresh, prompts and rollback. [Check-in service](../backend-go/internal/checkins) · [Phone setup](iphone-setup.md)

### Workspace backup and restore

Run `going-bananas backup OUTPUT.tar.gz` with the intended `DATABASE_URL` and `PRIVATE_DIR`. Restore with `going-bananas restore OUTPUT.tar.gz --target-database-name NEW_DATABASE --target-private-dir NEW_DIRECTORY`. Both targets must be new. The version-one archive contains a PostgreSQL custom-format dump, an allowlisted private file tree and SHA-256 checksums. The command uses the installed PostgreSQL client tools. The rehearsal cross-restored synthetic archives between Go and Python. [Backup package](../backend-go/internal/backup)

### Additional HTTP registrations

The main server supplies the local Host, Origin and write guards to all three registries.

| Registry | Routes and behavior | Synthetic verification |
| --- | --- | --- |
| `synchttp.New(pool, mode, privateDir).Register(mux)` | Sync status, job lookup, enqueue, treadmill preview and confirmation. Confirmation persists the reviewed summary, FIT and lap paces with its queue and metric updates. | [Native sync handlers](../backend-go/internal/synchttp) |
| `httpapi.ExceptionRoutes{Pool: pool, Mode: mode}.Register(mux)` | Reading findings runs detection. Dismissal and patch resolution validate the expected version and update linked findings in the same transaction. For a read-only projection, call `exceptions.View(ctx, tx, now, include)`. | [Detector and projection tests](../backend-go/internal/exceptions) |
| `loginstartup.Local(absoluteRepoRoot, mode).Register(mux)` | Read or update the macOS login-startup preference. The OS adapter checks the current checkout's launch agent and writes its plist atomically. | From `backend-go`, run `go test -race ./internal/loginstartup` for the simulated launchd cases. |

The browser reads the same wire types described by the native route fragments. The sync contract includes nullable provider dates, job checkpoints and counters, reviewed laps and confirmation receipts. The check-in and exception contracts describe duplicate receipts, historical reads, versioned actions and request guard failures. [Sync](../backend-go/api/sync.openapi.json) · [Check-ins and phone](../backend-go/api/checkins.openapi.json) · [Exceptions and login startup](../backend-go/api/exception-startup.openapi.json)

### Fresh synthetic dashboard

From the repository root, run the native migration and fixture through the same demo target.

```sh
./scripts/with-mode demo make seed-demo
```

The seed command takes no arguments and requires demo mode, a database name ending in `_demo` and a private directory that resolves to a directory named `demo`. It creates synthetic activity history, recovery observations, training plans, check-ins and travel events in one transaction and prints table counts. The unified CLI dispatches directly to the seed package. [Seed command](../backend-go/internal/demoseed/command.go)

The fresh dashboard and same-day replay comparison matched all 183 current metric results. Python stored 34 superseded rows during the fresh seed and five more during the same-day replay, from intermediate states within its seed transactions. Go stores the resulting current rows. [Native seed package](../backend-go/internal/demoseed)
