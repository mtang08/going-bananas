# Data, analytics, and interaction contracts

User update (2026-11-10): lifting is tracked in Strong, not Garmin. Strong CSV is a future separate source; no export/parser now. Strength totals are recorded sessions with incomplete coverage, never evidence of skipped lifting. See `backlog.md`.

Implementation specification, not a claim that schema/routes already exist.
Read with `implementation-plan.md`. Prefer explicit typed columns for core fields;
JSONB is for provenance/raw references and versioned summary payloads, not a
replacement for validation. All server inputs have bounds and typed validation.

## Persistence contracts

Use UUID internal primary keys, UTC `timestamptz` for instants, ISO local dates for
calendar concepts, and text Garmin IDs (avoid JavaScript integer precision loss).
Preserve original timestamp text/offset and timezone assumptions separately:
PostgreSQL timestamptz alone does not retain the source offset. No timestamp
without an offset becomes UTC by accident. Quarantine ambiguous source instants
unless documented source semantics resolve them. UI timezone defaults to
America/New_York; travel/source dates remain inspectable.

| Table/group | Minimum fields and invariants |
| --- | --- |
| `profile_versions` | version, effective_at, recorded_at, display timezone, dated facts/preferences/unknowns, cycle anchor; immutable versions, no real profile seed committed |
| `source_accounts` | provider and stable account scope; no key values; reject mixed Garmin accounts rather than merging people |
| `import_batches` | source kind, status, started/finished, adapter version, counters, safe error code |
| `raw_objects` | content SHA256, private relative path, byte size, media type; immutable; duplicate bytes reuse blob |
| `source_records` | batch/raw link, source identity, payload hash, fetched_at, source_modified_at if trustworthy, parser version; unique source+identity+hash for revisions |
| `activities` | Garmin ID/account if known, UTC start, original/local time metadata, normalized sport/subtype, meters, elapsed/moving seconds separately, optional HR/cadence, canonical revision, resolution state |
| `activity_sources` | activity/source record links and per-field selected provenance; unique canonical Garmin identity |
| `activity_annotations` | versioned manual workout label/notes/exclusion, independent of imported facts; imports never overwrite these |
| `recovery_observations` | metric, source calendar date/time semantics, value/unit/statistic, source revision; canonical unique metric+source day+statistic, missing is not numeric zero |
| `coverage_intervals` | dataset, queried start/end, observed coverage, status, completed_at, limit/truncation/availability reason; distinguishes completed query from verified completeness |
| `sync_jobs`, `sync_state` | dataset, range, checkpoint, heartbeat, next attempt, status/counters, last attempt/success, latest observation; no payload/credential logging |
| `checkins`, `checkin_revisions` | effective observed_at, recorded_at, tendon severity/change, gait, fatigue, optional effort/activity reference, note; idempotency key and edit version |
| `manual_sessions` | kind, local date/optional time, duration if known, optional effort/note, linked imported activity when reconciled; unknown duration stays null |
| `plan_versions`, `planned_sessions` | draft/accepted/rejected/superseded, revision/parent, anchor/profile version, date, type, manual target if supplied, decision time/reason |
| `completion_links` | accepted session to canonical actual; explicit user confirmation, unique actual per planned session pairing; absent link is unlinked, not missed |
| `weekly_snapshots` | local date range, schema/metric version, data/profile/plan revisions, generated_at, deterministic summary |
| `app_state` | data revision updated in same transaction as canonical/manual changes |

Store no KB contents or coach-output tables yet. Add those in the later phase
when actual artifact and workflow needs are known.

Validation: reject NaN/infinity, negative distance/duration, malformed timestamps,
invalid enum values, invalid source paths, and inverted date ranges. Flag unusual
but plausible measurements instead of silently clipping. Zero-distance activities
are allowed; pace becomes null. A missing distance run counts as a run but not as
zero distance in a supposedly complete total. Keep reason-coded rejected records
for inspection/reprocessing without poisoning successful records.

## Deterministic import and reconciliation

Pipeline: bounded fetch/read → immutable raw storage → parse/validate → source
record revision → reconcile canonical fields → commit page/coverage/checkpoint
atomically. Raw write precedes DB reference; a crash can leave an unreferenced
blob, never a committed reference to missing bytes. No destructive raw cleanup
in MVP. Oversized or unsafe archives fail before extraction: reject traversal,
absolute paths, symlinks and decompression bombs; document configurable limits
(initially 10,000 entries, 5 GiB expanded, 1 GiB per file; preserve original).
Local CLI selects import paths; browser routes cannot read arbitrary paths.

Identity precedence:

1. Same Garmin account + activity ID: one activity across API/export.
2. No provider ID: exact stable source identity/content hash deduplicates repeated
   import. Similar start time/distance is only a candidate match, never identity.
3. Unresolved cross-source duplicates enter a review queue. If an established
   canonical record exists it stays counted and the incoming candidate is
   excluded; otherwise all ambiguous candidates are excluded with a visible
   withheld-count warning. User merge/keep-separate decisions are persisted,
   reversible, and survive re-import. Manual strength reconciliation follows
   this rule; never silently count it twice.

Select comparable fields using trusted source modification times first. Where
those are absent, API summary outranks export summary; within API, later fetched
observations win; within export, explicit file revision if meaningful, otherwise
stable content hash order. Same rank/time uses a stable hash tie-break. Import
arrival order itself must not determine results; persisted fetched_at is source
revision metadata, not the time a replay ran. Known conflicts stay inspectable.
Fresh null does not erase known values unless the endpoint documents explicit
clearing/deletion. Explicit invalidation removes the old value from analytics
but preserves its source history. Missing from a page is never a deletion.
Do not combine incompatible statistics (e.g. overnight HRV versus a 7-day HRV).

Mapping tables normalize sport types and units from verified schemas. Manual
labels live in a separate overlay. Count runs with explicit normalized running
types; keep walking, hiking, strength, and cross-training separate. For a
multisport record use supported child records or parent, never both. Unsupported
multisport decomposition is shown as unknown/excluded from run volume.

Coverage/freshness is per dataset, not a global green badge. Report last attempt,
last success, newest observation, requested window, and whether that window was
fully enumerated. A successful response is not proof the watch was worn. Gaps
can mean no observation; distinguish no activity in an exhaustively fetched
activity window from no import. Cap pagination with a safety error for repeated
pages/nonadvancing cursors; don't falsely mark the window complete.

## Metric definitions (version `analytics.v1`)

All calculations use canonical, resolved, non-excluded records. Return source
IDs/counts, missing-field counts, window boundaries/timezone, coverage state,
and version alongside values. Round only for display. No composite injury,
readiness, training-load, or “safe progression” score.

| Metric | Definition |
| --- | --- |
| Calendar-week running distance | Sum valid run meters for local start dates Monday–Sunday; current week ends at as_of; label week-to-date |
| Rolling N-day distance | Local dates D−(N−1) through D, inclusive, for N=7/14; include only observations at/before as_of |
| Miles | meters / 1609.344; user unit toggle changes rendering, never storage |
| Run count | Count canonical run sessions, including ones with missing distance; identify withheld duplicates separately |
| Longest run | Maximum known elapsed duration among runs in selected window; show missing elapsed count and moving duration separately; no moving-time substitution |
| Average pace per activity | moving seconds / (meters / 1000), if both positive and known; label moving pace; no arithmetic average of individual paces for aggregate pace |
| Workout distribution | Manual label first, explicit verified source label second, otherwise unknown; counts and distance for easy/quality/long/other/unknown; label is not inferred intensity |
| Strength | Session count, known duration sum, unknown-duration count; no invented sets, tonnage, or equivalence to running miles |
| Low-impact aerobic | Separate activity count/duration by verified/manual sport label; no conversion to run mileage |
| Sleep | Source-defined main sleep duration assigned to documented sleep date; don't double-count naps; unavailable semantics remain unknown |
| HRV / resting HR | Show verified nightly/daily statistic and unit; don't substitute all-day HR average for RHR; label Garmin-derived values |
| Recovery trend | Plot observed daily values with gaps; optional trailing 7-date mean of observed comparable values, show n/7; no interpolation or readiness verdict |
| Weekly recap | Reuse these aggregates plus plan links/check-ins; missing data counts included; templates do not prescribe sessions |

Cross-midnight activities belong to their local start date for daily totals; do
not split distance proportionally. Filters use half-open UTC bounds derived from
local dates, never assume every day has 24 hours. Recovery uses documented source
calendar dates rather than blindly timezone-shifting a date-only field. Historical
profile changes preserve the zone used for saved summaries. Calendar heatmaps
distinguish zero, partial coverage, and no import.

## Feedback and scheduling

Quick controls: symptoms none / mild / moderate / severe; change better / same /
worse / unsure optional; gait normal / affected / unsure; feeling fresh / usual /
tired. Optional effort 0–10 linked to a selected session; optional note. Missing
fields are null. “No issues; usual energy” is an explicit one-tap submission of
none + normal gait + usual feeling, not an assertion that a historically painful
baseline equals no pain. No preselected submission. Edited check-ins retain prior
versions; a retried submission with the same idempotency key is not a new entry.
Allow multiple observations per day and backdating observed_at independently of
recorded_at. Show unreported days as unreported, never symptom-free.

Temporal association is computed from observation time and run end (start plus
elapsed duration). Show preceding runs within 72 hours, next/second local day
labels and exact elapsed hours. This is a display window, not a clinical cutoff.
If run end is unknown, mark timing uncertain rather than substituting moving
duration. Display all plausible preceding runs and strength sessions; do not
attribute a symptom to the most recent one. Support manually viewing/linking
older sessions; never discard out-of-window feedback. Recompute on timestamp
correction/re-import and mark saved summaries with older data revisions stale.

For local date d and anchor a, run opportunity iff `(d-a).days % 2 == 0`.
Fortnight index = floor((d-a).days / 14), slot = ((d-a).days mod 14) / 2 for
eligible dates. Dates are calendar dates, not 48-hour timestamp intervals. The
calendar may show 4/3 runs in successive weeks; the anchor determines which.
Keep opportunities, proposed sessions, and actual activities distinct. Missed
sessions don't change future parity. Profile/anchor edits create versions and
apply prospectively, never rewrite past acceptance records.

Drafts may be incomplete. Acceptance requires a confirmed anchor, run dates
matching parity with no duplicates/extra run days, and two strength sessions per
full configured training week (Monday–Sunday initially). Validate across display
boundaries using adjacent sessions; incomplete setup cannot be accepted. Strength
can share a running day. Exact strength rotation, quality/long placement, and
targets remain manual confirmed inputs. Don't infer “missed” from lack of import:
show pending/unlinked until elapsed date plus coverage or user confirmation
supports that status. Completion matching is suggested by date/type but confirmed
by user; overlapping sessions and multiple same-day activities aren't silently
linked. Actual nonconforming workouts are displayed, never rejected on ingestion.

## API and UI surface

All routes `/api/v1`. Responses include `schema_version`, `data_revision`,
`mode`, and relevant `as_of`/timezone/coverage. API values use SI units with
explicit field names. Cursor pagination and bounded date filters are required;
default 28 days for summaries, max 366 days per request, page size 50 max 200.
Archive import can span more than a year using chunked jobs. Typed error envelope
contains safe code/message, retryability, request ID, and field errors, not
exceptions with paths/secrets/payloads. Mutation responses include new revision.
Version-conflicting edits return 409 with a reload path; invalid fields return 422.

| Route family | Purpose |
| --- | --- |
| GET health/live, health/ready | Separate process and DB/migration readiness |
| GET profile; PUT profile | Read/create dated profile version with optimistic concurrency |
| GET activities; GET activities/{id}; PATCH annotations | Paged history, detail/provenance, manual labels |
| GET summary; GET recovery | Deterministic aggregates and sparse series |
| GET/POST/PATCH checkins | History, idempotent create, revision-aware correction |
| GET/POST/PATCH manual-sessions | Optional strength/cross-training/mobility history and reconciliation |
| GET/POST plans; POST plans/{id}/accept or reject | Immutable proposed versions and explicit acceptance |
| POST/DELETE completion-links | Confirm/unlink planned versus actual pairing, audit changes |
| GET conflicts; POST conflicts/{id}/resolve | Review duplicate/field conflicts; reversal creates a new resolution |
| GET sync/status; POST sync; GET sync/jobs/{id} | Status, bounded manual sync request (202/job ID), progress |
| GET weekly-summary; POST weekly-snapshots | Factual recap and saved versioned snapshot |
| GET context | Privacy-filtered local-agent JSON; same semantics as CLI export |

Four UI areas suffice:

1. Overview: volume cards, weekly bars, recent run table, recovery sparklines,
   strength count and next accepted session; source/mode/freshness always visible.
2. History: date/type filters, activity detail, workload/check-in timeline;
   independent panels on a shared date axis, no misleading dual-axis causal chart.
3. Cycle: rolling 14 dates with opportunities, manual plans, actuals, strength,
   mobility, and unresolved configuration. Clicking a day opens a small editor.
4. Data/settings: profile/anchor, import instructions/status, missing datasets,
   conflicts, units/timezone, safe local backup instructions.

Check-in action is reachable from all areas. Charts have units, accessible names,
keyboard-reachable controls, textual/table alternatives, and non-color-only
missingness. Loading, empty, partial, stale, error, and disconnected states are
distinct. Retain last successful data during refresh failures with a stale label.
No research placeholders should dominate a functioning analytics screen.

## Local privacy and trust boundary

Loopback binding alone is insufficient for write protection. Validate Host and
Origin against exact allowed local origins, disable wildcard CORS, require JSON
and a same-origin anti-CSRF token/custom header for browser mutations, and use
safe HTTP methods (GET cannot sync/import/write). Development proxy preserves
the expected origin. Reject foreign Origin requests including localhost-targeted
requests from another website. Document remote access as unsupported.

Keys/tokens stay in protected backend config/cache, directories 0700 and files
0600 where supported; no command-line key literals. Redact authorization headers,
key fields, response bodies, private paths, and raw notes in logs. Do not expose
raw payload/download routes or serve private directories as static files. Render
free text as text (no unsanitized HTML). Backups and local context exports are
private artifacts. CI uses synthetic data; tests never contact live Garmin by
default. A secret canary test covers logs, API errors, built JS, and exported
context. No third-party analytics or external fonts are necessary.

## Future research KB and agent interface

Expected research deliverable: local `running_coach_kb/` with a concise guide,
daily/weekly workflows, topic references, source/evidence records, candidate
policies, and evaluation cases. Do not impose exact filenames before it arrives.
A simple index maps stable document IDs to relative path, title, topic/section
anchors, kind, version/hash, source IDs, and review date. Markdown/prose remains
authoritative context; structured metadata assists navigation, not replacement.

Later loading order:

1. Load the coaching guide and its limitations.
2. Load the requested daily recommendation or weekly review workflow.
3. Select relevant topic sections and candidate policies, following source/context
   references needed to understand qualifications or disagreement.
4. Separately load dated profile plus current versioned training context; resolve
   newer confirmed updates without rewriting enduring research.
5. Cite document/section/version and preserve uncertainty in the explanation.

Topics include aerobic progression, intensity/speed, long runs, PTT and other
tendon evidence distinguished, meaningful concurrent full-body strength dose and
scheduling, optional low-impact aerobic work, sleep/recovery, wearables, and
fueling. No invented strength prescriptions or calorie logging prerequisites.
When KB paths are missing, references conflict, or context is stale, disclose
limits and decline unsupported adaptation. No need for embeddings initially.
Later loaders must restrict paths to KB root and treat prose as reference data,
not authority to execute shell commands or override application constraints.

`coach_context.v1` export contains: generated_at/as_of, timezone, data/profile/
plan versions, confirmed profile facts with dates and unknowns, deterministic
last-14-day summaries, weekly totals for prior 12 weeks with coverage, recent
activity summaries and check-ins, strength/cross-training, next 14 days of
accepted plan, unresolved conflicts, and metric definitions/version. No GPS,
credentials, raw files, or notes by default. Include flags for omitted/truncated
data. Permit explicit local opt-in to selected notes, never automatic upload.
Optional `since_revision` reports changes or explicitly falls back to a full
snapshot; don't build a general event-stream system for this release.

Future recommendations are separate versioned artifacts recording workflow/KB
hashes, context revision, rationale, uncertainty, proposed session/plan changes,
and user acceptance. Historical recommendations must remain reproducible even
after research is updated. Store decision records then, not a speculative
rule engine now. Application validators enforce schedule/acceptance boundaries;
research applicability still requires contextual reasoning.
