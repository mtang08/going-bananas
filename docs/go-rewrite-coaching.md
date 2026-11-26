# Workstream 3 · Coaching evidence and proposal lifecycle

**Owner:** the third Astra session. **Branch:** `go/coaching`. Home's Go proposal-list read is the existing transport reference. Pending proposals, decisions, the dashboard coach and the repo-local helper still use the Python application. [Working Go read](../backend-go/internal/proposals) · [Shared specification](go-backend-rewrite.md)

## First independent assignment

Port the **coaching evidence fingerprint used to decide whether an existing draft is current**. Start under `backend-go/internal/coaching/` with typed inputs for source versions and verified knowledge selection. Produce canonical UTF-8 bytes and a SHA-256 digest from those inputs. The package must compute the result from the supplied evidence, including selected record content. The Python implementation and checked-in fixtures define the behavior. [Canonicalization and fingerprint construction](../backend/app/services/decision_inputs.py) · [Coaching hash fixture](../backend/tests/fixtures/canonical-hashes.json) · [Persisted fingerprint fixture](../backend/tests/fixtures/coach-fingerprint.json)

| Deliverable | Completion check |
| --- | --- |
| Coaching scalar and timestamp encoding | Read the fixtures as inputs, preserving large integers, integer/float distinctions, negative zero, UTC offset spelling, Unicode and exact string escaping. Assert canonical bytes and SHA-256 against Python's coaching vectors. |
| Construction of the fingerprint from source versions and verified knowledge | Match the original fixture digest and its revised selected-content digest. Reordered object keys retain identity. Changed evidence invalidates the fingerprint. Cover missing/null values and order-sensitive lists as in Python. |
| Reproducible reference comparison | Run the existing Python canonical-hash and proposal fingerprint cases and the new focused Go race tests. Use the committed synthetic evidence. A database, Garmin account and model session are unnecessary for this package. |

Stream 1 owns metric identity, whose timestamp encoding differs. Keep the coaching entry point explicit. A shared encoder can be extracted later if both domains' byte fixtures still pass. [Python hash tests](../backend/tests/unit/test_canonical_hash_vectors.py) · [Changed-evidence case](../backend/tests/unit/test_proposals.py)

### Fingerprint handoff

Snapshot and proposal code can call `coaching.Fingerprint(sources, knowledge)` to obtain the canonical UTF-8 bytes and lowercase SHA-256. Supply these two inputs. [Go fingerprint API](../backend-go/internal/coaching/fingerprint.go)

- `SourceVersions` contains the full source-versions object. Keep historical and unknown keys, explicit nulls and list order. Its JSON decoder preserves integer and float tokens. For programmatic inputs, use ISO strings for calendar dates and `time.Time` at microsecond precision or coarser for instants. [Coaching encoder](../backend-go/internal/coaching/canonical.go)
- `VerifiedKnowledge` carries the verifier's digest, ordered `SelectionEntry` values (path and sections or record IDs), and ordered `SelectedRecord` values (path, record ID and complete `RecordContent`). Knowledge verification still runs in Python. [Verified knowledge selection](../backend/app/services/knowledge.py)

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

## Prompt for the third Astra session

> Own workstream 3 in Going Bananas. Read the root AGENTS.md and docs/go-rewrite-coaching.md. Start from current origin/main containing dc15070, in a separate checkout on go/coaching. Use your own Astra subagents for canonical encoding, fingerprint fixtures and independent review. Deliver the first assignment end to end, comparing actual Go bytes and digests against the existing Python evidence. Run the focused reference cases, race tests and project checks, then commit and push your branch. Report the commit, exact checks, parity gaps and the typed inputs that snapshot or proposal code will supply. Leave metric identity, shared write infrastructure and proposal activation with their documented owners. Use only synthetic evidence.
