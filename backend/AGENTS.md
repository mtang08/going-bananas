# Backend implementation map

Inherit the root iteration-speed policy. Prefer changing a contract and all its
callers together over maintaining parallel implementations for compatibility.

## Locate the behavior

Paths below are relative to `backend/`.

| Layer | Location and purpose |
| --- | --- |
| App wiring | `app/main.py`: routers, local host/origin/write guards, errors, health, static frontend |
| Runtime | `app/config.py`, `app/db.py`, `app/cli.py`; root `scripts/serve.py` manages processes |
| HTTP | `app/api/`: request validation, service calls, response envelopes |
| Calendar | `app/calendar_models.py`, `app/services/calendar.py`: versioned session state and undo |
| Proposals | `app/coach_v2_models.py`, `app/services/proposals.py`: payload schema, freshness, validation, decisions |
| Coach context | `app/services/snapshot.py`, `decision_inputs.py`, `knowledge.py`: filtered evidence, fingerprints, verified KB |
| Planning | `app/planning_models.py`, `app/api/planning.py`, `app/api/anchors.py`: blocks and calibration |
| Feedback | `app/checkin_models.py`, `app/services/checkins.py`, `prompts.py`, `daily_guidance.py` |
| Metrics | `app/metrics/contract.py`, `engine.py`, then relevant metric module; `app/metric_models.py` |
| Ingestion | `app/adapters/` parses provider formats; `app/services/` orchestrates sync/import/FIT and source history |
| Pure calculations | `app/domain/`: analytics, recurrence, associations |
| Storage changes | `migrations/versions/`, `app/migrations_head.py` |

Current flow: helper → coach API/CLI → snapshot + decision inputs + KB → proposed
changes → explicit app decision → versioned calendar → actual matching/check-ins
→ next snapshot. Trace the relevant path rather than reading every service.
Legacy `coaching.py` and `agent_plans.py` are separate older workflows.

## Change conventions

- Keep domain decisions in services/pure calculations so API and CLI share them.
  Use the existing envelope/error patterns; coordinate wire changes with
  `frontend/src/api.ts`, `frontend/src/api/types/`, and the helper if affected.
- PostgreSQL is the supported database. Use its integration tests for transaction,
  locking, JSON, migration, and stale-version behavior; SQLite is not a substitute.
- Inspect the current transaction/lock boundaries before changing calendar or
  proposal writes. Preserve atomic acceptance, freshness checks, revision history,
  and protected actual/completion links unless deliberately redesigning them.
- When schema changes, add a migration and update `app/migrations_head.py` and
  affected upgrade tests. Prefer a direct migration over compatibility scaffolding.
  Keep real history recoverable and back up before applying to real mode.
- Imported observations retain provenance and replay/idempotency behavior. Unknown
  values stay unknown. Dates and recurrence use the athlete timezone, including DST.
- Snapshot fields and fingerprint inputs belong together: changed decision evidence
  must invalidate stale proposals. Check `decision_inputs.py` when adding evidence.
- Helper changes live in the repo-local `.codex` package, not the legacy `skills/`
  copy. Update its manifest hashes when changing packaged files and run the v2
  helper tests. Do not silently install over the user's global skill copy.

## Focused verification

Run from repo root. Use `PYTEST_ADDOPTS` to focus the integration suite while
keeping its isolated PostgreSQL setup.

```sh
./scripts/with-mode test bash -c 'cd backend && uv run pytest tests/unit/test_proposals.py'
PYTEST_ADDOPTS='-k proposals' make test-integration
./scripts/run bash -c 'cd backend && uv run ruff check . && uv run mypy app --ignore-missing-imports'
```

Unit tests are under `tests/unit/` and `tests/test_*.py`; DB tests are under
`tests/integration/` plus `tests/test_ingestion_integration.py`. Select tests by
behavior; names alone do not prove which generation of coaching they cover.
For a complete coaching contract change, verify helper → API → calendar → next
snapshot on synthetic data. A mocked transport test does not establish coaching
quality or real device capability.
