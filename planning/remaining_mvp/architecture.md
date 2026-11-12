# Going Bananas — architecture (MVP-1.0)

Extends current FastAPI/SQLAlchemy/PostgreSQL17 + React/Vite/TanStack app. Immutable audit baseline `main@5ebf981aa4517f4f73f3c97aa5d43232204466ce`, current schema `0009_agent_plan`; implementation starts from manager-supplied dependency-complete `gb-mvp1-*` tag. All planning contracts live in `planning/remaining_mvp`. No planning-time application changes or real-data access.

## 1. Runtime and rollout

Garmin/Strong ingestion retains raw provenance → canonical observations → FIT stream/metric facts → browser and selective coach snapshots. Codex skill obtains snapshot/query results and submits a proposal; every changeset requires user acceptance in browser. Server has no model credentials or LLM calls. Existing `scripts/serve.py`, local worker and loopback security stay.

Current weekly/daily agent plans, review history, checkins, completions and recurring strength/mobility remain fully functional through foundation and feature tasks. New services develop beside them. TASK-068 imports populated state transactionally, preserves raw archives/source mappings and latest eligible legacy undo, then changes `app_state.planning_authority` to calendar. Before cutover old writers are authoritative; after it no old route can auto-activate plans or write invisible legacy observations. New calendar/coach writes require calendar authority. Permanent new checkin/guidance routes are `/v2/checkins` and `/coach/v2/daily`; no ambiguous duplicate route registration.

## 2. Owned module map

| Path | Remaining responsibility / owner |
| --- | --- |
| `app/models.py` | TASK-003 additive Activity/AppState fields only; keep legacy classes |
| `app/agent_models.py`, `app/coaching_models.py` | preserve existing audit/recommendation/outcome classes; no replacement |
| `app/{fit,checkin,calendar,planning,metric,coach_v2}_models.py` | TASK-003 new model modules; coach_v2 avoids deleting existing imports |
| `migrations/versions/0010_ingest_fit.py` … `0015_coach_v2.py` | TASK-003 integration owner; additive chain after0009, exact schema §1 |
| `app/migrations_head.py` | TASK-003 `EXPECTED_HEAD='0015_coach_v2'` |
| `app/adapters/garmin/fit.py` | TASK-004 pure decoder/dataclasses, schemas §6.2 |
| `app/adapters/garmin/personal.py` | TASK-004 `_call` wrappers for download/details/workouts |
| `app/services/fit_inventory.py` | TASK-004 redacted inventory helpers; CLI wiring030 |
| `app/services/fit_ingest.py`, `services/sync.py` | TASK-010 idempotent raw/FIT persistence, per-activity isolation; preserve source provenance |
| `adapters/garmin/normalize.py`, `services/export_import.py` | TASK-010 profile timezone and missing-safe timer handling; API duration remains gated |
| `app/services/timezone.py` | already complete; reuse athlete_tz/local_date/athlete_today |
| `app/metrics/contract.py`, `engine.py`, `anchors.py`, `api/anchors.py` | TASK-011 foundation signatures, historical anchors, no live wiring |
| `app/services/calendar.py`, `calendar_structure.py`, `api/calendar.py` | TASK-012 calendar lineage, typed structure, manual edits, completion links, rollback/bootstrap |
| `app/services/checkins.py`, `daily_guidance.py`, `api/checkins.py` | TASK-013 v2 checkins, rules, persisted guidance; preserve legacy coaching.py |
| `app/services/strength_routine.py`, `api/planning.py` | TASK-014 routine templates/profile schedule projection, goals/events/block read APIs |
| `app/metrics/{volume,intensity,intervals,srpe,symptoms,recovery,spacing,planned_actual}.py`, `services/matching.py`, `prompts.py` | TASK-020–026 owned modules and pure fact calculators |
| `app/metrics/engine.py`, `app/api/metrics.py` | TASK-030 integration triggers, metric read DTOs, API/router/CLI registration |
| `app/services/knowledge.py` | delivered selective loader retained; TASK-060 adds remaining routing while preserving callers |
| `app/services/snapshot.py`, `proposals.py`, `api/coach.py` | TASK-061–063 freshness-checked snapshots, manual decisions, atomic acceptance |
| `app/services/summary.py`, `api/core.py::get_context`, existing agent services | retained through068; no early cleanup or stubbing; adapt remaining callers before any later removal |
| `app/services/legacy_cutover.py`, `api/history.py` | TASK-068 import, mapping, archive reads and latest legacy undo adapter |
| `app/main.py`, `app/cli.py`, lockfiles, `frontend/src/App.tsx`, `api.ts` | integration-owner-only shared-file edits at each coordinated task boundary |

A model-level FK may target its own module or `models.py`; cross-module FKs must exist in migration even when ORM column omits ForeignKey to avoid import cycles. Every model module imported in migration env and application metadata bootstrap. Check constraints/defaults/unique indexes are schema obligations. SDK21.221.0 is already locked; TASK-002 is not rerun.

## 3. Recompute and data identity

Schemas §6.3 is the sole metric API contract. Source writes collect old/new identities before flush; TASK-030 owns ordered matching → activity metrics → planned/actual completion writeback → windows/spacing → prompts. No metric commits. Transactions atomically invalidate old current rows and promote new dependency signatures; previous rows remain explainable. Failure rolls back source and derived changes. Derived refresh does not bump source data revision or self-trigger a loop. Register hooks once, guard recursion, explicitly flush derived rows; prohibited untracked bulk mutations must fail tests.

FIT IO occurs outside the canonical write transaction in the real sync worker. Each run ingestion transaction is isolated after activity-page commit; failures do not abandon other runs. Decode success replaces laps/steps/streams atomically and keeps SHA idempotency. Missing FIT does not erase summary observations; later failed refetch does not erase a usable decode. New writes from manual mode use the same deterministic calculators, never require Garmin/network.

Corrections invalidate all affected old/new local windows, anchor histories, matches, following60 recovery-baseline nights, symptom associations and spacing. Latest result means current dependency signature, not greatest timestamp. Read-time rolling-window refresh is bounded, deterministic and derived-only; no network/model call. Scope selection and fixtures are TASK-030/metrics.md, not ad-hoc endpoint calculations.

## 4. Browser and compatibility

TASK-001 already extracted pages/components. Keep current Coach/Cycle/Overview/History/Settings/Strength/checkin flows until TASK-068. TASK-039 adds canonical schema §6 DTOs without deleting old exports. TASK-040–045 add Home/Calendar/Activity/Trends/Block and v2 checkin views; TASK-050 adds navigation/hash synchronization behind authority readiness. ProposalReview and accepted-history/undo features arrive before cutover. `useState<Page>` remains; no new router/framework.

API supplies today/timezone; browser does not compute athlete-local day from device zone. All collection wrappers `{items}`. Query-key invalidations follow source writes and accepted decisions; rejected proposals do not fabricate calendar changes. Repeat blocks render/expand interleaved identically to Python helper. Legacy unstructured prescriptions render original prose with unassessed execution, never invented targets.

Strength templates describe lifting commitments; current ProfileVersion remains sole weekly/alternating schedule authority. Existing schedule editing remains available. New editor must not silently replace confirmed rotation with weekday suggestions. Mobility and optional status survive import. No calendar roll-forward beyond last planned date.

## 5. Security, operations and acceptance

Existing local guard, loopback, mode selection, secret file permissions and provenance are retained. Raw ZIP/FIT artifacts0600 under private directory; database stream/metadata/snapshots exclude coordinates. Inventory logs only allowlisted names/types/counts, never tokens, free notes or device serials. Snapshot pins KB content digest and selected records. Application does not estimate actual model token charges.

All new DB tests run only via guarded disposable TEST_DATABASE_URL; pure tests have no DB/network/clock dependency. TASK-003 preserves full baseline behavior/tests; TASK-068 requires populated0009 upgrade/import/retry/failure/undo/export fixtures. Existing migration history is immutable. No source data rebuild or destructive D15 downgrade. G2 synthetic contracts permit implementation; representative real-device evidence remains a separate release gate, not a fabricated planning result. TASK-070 signs off after068 and applicable G2 checks.
