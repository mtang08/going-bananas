# Backend implementation map

Inherit the root iteration-speed policy. The Go API, worker, and operational
commands serve all workspaces. This directory contains the historical Alembic
chain and Python reference code for offline comparisons. Start with the Go
entry points for current behavior.

| Layer | Location |
| --- | --- |
| HTTP, worker, CLI dispatch | `backend-go/cmd/going-bananas/`, `backend-go/internal/httpapi/`, `backend-go/api/` |
| Domain services and SQL | The relevant `backend-go/internal/` package, then `backend-go/sql/` and generated `backend-go/internal/db/` |
| Fresh and historical migration dispatch | `backend-go/internal/workspacemigrate/` and the baseline in `backend-go/sql/` |
| Historical Python migration chain | `migrations/versions/`, `migrations/env.py`, `app/migrations_head.py` and `app/history_models.py` |
| Python reference CLI | `app/cli.py`, `app/config.py`, `app/db.py` |
| Python domain and service reference | `app/domain/`, `app/read/`, `app/services/`, `app/metrics/`, and `app/adapters/` |

Current flow goes from the helper and Go coaching commands to a snapshot and
draft, then through explicit review and acceptance to a versioned calendar.
Matching and check-ins update the evidence available at the next review.

## Change conventions

- Keep domain decisions in services and pure calculations so API and CLI share
  them. Coordinate wire changes with the Go OpenAPI definitions, generated
  types, frontend consumers, and the coaching helper.
- PostgreSQL tests cover transactions, locking, JSON, migration, and stale
  versions. Inspect the transaction boundary before changing calendar or
  proposal writes. Preserve atomic acceptance, freshness checks, revision
  history, and protected actual and completion links.
- For schema changes, account for both an existing upgraded database and the
  Go baseline for fresh databases. Keep older Alembic revisions loadable and
  verify the upgrade with synthetic history. Back up before applying schema
  changes in real mode.
- Preserve source provenance and replay idempotency. Keep unknown values
  explicit. Dates and recurrence use the athlete timezone, including DST.
- Update snapshot fields and fingerprint inputs together so changes to decision
  evidence invalidate stale proposals.
- The repo-local `.codex/skills/going-bananas-coach/` owns the coaching helper.
  Update manifest hashes when changing packaged files and run its contract
  checks. Install into the user's global skill copy only when requested.

## Focused verification

Run from the repository root.

```sh
cd backend-go && go test ./internal/httpapi ./cmd/going-bananas
```

`make check-go` checks generated code, builds, lints, and runs race-enabled
tests. `make check-backend` also checks the retained Python code.
`make test-integration` provisions isolated PostgreSQL for the Python reference
and migration suite. Use the Go HTTP tests and the synthetic Playwright setup
in [README.md](../README.md#verification) for runtime API and browser behavior.

For a complete coaching contract change, exercise the helper, Go API, accepted
calendar, and next snapshot with synthetic data. Mocked model transport verifies
the app contract. Coaching quality and real device capability need their own
evidence.
