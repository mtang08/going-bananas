# Garmin dashboard foundation

Historical initial proposal. Superseded by `implementation-plan.md`,
`contracts.md`, `verification.md`, and `handoff.md` following the user's scope
clarification. In particular, research and adaptive coaching are a later phase,
not analytics MVP requirements; the KB will preserve selectively loaded prose
and workflows rather than reduce research to executable policy records. Use the
new contracts for check-in controls, reconciliation, and implementation tasks.

Status: proposed foundation, 2026-11-10. Repository was empty; no applicable
AGENTS.md found. No application, imports, research, or coaching is active yet.
Private source brief: `private/context/garmin_coach_seed_prompt.md` (ignored).

## Scope and first milestone

Single-user, local Mac application. First deliverable: a thin React dashboard
backed by persistent data, with recent runs, volume, a quick check-in, and a
continuing fortnight view. Start with conspicuously labeled synthetic fixtures
in an isolated demo dataset. Replace those with one small real import as soon
as credentials or an export are available. Demo delivery is not completion of
the real-data MVP.

First end-to-end milestone: import real activities idempotently, show their
freshness and deterministic metrics, save feedback across restarts, associate
later symptoms with preceding runs, and compare a manually accepted session
with its completion. A factual weekly summary works without a model. Adaptive
session suggestions follow the research gate below.

Defer workout publishing, automatic plan rewrites, chat, predictions, multi-user
features, phone access, hosting, and elaborate charts.

## Architecture and storage

React + TypeScript + Vite → Python FastAPI → PostgreSQL. Choose PostgreSQL to
honor the user's familiarity and preference; one local database service is the
accepted setup cost. Do not implement SQLite as a second backend. Node, Docker,
and psql were not found on this shell's PATH; installation or discovery is an
implementation prerequisite, not proof they are absent from the machine.

Keep Python ingestion adapters, pure analytics functions, scheduling validation,
and coaching orchestration separate. Bind locally initially. Secrets belong in
backend-only protected configuration; never frontend variables or model inputs.
Immutable raw payloads live under ignored private storage, referenced by hash.
Synthetic fixtures must contain no real coordinates or athlete observations.

Minimal persistent entities:

| Entity | Essential contents |
| --- | --- |
| Athlete profile versions | Dated preferences, confirmed facts, unknowns, cycle anchor |
| Import batches / source records | Source, raw hash/path, source identity, timestamps, parser version |
| Activities / recovery observations | Canonical identity, values and units, source links, missingness, revisions |
| Sync state | Per-dataset cursor, last attempt/success, coverage, partial failures |
| Check-ins / symptom associations | Observation time, symptoms, gait, fatigue, optional effort/note, candidate preceding activities and elapsed hours |
| Plan versions / sessions | Proposal, acceptance/rejection, intended date/type, completion link, rationale |
| Research snapshots / policies | Version, sources, applicability, confidence, review/activation state |
| Coach outputs / model calls | Input fingerprint, evidence/profile/plan versions, structured decision, tokens, latency, cost if known |

Metrics are reproducible computations, not LLM arithmetic. Store timestamps with
source timezone/offset preserved; default display is America/New_York. Normalize
distance to meters and durations to seconds. Distinguish elapsed and moving time.
Use local calendar dates for scheduling, including across DST transitions.

## Import strategy

Before API implementation, inspect current Swagger and client code for actual
activity/recovery coverage, pagination, history/date limits, rate limits, terms,
and pricing. Unknown coverage is not a supported feature. Verified starting
points on 2026-11-10:

- https://developer.garmin.com/gc-developer-program/personal/personal-api/
- https://developer.garmin.com/gc-developer-program/personal/personal-faq/
- https://github.com/garmin/connect-personal-api-python

Garmin documents personal keys exchanged for access tokens; access tokens last
up to 24 hours or key expiration, with no refresh tokens. The official client
provides token caching/exchange and currently requires Python 3.12+. Personal
keys separately expire and can be revoked. Do not assume all health metrics are
exposed. Rate limits, pricing, and endpoint-specific history remain unverified.

Use the official Python client for deterministic ongoing sync. Inspect the real
export's manifest, formats, units, timestamps, identifiers, and sample records
locally before writing an export parser. Build whichever real path is available
first; do not build two broad adapters speculatively.

Canonical activity identity is Garmin activity ID where available, independent
of source. Keep source revisions. For same-ID overlaps, prefer the latest
explicit source revision for comparable fields; if revision dates are absent,
prefer API summary fields and export-only detail, with stable hash tie-breaking.
Missing values never erase known values without an explicit deletion signal.
Record field provenance and conflicts. No-ID records use stable source hashes
for repeat-import detection; possible cross-source matches are quarantined for
resolution, not silently merged or double-counted in confirmed totals.

Sync uses a shared service for manual action, startup catch-up, and a later
macOS launchd daily job. Use bounded recent re-fetch windows configurable per
dataset after checking API limits; older bootstrap uses separate checkpoints.
Commit successful pages/datasets with resumable state. Serialize overlapping
syncs; honor Retry-After, bounded backoff, and authentication failures. Report
partial success and stale datasets visibly without deleting prior observations.

## Dashboard and input contract

Overview: recent runs, calendar-week and rolling 7/14-day volume, longest run
duration, workout distribution, available recovery trends, and planned/completed
sessions. Explain windows and units. Distinguish an observed total over partial
coverage from a complete total; absent observations are not zero. Workout type
is explicitly imported/manual or unknown, never inferred from one pace.

Check-in: tendon none / usual / worse; walking/gait normal / affected; feeling
fresh / usual / tired; optional session effort and note. A single “usual / no
issues” action explicitly records no symptoms, normal gait, and usual feeling;
use this shortcut only where it reflects the person's defined baseline. Never
pre-submit it or equate a missing check-in with recovery. Support corrections.

Show next-day and second-day symptom observations alongside candidate preceding
runs, with elapsed hours and overlapping strength load visible. Associations are
temporal context, not attribution or evidence of causality. Preserve observations
outside those windows rather than imposing a permanent tendon-response cutoff.

## Scheduling and coaching contract

Anchor the every-other-day cycle to a confirmed local run date. Generate seven
run opportunities per 14 days by date arithmetic; never restart on Monday or
silently add days. Until an anchor is confirmed, real dates remain unassigned.
Preserve twice-weekly strength and mobility; exact rotating strength mapping
and quality/long-run placement need confirmation only when scheduling begins.
Account for running, lower-body strength, and rehab together.

Do not prescribe paces/zones from one run, a race time, or watch estimate. Treat
athlete facts as dated and verify recent volume from actual imported coverage.
No universal progression rule or automatic readiness threshold. No diagnosis.

Structured coach output: proceed / modify / rest, suggested session, short
reason, observed facts, calculated metrics, hypotheses, uncertainty, evidence
IDs, and proposed changes. Validate schema, cycle, strength constraints, and
research activation before presenting it as actionable. Rejected or unsupported
outputs fall back to accepted session display and a visible limitation.
Changes require acceptance and retain their prior plan versions.

Model context: compact profile version + computed 14-day summary and longer
baseline aggregates + data coverage/freshness + symptoms and combined load +
accepted plan segment + relevant compact policy IDs + last review/change delta.
No secrets, routes, raw streams, or full literature report. Cache by relevant
data/profile/plan/policy/model versions; invalidate on corrections as well as new
data. No model call on routine page rendering. Daily and weekly outputs persist.

Runtime model choice is deferred to representative-case evaluation and current
official capability/pricing verification. Start with no runtime model dependency;
later prefer the lowest-cost model that passes coaching/schema evaluations.
Escalate ambiguous evidence or conflicting context for review, not automatic
medical inference. Coding-agent model preferences do not select the app model.

## Research and activation gate

The separate `garmin_training_research_prompt.md` was not found at the sibling
Downloads path. Obtain its location before commissioning that specified review;
data/UI work can continue independently.

Expected snapshot: full report, evidence table, compact policy records, source
dates, population applicability, confidence, disagreements, limitations, and
review dates. Cover the requested aerobic/progression, intensity, long-run,
speed, concurrent strength, tendon, recovery, and wearable topics. Distinguish
PTT evidence from extrapolation, research from heuristics, and observations
from recommendations.

Gate: import/version artifacts → review proposed policies → explicitly accept
constraints and structural changes → pass representative evaluations → activate
only accepted policies. Research ingestion alone cannot activate coaching.
Before this gate, show descriptive summaries and accepted/manual sessions;
synthetic coaching demonstrations must be labeled and cannot become real plans.

## Small implementation increments and acceptance criteria

1. Scaffold frontend/backend/PostgreSQL with isolated demo records and clear
   setup instructions. Dashboard and check-ins work without any model or key;
   feedback survives restart and demo records cannot mix with real history.
2. Implement one verified real import. Re-import and export/API overlap tests
   produce one canonical activity. Test pagination, retries, partial failure,
   timestamp offsets, DST, units, missing values, and stable conflict resolution.
3. Add deterministic metrics and the feedback/cycle view. Hand-computed fixtures
   match weekly/rolling totals; tests cover week/year boundaries, delayed symptom
   associations, overlapping workouts, and missing recovery data.
4. Add manual sync, startup catch-up, and a local daily job. A missed laptop run
   catches up; revised recent records invalidate affected summaries; failure in
   one dataset preserves other successes and exposes freshness independently.
5. Import research, review policies, and evaluate structured coaching in shadow
   mode. One poor sleep night alone must not automatically cancel training;
   worsening symptoms cannot be overridden by favorable wearable scores;
   missing recovery metrics remain unknown; extra run days and unaccepted plan
   rewrites fail validation. Add model telemetry and cache invalidation tests.
6. Activate reviewed daily guidance and weekly reviews, retaining proposed versus
   completed sessions, subsequent symptoms, acceptance decisions, and a simple
   later helpfulness response. Demonstrate the full loop on real data.

## Handoff and unresolved inputs

Next step: scaffold increment 1 and finish API capability inspection. No athlete
question blocks that reversible work. Research prompt location blocks only the
specified research review. Real import needs an export path or locally configured
key (never pasted into chat). Confirm cycle anchor and placement only before
assigning real sessions. Rehab instructions, symptom pattern, strength details,
and tentative races remain unknown and must not be silently filled in.
