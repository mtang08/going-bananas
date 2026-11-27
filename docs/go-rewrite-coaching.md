# Workstream 3 · Coaching evidence and proposal lifecycle

**Owner:** the third Astra session. **First delivery:** `go/coaching` at `33b2b61`. **Continuation branch:** `go/coaching-lifecycle`. Home's Go proposal-list read is the existing transport reference. Pending proposals, decisions, the dashboard coach and the repo-local helper still use the Python application. [Working Go read](../backend-go/internal/proposals) · [Shared specification](go-backend-rewrite.md)

## First independent assignment

Port the **coaching evidence fingerprint used to decide whether an existing draft is current**. Start under `backend-go/internal/coaching/` with typed inputs for source versions and verified knowledge selection. Produce canonical UTF-8 bytes and a SHA-256 digest from those inputs. The package must compute the result from the supplied evidence, including selected record content. The Python implementation and checked-in fixtures define the behavior. [Canonicalization and fingerprint construction](../backend/app/services/decision_inputs.py) · [Coaching hash fixture](../backend/tests/fixtures/canonical-hashes.json) · [Persisted fingerprint fixture](../backend/tests/fixtures/coach-fingerprint.json)

| Deliverable | Completion check |
| --- | --- |
| Coaching scalar and timestamp encoding | Read the fixtures as inputs, preserving large integers, integer/float distinctions, negative zero, UTC offset spelling, Unicode and exact string escaping. Assert canonical bytes and SHA-256 against Python's coaching vectors. |
| Construction of the fingerprint from source versions and verified knowledge | Match the original fixture digest and its revised selected-content digest. Reordered object keys retain identity. Changed evidence invalidates the fingerprint. Cover missing/null values and order-sensitive lists as in Python. |
| Reproducible reference comparison | Run the existing Python canonical-hash and proposal fingerprint cases and the new focused Go race tests. Use the committed synthetic evidence. A database, Garmin account and model session are unnecessary for this package. |

The shared JSON encoder preserves separate coaching and metric timestamp formats. Both domains have byte-for-byte regression fixtures. [Python hash tests](../backend/tests/unit/test_canonical_hash_vectors.py) · [Changed-evidence case](../backend/tests/unit/test_proposals.py)

### Fingerprint handoff

Snapshot and proposal code can call `coaching.Fingerprint(sources, knowledge)` to obtain the canonical UTF-8 bytes and lowercase SHA-256. Supply these two inputs. [Go fingerprint API](../backend-go/internal/coaching/fingerprint.go)

- `SourceVersions` contains the full source-versions object. Keep historical and unknown keys, explicit nulls and list order. Its JSON decoder preserves integer and float tokens. For programmatic inputs, use ISO strings for calendar dates and `time.Time` at microsecond precision or coarser for instants. [Coaching encoder](../backend-go/internal/coaching/canonical.go)
- `VerifiedKnowledge` carries the verifier's digest, ordered `SelectionEntry` values (path and sections or record IDs), and ordered `SelectedRecord` values (path, record ID and complete `RecordContent`). The Go verifier checks the selected records and sections against the repository KB. [Go verifier](../backend-go/internal/coaching/knowledge.go) · [Python reference](../backend/app/services/knowledge.py)

The unchanged draft fixture produces 608 canonical bytes. Changing only the selected title from `Easy` to `Easy revised` produces 616. Both byte sequences hash to their respective stored Python digests. Run the following checks from a configured checkout. [Persisted fixture test](../backend-go/internal/coaching/fingerprint_test.go)

```sh
./scripts/with-mode test bash -c 'cd backend && uv run pytest -q tests/unit/test_canonical_hash_vectors.py tests/unit/test_proposals.py::test_fingerprint_fixture'
(cd backend-go && go test -race -count=1 ./internal/coaching)
make check-go
```

## Following slices and integration

- Port verified knowledge selection, bounded snapshots, and immutable evidence needed to reproduce freshness. Keep the research library and repo-local skill authoritative. Share one factual read across display and fingerprint calculation while retaining dependencies omitted from the compact display. [Knowledge verification](../backend/app/services/knowledge.py) · [Snapshot implementation](../backend/app/services/snapshot)
- Port proposal validation, partial selections, revision/retry receipts, stale outcomes, the CLI/helper and native dashboard coaching operations. Preserve stable IDs and draft revisions. A saved draft requires an explicit athlete decision before calendar activation. The dashboard must preserve its private conversation receipts, local-only access and six approved tools. [Proposal services](../backend/app/services/proposals) · [Coaching API scenarios](../backend/tests/integration/test_coach_api.py) · [Dashboard scenarios](https://github.com/mtang08/going-bananas/blob/de3bdf504b8dc6f9b1577d610889349ffd723fb2/backend/tests/integration/test_coach_chat.py)
- Stream 3 owns coaching packages and domain tests. Stream 1 owns calendar/block/anchor mutations, exception detection, shared database migrations, global API/CLI registration and their transaction runner. Hand it the validated selected changes keyed by change ID, expected revisions and idempotency key. Under one locked transaction, recheck freshness, apply accepted changes and persist the receipt. Demonstrate an unchanged Python-created draft can be revised or accepted and a lost response can be retried without a second calendar edit. [Decision scenarios](../backend/tests/integration/test_proposals.py)

## Active assignment · Complete pending-draft lifecycle

Deliver a runnable synthetic workflow that builds or loads a snapshot, saves a pending proposal, reloads it, revises it under the same ID and discards it. Include a draft originally created by Python. The coaching team owns package-local persistence, knowledge selection and validation. Core owns shared route registration and calendar writes.

1. Read persisted draft and snapshot evidence in PostgreSQL, verify the selected knowledge, and check its fingerprint. Cover changed source inputs and changed selected record content.
2. Port proposal validation and submit/load/revise/discard. Preserve the current draft ID, revision checks, duplicate handling, structured errors and authorization. Produce typed inputs keyed by change ID for a future manual acceptance.
3. Compare the responses and durable rows from Go and Python on independent synthetic schemas. Exercise a duplicate submission, stale revision, concurrent edits, a failed write with rollback and the unchanged Python-created draft.
4. Push each verified increment on `go/coaching-lifecycle` and continue through the whole workflow. The runnable entry point and package-local tests can proceed while core owns shared HTTP registration. Manual acceptance remains a separate athlete action.

[Proposal lifecycle tests](../backend/tests/integration/test_proposals.py) · [Proposal services](../backend/app/services/proposals)

## Continuation prompt

> Own the complete pending-draft lifecycle above with your Astra team. Continue from the published fingerprint package on the active continuation branch. Work through evidence, validation, persistence and rollback, publishing each verified increment. Finish by reporting the runnable command, commits and Python-created draft comparison.

## Native dashboard handoff

The package-local HTTP handler serves the dashboard review, message, new-review, cancellation and auth endpoints. Core owns registration under `/api/v1/coach/chat` and shutdown at server exit. For demo and test, call `coachdashboardhttp.NewNative(ctx, pool, cfg)` once with the migrated PostgreSQL pool and a `LocalConfig` containing the repository root, private directory, mode and local ports. [Native tool wiring](../backend-go/internal/coachdashboardhttp/native.go) Construction imports the mode's previous Python conversation files. Opening a review reads its state. Sending a user message loads the repo-local coaching instructions and starts a model turn. [Local composition](../backend-go/internal/coachdashboardhttp/local.go) · [Runtime](../backend-go/internal/coachdashboard/appserver.go)

Core owns migration `0028_coach_chat_reviews` and the schema catalog. The file importer uses its reviews, receipts and import-marker tables. Stop the Python writer for the mode at cutover. Import retains archives, thread IDs, observed evidence and message receipts in one transaction. Repeating startup preserves subsequent Go turns. [Importer](../backend-go/internal/coachdashboard/import.go)

The six dashboard tools operate on the active turn. The native constructor binds domain reads and pending-draft writes to the dispatcher's transaction. The save callback receives a verified snapshot identity and the observed draft revision. The athlete’s pending-save authorization applies to the current message. Proposal decisions belong to the proposal service and its review page. [Tool contract](../backend-go/internal/coachdashboard/tools.go)

Snapshot assembly calls `snapshotreads.LoadInputs` in the caller's consistent transaction after metric and exception refresh. It reads planning, workout, feedback, block, travel, exception and profile projections. The snapshot builder composes the native weekly digest, return plan, confirmed strength sessions and accepted omissions. It selects and verifies the KB evidence and persists the canonical packet and source fingerprint in the same transaction. [Snapshot builder](../backend-go/internal/coaching/snapshots/build.go) · [Query registry](../backend-go/internal/coaching/drilldowns/query.go) [Snapshot inputs](../backend-go/internal/coaching/snapshotreads/inputs.go)

Run the dashboard checks from a configured checkout with the pinned Go tools on PATH. The dashboard runner uses a disposable schema and a scripted local app-server. Its file-import case generates the archive with the Python dashboard writer.

```sh
python3 scripts/test-db.py test tests/integration/test_coach_chat.py
python3 scripts/test-db.py dashboard
make check-go
```
