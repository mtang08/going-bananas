# Analytics MVP release verification

This section records the earlier analytics release. The Strong/coaching extension
is documented below. Verified locally on 2026-11-10. Scope: local analytics, visualization, feedback,
manual planning, Garmin ingestion and operations. Research/adaptive coaching and
Strong integration remain deferred. No synthetic feedback or plan was written
to the real workspace.

## Executed checks

| Check | Result |
| --- | --- |
| `make check` | Backend Ruff and mypy (23 source files), 27 domain/ingestion/config/export tests; frontend lint/types, 7 component tests and production build pass |
| `make test-integration` | 16 PostgreSQL tests pass, including import replay, conflicts, manual/import strength in both orders, feedback, privacy, plan constraints, concurrent enqueue, persistent retry limit, and partial recovery |
| `make test-e2e` | 4 Chrome tests pass: navigation and check-in; mobile layout; historical date windows; manual draft/accept/actual link/unlink. Demo mode is asserted before mutations; synthetic profile setup is explicit |
| API acceptance | `scripts/verify-demo.py`: check-in replay/edit/stale-version/null rejection, context note exclusion, manual strength totals, weekly snapshot persistence, valid/invalid cycle plans pass |
| Clean migrations | Fresh `garmin_migration_test` upgraded through `0003_app_state`; `alembic check` reports no new operations. Initial schema is frozen rather than imported from mutable ORM models |
| Real source comparison | 28-date import window; all 12 activities checked against preserved source IDs/timestamps/distance/moving/elapsed fields. Unique identities and independent rolling-14 sum match |
| Real re-import | Same window repeated: zero changed activities/recovery values and zero duplicate canonical records; valid recovery observations retained |
| Recovery availability | 82 valid observations. One sleep summary lacks its owner identifier; it is retained as rejected source data and sleep is explicitly partial. Other datasets complete their requested queries |
| Backup/restore | Final private archive restored into a new database/directory; seven table counts match and all 94 referenced raw objects exist with matching SHA256. Original database unchanged |
| Production read-only smoke | All 13 API reads pass; foreign-origin mutation rejected. Real-data browser views load, Strong warning is visible, mobile has no horizontal overflow, no page/server errors |
| Daily operation | Local launchd schedule registered for 08:30; standalone command starts the existing project database if needed. Startup catch-up and worker job coordination are implemented/tested |
| Privacy | Real raw/profile/credentials/backups/screenshots ignored; no remote or deployment configured. Configured secret-value and private-path scan of staged source passed before commit |

The full V01–V28 matrix remains the design reference. The evidence above records
what actually ran; it does not claim exhaustive provider behavior, every future
export format, every crash timing, or every wearable statistic has been tested.

## Independent review and corrections

A separate Sol-medium review identified and drove fixes for invalid UI run-kind
values, missing duplicate candidate creation, resumed retry limits, missing
startup catch-up, and partial-plan supersession. Follow-up fixes added exact
replacement boundaries, selective context coverage, manual-strength reconciliation,
and pagination. The lead also checked DST arithmetic, metric enums, validation,
protected mode separation, credential handling, connection-pinned advisory locks,
and clean migrations.

## Current limitations and intentional boundaries

- Strong lifting history is not connected. Recorded sessions are incomplete;
  missing Garmin strength records never establish skipped lifting. No Strong
  parser exists until an actual export is inspected.
- The inspected Garmin account export and API are validated ingestion paths.
  Full stream/GPS views, coaching, and phone/private hosting remain deferred.
  Unrecognized archive categories remain in the preserved original ZIP.
- No real schedule anchor or rotating strength mapping was invented. Configure
  these when ready to use accepted manual plans. No actual symptom check-in was
  fabricated for acceptance testing; that workflow was verified in demo mode.
- Garmin's maximum history/rate limits, pricing, and precise source-date boundary
  semantics are not fully documented/verified. Bounded requests, conservative
  status reporting, overlap re-fetching, and manual historical windows are used.
- Replacing an accepted plan requires its exact date range; partial overlaps
  return an explanatory validation error. This prevents silent loss of sessions.
- Build emits a non-blocking large-bundle warning (charts included); tests emit
  an upstream Starlette/httpx deprecation warning. Both complete successfully.
- Backups are private plaintext archives, not encrypted cloud storage. Credentials
  are excluded. Restore into a new target and verify before selecting it.

## Runtime/tool evidence

Python 3.12.13, Node 22.23.4, PostgreSQL 17.11, uv 0.13.7 were available for this
run. Package versions are captured in committed lockfiles. The official Garmin
Python client is 1.0.0. See `garmin-capabilities.md` for inspected provider docs.

## Historical export acceptance (2026-11-10)

- Imported 179 activities: 167 new, 12 API overlaps unchanged; 163 runs. Activity
  dates span September 4, 2025 through November 8, 2026.
- Imported 429 sleep, 416 HRV, and 434 resting-HR source observations. Canonical
  history now contains 1,282 recovery observations, including prior API data.
- All activity units/timestamps and every recovery value were independently
  compared with original sources by `scripts/verify-export.py`. Run-volume sum
  matches; profile/check-in/plan counts and existing API fields are unchanged.
- Sleep uses GMT window minus awake seconds; HRV uses the typed HRV metric.
  Each recovery mapping matched all 27 overlapping API dates per metric.
- Six incomplete sleep rows and 43 missing resting-HR rows remain gaps. Another
  1,664 unsupported health metrics remain preserved without normalization.
  Observed date coverage is partial, not a guarantee of full account coverage.
- Identical archive replay produced zero new revisions and zero canonical changes.
  All 1,572 raw-object checksums pass, including the untouched original ZIP.
- Synthetic tests cover both recovery source orders, API activity precedence,
  malformed/unsafe archives, source-byte preservation, and replay coverage dedupe.
- Real read-only Chrome smoke verifies historical activity display, import
  coverage/status and mobile layout. Screenshots remain private.
- Post-import backup contains 1,574 files; restore into a new isolated target
  verifies seven table counts and all 1,572 raw references/checksums.


# Strong and local coaching extension — November 10, 2026

The active runtime is an explicit local evidence-guided rule flow. It offers
conservative daily options and weekly proposals from current inputs and selected
research prose. It makes no external model call, exact dose progression,
diagnosis, clinical clearance, or automatic plan change. The supplied 15
behavioral cases remain a design/evaluation set; this release has targeted tests,
**not all 15 cases exercised end to end**.

| Check | Executed result |
| --- | --- |
| Research integrity | 20 original manifest hashes verified; four standalone files byte-identical to archive copies. Reviewed, generalized corpus hash-checked at load time; private athlete snapshot and originals are ignored. |
| Strong source comparison | 512 workouts and 8,168 sets match the original CSV by identity, payload, start, duration and recorded set text; preserved CSV bytes match. June 7, 2021–November 9, 2026. 118 overlong timers have unknown normalized duration. |
| Running context boundary | November 10, 2026 minus 18 calendar months is May 10, 2025; 143 Strong sessions enter context. Older sessions remain in history. No weight-unit or dumbbell convention inference. |
| Database migration | Test, demo, and real upgraded through `0007_coaching_selection`; `alembic check` found no pending operations. Outcome events are append-only; cached selection time is persisted. |
| `make check` | Ruff and mypy pass (32 backend source files); 45 backend tests pass; frontend lint/types, 15 component tests, and production build pass. |
| `make test-integration` | 22 PostgreSQL tests pass, including five coaching endpoint and one Strong import test. |
| Demo browser | Six Playwright tests pass on synthetic demo data, including Coach generation/stale/feedback and Strength detail/mobile flows. |
| Real API/browser | 18 read-only API GET checks plus rejected foreign-origin mutation pass. Production browser smoke shows Coach and connected Strong on desktop/mobile without overflow; screenshots remain private. No real symptom, plan, or outcome was invented. |
| Existing real data | Pre-change backup restored in isolation; exact row-content digests unchanged for two profiles, 179 Garmin activities, 1,282 recovery observations, and zero check-ins/manual sessions/plans. |
| Post-change backup | Private archive created at 03:39:25 UTC with 1,581 files and restored to a new isolated test DB/directory. Eleven table counts, complete Strong/coaching table row digests, 1,573 raw checksums, and six research original files match; source DB untouched. |
| Privacy | Candidate tracked files checked for raw CSV, private snapshot, key material and local secrets before commit. Private backups/screenshots remain ignored. |

Supported targeted behavior includes unknown inputs, worsening symptoms/illness
precedence, source/plan staleness, conservative alternatives, append-only outcome
feedback, and no automatic plan mutation. Still unsupported: exact personalized
run/strength dose and placement, calibrated favorable progression, full delayed
multi-day symptom assessment, previous-period trend comparison, and the complete
15-case behavioral suite. Missing symptoms and an unconfirmed real cycle are
user inputs for better advice, not development blockers.
