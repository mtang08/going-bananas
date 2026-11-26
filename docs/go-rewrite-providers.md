# Workstream 2 · Provider ingestion and FIT

**Owner:** the second Astra session. **Branch:** `go/providers`. The native Garmin HTTP client is already in `main` at `dc15070`. It handles authentication/cache reuse, activity and recovery reads, pagination and FIT downloads. Python still normalizes and persists the data. [Go client](../backend-go/internal/garmin) · [Shared specification](go-backend-rewrite.md)

## First independent assignment

Port **downloaded ZIP bytes to application-level decoded FIT data**. Put the production decoder and its tests under `backend-go/internal/garmin/fit/`. Give it an in-memory entry point that accepts the same downloaded bytes as Python. Use the Go decoder version pinned in the existing probe. Stream 2 owns the corresponding Go module dependency and checksum change for this slice. [Python decoder and output types](../backend/app/adapters/garmin/fit.py) · [Probe dependency](../scripts/rewrite/fit/go.mod)

| Deliverable | Completion check |
| --- | --- |
| ZIP member selection, size checks while streaming, FIT integrity checks and stable errors | The same synthetic archives produce the same error codes for zero or multiple FIT members, an oversized member, corrupt ZIP and bad FIT CRC. |
| Typed session, laps, steps, timer intervals, streams, quality flags and filtered metadata | Compare the Go outputs to Python's `decode_fit_zip` on the same synthetic bytes. Cover pauses, duplicate timestamps, missing channels, alternate speed/altitude fields, lap intensity and workout targets. Preserve nulls, ordering and the FIT payload hash. Record the native library's actual version in decoder provenance. |
| Reproducible parity fixtures and an isolated test command | Keep the Python fixture builder as the reference. Assert that coordinates, device serials and other excluded fields stay out of normalized results. Run focused Go race tests, Python reference cases and the project checks. |

The existing Go probe compares primitive decoder messages. Passing it alone does not exercise the normalized values consumed by ingestion. This first deliverable needs synthetic files only. [Synthetic FIT builder](../backend/tests/fixtures/fit/synthetic.py) · [Decoder scenarios](../backend/tests/unit/test_fit_decode.py) · [Existing probe](../scripts/rewrite/fit/check.py)

Run the references from a configured checkout with Go on `PATH`. Add the package's normalized-output comparison to these checks when handing back the branch.

```sh
./scripts/with-mode test bash -c 'cd backend && uv run pytest -q tests/unit/test_fit_decode.py'
uv run --project backend python scripts/rewrite/fit/check.py
make check-go
```

## Following slices and integration

Stream 2 owns Garmin JSON and export normalization, FIT reprocessing, Strong preview/apply, Google Calendar event and trip reconciliation, and provider job fetch/retry/checkpoint logic. Keep provider-specific tests and fixtures with these packages. Cover precedence in either import order, repeated delivery, partial or failed pages, and preserved manual trip edits. [Garmin/export precedence](../backend/tests/integration/test_export_precedence.py) · [FIT reprocessing](../backend/tests/integration/test_fit_reprocess.py) · [Strong import](../backend/tests/integration/test_strong_import.py) · [Google Calendar](../backend/tests/integration/test_gcal_sync.py)

Hand stream 1 typed observations, their provenance, affected source identities/dates and the proposed job checkpoint. Connect persistence when stream 1 publishes its transaction boundary. A replay unit must commit source history, the winning values and its checkpoint together. Leave the existing worker as the sole runtime owner until the integrated replay and rollback checks pass. Stream 1 owns the shared router, schema, Makefile and supervisor. The FIT decoder and offline adapters can merge before that integration.

## Prompt for the second Astra session

> Own workstream 2 in Going Bananas. Read the root AGENTS.md and docs/go-rewrite-providers.md. Start from current origin/main containing dc15070, in a separate checkout on go/providers. Use your own Astra subagents for ZIP/FIT decoding, Python parity fixtures, and independent review. Deliver the first assignment end to end using synthetic files. Respect the documented ownership boundary. Run the focused comparisons, race tests and project checks, then commit and push your branch. Report the commit, exact checks, parity gaps and the package entry point stream 1 can call. Leave production ingestion and real athlete data untouched.
