# Analytics MVP implementation plan

User update (2026-11-10): lifting is tracked in Strong, not Garmin. Strong CSV is a future separate source; no export/parser now. Strength totals are recorded sessions with incomplete coverage, never evidence of skipped lifting. See `backlog.md`.

Updated 2026-11-10. Authoritative scope after the user's clarification: build the
data, analytics, visualization, and persistent feedback core first. Research
arrives later as a local `running_coach_kb/`; no runtime LLM is required for this
release. This is the design baseline. The analytics implementation is now delivered; see `release-checklist.md` and `handoff.md` for actual verification and remaining limitations.

## Product outcome

The athlete can import Garmin history, understand recent running and strength
training, see missing/stale data, record symptoms in seconds, inspect delayed
responses, and compare an accepted manual plan with actual training. The app
provides factual weekly summaries, not training prescriptions. It prepares a
compact local context export for a future research-informed agent/skill.

The athlete is a hybrid athlete maintaining meaningful full-body strength twice
weekly alongside running. Strength is not an expendable accessory. Show it in
history and scheduling; do not invent lifting targets, exercises, rehab doses,
calorie targets, or require food logging. Optional low-impact aerobic activities
can be imported/tagged and displayed separately without adding recommendations.

Included: real-data import; safe re-import; recovery data when actually available;
overview and drill-down; check-in history; fortnight schedule and manual plan
versions; sync status; private backup/restore; documented local operation.

Excluded: recommendations, readiness scores of our own, injury prediction,
automatic load progression, inferred training zones, Garmin workout publishing,
agent chat, embeddings/vector stores, runtime model selection, public hosting,
phone access, multi-user accounts, full GPS/stream charts, and food diaries.
No cloud deployment or telemetry is part of implementation.

## Decisions and structure

- React + TypeScript + Vite; plain CSS; Recharts for the few needed charts;
  TanStack Query for server state. Avoid a global state framework.
- Python 3.12+, FastAPI/Pydantic, synchronous SQLAlchemy + psycopg, Alembic,
  PostgreSQL. SQLAlchemy sessions stay inside request/job boundaries. Network
  imports run in a separate local worker process, not an async request handler.
- Use uv with a committed lockfile and npm with a committed lockfile. Select
  mutually supported stable versions during scaffolding, document them, and pin
  them. Verify library APIs in official documentation when implementing.
- Compose runs PostgreSQL only, loopback-bound, with a named volume. An existing
  local PostgreSQL service may be configured instead: same backend/schema,
  not another database implementation. No automatic system-wide installations.
- Production local mode: FastAPI serves the built frontend and `/api/v1` on one
  loopback origin. Development: Vite loopback server proxies `/api` to FastAPI.
- Backend CLI manages imports, worker, startup catch-up, backups, context export,
  and demo seed. No Redis/Celery or resident LLM service.

Suggested tree (create files when their task needs them):

```text
backend/
  pyproject.toml, uv.lock, alembic.ini
  app/{main.py,config.py,db.py,cli.py}
  app/api/                 # HTTP schemas/routes; no metric arithmetic
  app/models/              # persisted entities
  app/domain/              # pure normalization, metrics, cycle, associations
  app/services/            # transactions, reconciliation, summaries, jobs
  app/adapters/garmin/     # official client adapter, inspected export adapter
  migrations/
  tests/{unit,integration,fixtures}/
frontend/
  src/{api,components,pages,styles}/
  tests/
e2e/
scripts/                  # launchd template, doctor, backup wrapper
docs/
private/                  # ignored raw, config, profile, backups, context exports
running_coach_kb/          # later local research folder; not required at startup
compose.yaml, Makefile, .env.example
```

Database migrations are normal schema evolution, not a database migration
project. Use separate demo, test, and real databases with identical schemas.
Configure mode at process startup; all API envelopes/UI show mode. No runtime
frontend toggle can write demo rows into the real database. Seed commands refuse
the real database. Test/drop/reset commands refuse non-test targets.

## Ordered implementation tasks

Each task finishes with relevant tests, a brief ledger update, and a usable
checkpoint. Continue to the next task without repeated approval requests. Ask
only when the decision truly depends on the athlete or an external permission.
Record a blocked external gate and continue independent tasks.

### M0 — Reproducible local skeleton

Read the private brief locally; persist a dated profile through a local setup
command, not a committed fixture. Inventory tools without printing environment
secrets. Create backend, frontend, Postgres configuration, initial migrations,
health/readiness endpoints, loopback restrictions, `.env.example` placeholders,
and `doctor` checks. Add setup/start/stop instructions, graceful process shutdown,
and a small fixture dashboard with unmistakable DEMO labeling.

Deliver commands with these meanings (exact paths documented in README):
`make setup`, `make dev`, `make build`, `make start`, `make check`,
`make test-integration`, `make test-e2e`. Setup never imports real data or replaces
an existing database. Start runs the local server and import worker.

Gate: fresh demo setup starts, health/readiness distinguish process health from
DB availability, app works with no keys/model/KB, stop preserves data. Pin tool
requirements; if tools cannot be installed, deliver files but mark execution
unverified instead of claiming the gate passed.

### M1 — Persistence and canonical data

Implement the minimal schema and pure domain contracts in `contracts.md`.
Synthetic adapter exercises the same normalization/persistence pipeline as
real adapters. Add source versioning, idempotence, field provenance, conflicts,
activity overrides, coverage records, and a monotonically increasing data
revision updated transactionally after relevant mutations. Build read APIs and
activity list/detail first so imported results are inspectable immediately.

Gate: unit/integration cases V01–V09 and V19 pass using PostgreSQL. Reordering
source imports has a deterministic result given the same source revision metadata.
Re-imported data doesn't change counts or revision unnecessarily.

### M2 — First real import and capability inventory

Verify current Garmin docs/client and record checked URLs, date, client version,
wrapper/endpoint, units, fields, pagination, timezone semantics, history/window
limits, auth behavior, rate policy, terms, and pricing status per used dataset
in `docs/garmin-capabilities.md`. Unknowns stay explicit. Never claim a complete
history based on the first successful page. Do not silently use unofficial APIs.

Preferred API path: locally configured key → bounded activity import → canonical
activities. Fetch only necessary summaries/details; avoid all activity streams.
Then add sleep, HRV, and resting HR only when actual fields and units are verified.
Use an availability state for unsupported or empty datasets. Missing wearable
data must not block activity analytics.

If export arrives first: inspect its actual formats locally, preserve original
bytes, report inventory without coordinates/medical notes, implement only the
observed activity summary format first. Do not guess archive paths or Garmin
field names. Defer FIT parsing unless required for that real path. Support only
documented observed files, with actionable errors for unsupported inputs.
Implement second-source parsing only when actual files/access are available;
the common reconciliation contract and synthetic overlap tests exist regardless.

Gate: first real activities visible, source comparison checks pass, identical
re-import changes neither totals nor identity. Redacted verification notes contain
counts/date coverage, not route coordinates or payloads. No key/export: continue
M3–M6 with fixtures, mark real-data acceptance pending.

### M3 — Overview and analytics drill-down

Implement metric definitions exactly as specified. Overview contains current
week and rolling 7/14-day run volume, recent runs, longest run duration, workout
distribution, strength sessions, and sparse recovery trends. Add 4/12-week date
filters, accessible chart/table alternatives, activity detail/provenance, and
independent per-dataset freshness. Keep mobile-width layout usable without
adding remote access. Partial-week comparisons use matched elapsed dates or
clearly label full versus partial; never imply a training verdict.

Gate: V10–V12 and V20 pass; calendar weeks, units, unknown workout labels,
coverage warnings, loading/error/empty states, and gaps are visible. Overview
uses one summary request plus paged details, not per-card history downloads.

### M4 — Check-ins, combined history, and cycle

Implement quick feedback and revision history, temporal run associations, and a
shared timeline containing running, strength, optional low-impact aerobic work,
mobility/rehab notes, and symptoms. No invented combined-load score. Imported
strength is reused; a lightweight manual session is optional when absent, with
explicit duplicate reconciliation if Garmin later supplies it.

Add profile/cycle configuration, unscheduled state, anchored run opportunities,
manual proposals/acceptance/rejection, and manual completion matching. Show
strength twice weekly as a requirement; default suggested days are the reported
Monday/Friday pending confirmation of the rotating schedule. These placeholders
must be marked unconfirmed and cannot activate a plan. Mobility Wednesday is
also configurable. Do not schedule quality/long runs until placement is supplied.

Gate: V13–V18 pass; quick no-issues response takes one action; corrections survive
restart; a missed run doesn't shift the cycle or fabricate completion. Reject
incompatible accepted plans; preserve actual off-cycle imported runs as facts.

### M5 — Reliable local sync and operations

Persist jobs and progress, use one worker with a PostgreSQL advisory lock scoped
to real dataset sync, bound requests, and checkpoint committed pages. Repeated
manual sync requests return the active job. On crash, recover interrupted jobs
and replay safely. Startup checks freshness and enqueues catch-up once. Provide
a launchd template with absolute working directory/interpreter paths and no
secrets in arguments or plist; installation is explicit, not automatic.
The scheduled CLI enqueues and drains its bounded job itself when the web worker
is absent, using the same advisory lock. A queued job alone is not a successful
scheduled sync. Report launcher failures separately from remote API failures.

Initial design defaults, adjustable after API limit verification: daily sync;
14 local days of activities and 7 days of recovery re-fetched; historical
bootstrap separately bounded and resumable. These are engineering windows,
not guarantees Garmin won't revise older data. Offer manual older-range sync.
Default request timeout 30 seconds, at most 4 attempts for transient errors,
jittered backoff, honor Retry-After including HTTP-date form. Long retry delays
persist a next-attempt timestamp instead of holding a worker indefinitely.
Refresh a failed token once via supported client behavior; then stop auth retries
and report credential attention. Never expose response bodies in UI/logs.

Add private database + raw-file + profile/config backup manifest with checksums;
exclude credentials by default. Restore into a new database/directory, validate,
then let the user select it. Never overwrite a live database silently. Document
what backups contain and how to separately restore key configuration.

Gate: V21–V25 pass, scheduled job can run while web UI is closed, laptop catch-up
works after a missed day, restart resumes import, and backup restoration retains
feedback and provenance. Freshness remains honest during partial failures.

### M6 — Factual weekly summary and local-agent interface

Build a deterministic weekly recap: completed runs and strength, observed volume,
coverage, planned/completed differences, symptom entries, available recovery,
and questions remaining unknown. Use descriptive templates, no proceed/modify/rest
recommendations. Recompute inexpensive summaries on request; no premature cache.
Persist user-saved weekly snapshots with data/profile/plan/metric versions.

Expose a versioned, privacy-filtered context export using the same summary
service. Add a future-KB integration document and fixtures to verify selective
loading contracts; do not build an agent runtime, research ingestion service,
policy evaluator, or vector database now. No automatic LLM/network submission.

Gate: V26–V28 pass; JSON context and displayed metrics agree; free-text notes are
excluded by default; absence of KB has no effect on app operation. Research docs
can't overwrite profile values or activate recommendations.

### M7 — Release verification and handoff

Run all applicable checks on clean isolated databases; complete the real-data
walkthrough in `verification.md`; inspect browser console/network, production
build, privacy boundaries, backup restore, and setup from documented commands.
Replace root README's planning banner with accurate installation/operation docs.
Record exact commands/results and any unavailable external checks in
`docs/release-checklist.md`. Don't check in private reports or real-data fixtures.

Analytics release is complete only when all software gates and the real import
walkthrough pass. If credentials/export are unavailable, label it “fixture-tested;
awaiting real-data acceptance,” not complete. Research is not a release blocker.

## Later coaching phase (explicitly out of current implementation)

Integrate the provided local `running_coach_kb/` before substantive adaptive
coaching. Follow guide → selected daily/weekly workflow → relevant topic
sections and candidate policies. Preserve context, limitations, conflicts, and
sources; candidate policies are aids, not executable medical rules. See the
future interface in `contracts.md`. Research stays separate from the dated
athlete profile and current data. No calorie logging requirement.

Before activation: review KB applicability/version, validate plan and safety
constraints, run research evaluation cases including poor sleep alone, worsening
symptoms despite favorable wearable scores, missing data, and preservation of
strength. Proposals require acceptance. Model choice/pricing and any agent/skill
runtime are separate decisions, not implementation-agent assumptions.
