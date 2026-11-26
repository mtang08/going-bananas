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

Two ZIP differences remain. Go accepts stored, Deflate and BZIP2 members. Python also accepts LZMA, which Go reports as `bad_zip`. Go selects the central-directory filename and can accept a ZIP whose local header gives that member a different name. Python reports `bad_zip` for that mismatch.

Run the checks from a configured checkout with Go on `PATH`.

```sh
./scripts/with-mode test bash -c 'cd backend && uv run pytest -q tests/unit/test_fit_decode.py'
uv run --project backend python scripts/rewrite/fit/check.py
uv run --project backend python scripts/rewrite/fit/check_normalized.py
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
