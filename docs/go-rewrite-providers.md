# Workstream 2 · Provider ingestion and FIT

**Owner:** the second Astra session. **First delivery:** `go/providers` at `258167c`. **Continuation branch:** `go/provider-replay`. The native Garmin HTTP client is already in `main` at `dc15070`. It handles authentication/cache reuse, activity and recovery reads, pagination and FIT downloads. Python still normalizes and persists the data. [Go client](../backend-go/internal/garmin) · [Shared specification](go-backend-rewrite.md)

## First independent assignment

Port **downloaded ZIP bytes to application-level decoded FIT data**. Put the production decoder and its tests under `backend-go/internal/garmin/fit/`. Give it an in-memory entry point that accepts the same downloaded bytes as Python. Use the Go decoder version pinned in the existing probe. Stream 2 owns the corresponding Go module dependency and checksum change for this slice. [Python decoder and output types](../backend/app/adapters/garmin/fit.py) · [Probe dependency](../scripts/rewrite/fit/go.mod)

| Deliverable | Completion check |
| --- | --- |
| ZIP member selection, size checks while streaming, FIT integrity checks and stable errors | The same synthetic archives produce the same error codes for zero or multiple FIT members, an oversized member, corrupt ZIP and bad FIT CRC. |
| Typed session, laps, steps, timer intervals, streams, quality flags and filtered metadata | Compare the Go outputs to Python's `decode_fit_zip` on the same synthetic bytes. Cover pauses, duplicate timestamps, missing channels, alternate speed/altitude fields, lap intensity and workout targets. Preserve nulls, ordering and the FIT payload hash. Record the native library's actual version in decoder provenance. |
| Reproducible parity fixtures and an isolated test command | Keep the Python fixture builder as the reference. Assert that coordinates, device serials and other excluded fields stay out of normalized results. Run focused Go race tests, Python reference cases and the project checks. |

The existing Go probe compares primitive decoder messages. Passing it alone does not exercise the normalized values consumed by ingestion. This first deliverable needs synthetic files only. [Synthetic FIT builder](../backend/tests/fixtures/fit/synthetic.py) · [Decoder scenarios](../backend/tests/unit/test_fit_decode.py) · [Existing probe](../scripts/rewrite/fit/check.py)

### Stream 1 handoff

Pass the bytes from `garmin.Client.DownloadActivity` to `fit.DecodeZIP(archive []byte) (*fit.DecodedFit, error)`. The import path is `github.com/mtang08/going-bananas/backend-go/internal/garmin/fit`. The result includes the uncompressed FIT SHA-256, the header profile version, and the native decoder version. Read a failure code with `errors.As` into a `*fit.DecodeError`. The Python worker continues to own ingestion and persistence. [Entry point](../backend-go/internal/garmin/fit/decode.go) · [Observation types](../backend-go/internal/garmin/fit/types.go)

The normalized comparison rebuilds deterministic archives, calls Python’s `decode_fit_zip`, and compares every result field or error code with the Go decoder. The SDK version identifies each implementation. Pass `--update` to the comparison to refresh the checked-in reference after a deliberate contract change. The focused Go test can use the fixtures on its own. [Normalized comparison](../scripts/rewrite/fit/check_normalized.py) · [Go parity test](../backend-go/internal/garmin/fit/parity_test.go)

The native decoder accepts stored, Deflate, BZIP2 and LZMA members. A local-header filename that differs from the central directory produces `bad_zip`. The activity export reader uses the same member checks and retains the original archive and member hashes alongside each normalized row. [ZIP reader](../backend-go/internal/garmin/zipinput/reader.go) · [Activity reference comparison](../scripts/rewrite/check_garmin_activities.py)

Run the checks from a configured checkout with Go on `PATH`.

```sh
./scripts/with-mode test bash -c 'cd backend && uv run pytest -q tests/unit/test_fit_decode.py'
uv run --project backend python scripts/rewrite/fit/check.py
uv run --project backend python scripts/rewrite/fit/check_normalized.py
uv run --project backend python scripts/rewrite/check_garmin_activities.py
(cd backend-go && go test -race -count=1 ./internal/garmin/fit)
make check-go
```

## Following slices and integration

Stream 2 owns Garmin JSON and export normalization, FIT reprocessing, Strong preview/apply, Google Calendar event and trip reconciliation, and provider job fetch/retry/checkpoint logic. Keep provider-specific tests and fixtures with these packages. Cover precedence in either import order, repeated delivery, partial or failed pages, and preserved manual trip edits. [Garmin/export precedence](../backend/tests/integration/test_export_precedence.py) · [FIT reprocessing](../backend/tests/integration/test_fit_reprocess.py) · [Strong import](../backend/tests/integration/test_strong_import.py) · [Google Calendar](../backend/tests/integration/test_gcal_sync.py)

Hand stream 1 typed observations, their provenance, affected source identities/dates and the proposed job checkpoint. Connect persistence when stream 1 publishes its transaction boundary. A replay unit must commit source history, the winning values and its checkpoint together. Leave the existing worker as the sole runtime owner until the integrated replay and rollback checks pass. Stream 1 owns the shared router, schema, Makefile and supervisor. The FIT decoder and offline adapters can merge before that integration.

## Active assignment · Replay one Garmin activity end to end

Deliver a runnable synthetic replay from a downloaded activity page, FIT archive or export through normalized observations, field precedence, persisted source history and the job checkpoint. The lead owns the replay command and PostgreSQL transaction. The second agent owns the archive decoder and export parsing. Use the existing Python fixtures and ingestion behavior as the reference.

1. Close the LZMA and local-header filename differences in the FIT comparison. Normalize Garmin JSON, FIT and export inputs with typed provenance and explicit missing values.
2. Run API-first and export-first replays in independently migrated test schemas. Compare the canonical activity and source history with Python. Duplicate input must preserve identity and provenance.
3. Apply the observations and checkpoint atomically. Inject an error after a source write, then restart the job. Verify the durable state, checkpoint and affected activity IDs/dates, including a partial page.
4. Push each verified increment on `go/provider-replay` and keep going until the runnable replay passes the full matrix. Hand the worker and refresh integration code the command and its affected dates. Python continues to own live ingestion.

[Ingestion and precedence tests](../backend/tests/integration/test_export_precedence.py) · [Job implementation](../backend/app/services/sync.py)

## Continuation prompt

> Own the complete Garmin replay assignment above with your Astra team. Continue from the published decoder on the active continuation branch. Work through normalization, database writes, replay and recovery, publishing each verified increment. Finish by reporting the runnable command, commits, Python comparison results and any remaining live-worker integration.

## Running a synthetic activity replay

From the repository root, run the two-order PostgreSQL comparison with Go on PATH. The test runner creates independent Alembic-migrated schemas for Python and Go. It checks immutable raw payload hashes, winning values and source links, the FIT observations and the job checkpoint. It also interrupts the checkpoint write, restarts the same job and checks retained-file reprocessing after corruption.

```sh
python3 scripts/test-db.py provider
```

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

The worker integration entry point is `replay.Apply(ctx, pool, privateDir, page)`. It takes previously fetched inputs, including API records or `ScanExport` results and optional FIT bytes keyed by Garmin activity ID. It returns cumulative counters, next page, offset, and the changed activity IDs and dates for this delivery. A local-date move includes both dates. The checkpoint also retains the job-wide union of affected dates. The terminal status is `partial` when the job has rejected records or failed FIT attempts. A duplicate committed page returns its checkpoint with empty change sets. A changed redelivery or skipped page index fails.

Python continues to schedule downloads, hold unconfirmed treadmill runs for review, maintain coverage, and refresh dependent metrics. The standalone command uses its own replay job dataset. It imports the activity portion of an account export. [Replay transaction](../backend-go/internal/garmin/replay/page.go) · [Synthetic comparison](../scripts/rewrite/check_provider_replay.py)

## Strong workout CSV import

Preview a Strong export in a synthetic workspace, then apply the same file. Preview validates every row and compares source identities against PostgreSQL without creating a batch, a raw file, or a workout. The command emits a JSON summary and the IDs and local dates of changed workouts.

```sh
(cd backend-go && go build -o ../private/strong-import ./cmd/strong-import)
./scripts/with-mode demo private/strong-import private/fixtures/strong.csv
./scripts/with-mode demo private/strong-import -apply private/fixtures/strong.csv
```

`strong.Import(ctx, pool, privateDir, csvPath, apply)` preserves the exact source strings and set order. Apply retains the immutable CSV before committing its SHA-256, a source record for each distinct workout revision, and the batch outcome in one database transaction. A changed workout stays linked to its original canonical sets and enters revision conflict for review. Manual completions and recorded RPE keep their workout IDs. Repeated files create an import batch while preserving the existing workout and source identities. Timezone, weight units and the dumbbell-weight convention remain unknown. A rollback can leave an unreferenced immutable file, which a retry verifies and reuses.

Run the Python parser reference and the isolated PostgreSQL workflow comparison from the repository root.

```sh
uv run --project backend python scripts/rewrite/check_strong_csv.py
python3 scripts/test-db.py strong
```

The database comparison exercises read-only preview, first import, duplicate and changed exports, manual associations, rollback after the workouts were written, restart, competing import processes, and mixed-account rejection. [Scanner](../backend-go/internal/strong/scan.go) · [Transaction](../backend-go/internal/strong/import.go) · [Database comparison](../scripts/rewrite/check_strong_import.py)

## Google Calendar replay and trip reconciliation

`travel.Apply(ctx, pool, delivery)` accepts a fetch timestamp and the complete sequence of Google Calendar list responses. On every page after the first, include the request token as `page_token`. The final page has no next token. The decoder verifies the chain before treating absent events in the fetch window as removed. The window runs from 30 days before to 180 days after the fetch date in the athlete's timezone.

Replay commits event versions, detected trips, ordered flight legs, the data revision and the import batch together under the shared writer lock. A repeated window preserves event versions and trip identities. Changed or cancelled flights flag trips the athlete edited and preserve their dates, destination and availability. A failed fetch records a failed batch. A database failure rolls the reconciliation back. [Transaction](../backend-go/internal/travel/replay.go) · [Trip reconciliation](../backend-go/internal/travel/reconcile.go)

From the repository root with Go on PATH, run the comparison against Python or replay a local synthetic manifest.

```sh
python3 scripts/test-db.py gcal
(cd backend-go && go build -o ../private/gcal-replay ./cmd/gcal-replay)
./scripts/with-mode test private/gcal-replay -input private/fixtures/calendar-window.json
```

The manifest has the following form. An empty terminal page completes a window, so replay it only when the captured fetch is complete.

```json
{"now":"2026-11-22T15:00:00Z","pages":[{"items":[],"nextPageToken":"p2"},{"page_token":"p2","items":[]}]}
```
