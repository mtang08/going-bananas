# Going Bananas — data, API, and CLI contracts (MVP-1.0, 2026-11-11)

Baseline: `going-bananas` `main` @ `5ebf981aa4517f4f73f3c97aa5d43232204466ce`. Decision refs → `decisions.md`. Metric refs → `metrics.md`.
All SQL types are PostgreSQL 17 via SQLAlchemy 2.1 / Alembic. Every new model follows existing conventions:
`uuid_pk()` (`backend/app/models.py:26`), `DateTime(timezone=True)` for instants, `Date` for local dates, JSONB for structured payloads, Python enums stored as `String` with a `CheckConstraint` listing allowed values.

## 0. Global conventions

| Topic | Rule |
| --- | --- |
| Instants | UTC `timestamptz`; API ISO 8601 with offset |
| Local dates | `date`, computed in the profile IANA timezone (E5) |
| Units | s, m, m/s, bpm, °C; RPE and severity as `numeric(3,1)` 0–10 |
| Enums | `String(40)` + `CheckConstraint("col IN (...)")`, constraint name `ck_<table>_<col>` |
| Writes | every user-visible change calls `bump_data_revision(session)` (`backend/app/db.py:30`) |
| Optimistic locking | mutable rows carry `version int not null default 1`; writes send `expected_version`; mismatch → 409 `version_conflict` (existing pattern `api/core.py:433-437`) |
| API envelope | unchanged: `{schema_version:'v1', data_revision, mode, data}` (`api/core.py:53`) |
| API errors | unchanged: `{error:{code,message,retryable,request_id,fields[]}}`; all new errors raise `fail(code,msg,status)` from `app.api.core` (never `HTTPException` with a string detail — avoids the code-loss defect at `main.py:58`) |
| Readiness | `/health/ready` compares DB head to `app.migrations_head.EXPECTED_HEAD` (new constant module) instead of the literal at `main.py:85` |

## 1. Migration plan

One integration owner implements TASK-003. Existing revisions through `0009_agent_plan` remain unchanged. Every migration is additive; old tables, model imports, endpoints, exports and UI stay operational until TASK-068. Database readiness advances to `0015_coach_v2` together with this foundation deployment.

| Revision | Added content |
| --- | --- |
| `0010_ingest_fit` | FIT tables, nullable activity columns/status |
| `0011_checkins_v2` | `checkins_v2`, `checkin_v2_revisions`, symptoms, RPE; legacy `checkins` untouched |
| `0012_calendar` | calendar tables, `app_state.calendar_head_version=0`, `planning_authority='legacy'`, migration mapping tables |
| `0013_blocks_goals` | blocks, goals, events, strength templates; existing profile recurrence retained |
| `0014_anchors_metrics_prompts` | anchors, metrics, prompts; late prompt FK |
| `0015_coach_v2` | new coach tables and late cross-module FKs; existing recommendations/outcomes and agent history retained |

TASK-068 performs the populated-data import and authority switch only after replacement services/UI/Codex helper and latest eligible legacy undo adapter are ready. It is not an Alembic destructive rebuild. See §7. Old source rows, revision payloads, evidence and completion links remain immutable archives after switch. No downgrade that would lose new rows is permitted: fail with an actionable restore instruction before any DDL if a newly created table is nonempty. Empty-schema downgrades reverse only additions. Export/restore covers both generations and migration mappings.

## 2. Tables

Notation: `col type [null] [default] — note`. PK `id uuid` unless stated.

### 2.1 FIT ingestion (0010)

**`activities` — added columns**
- `timer_s float null` — FIT session `total_timer_time`; else Personal API `duration` (`GATED`)
- `end_at timestamptz null` — `start_at + elapsed_s`
- `fit_file_id uuid null fk fit_files.id`
- `workout_rpe numeric(3,1) null` — FIT session field 193 ÷ 10 (`GATED`)
- `workout_feel smallint null` — FIT session field 192
- `fit_status String(20) not null default 'not_fetched'` — `not_fetched|fetched|decoded|unavailable|decode_error`

**`fit_files`**
- `raw_object_id uuid fk raw_objects.id unique` — ZIP bytes stored via existing raw store
- `activity_id uuid fk activities.id unique`
- `zip_sha256 String(64)` — raw ZIP identity, including failed extraction
- `last_attempt_at timestamptz null`, `last_error String(100) null`
- `fit_sha256 String(64) null` — hash of the extracted `.fit` member
- `profile_version String(20) null` — from file header
- `sdk_version String(20) null` — `garmin-fit-sdk` version used to decode (`21.221.0`)
- `decoded_at timestamptz null`, `decode_error String(100) null`
- `message_inventory jsonb` — `{message_name: count}` for G2 audit
- `device jsonb` — file_id + device_info summary (manufacturer, product, software)

**`activity_laps`**
- `activity_id uuid fk`, `lap_index int` — UQ(activity_id, lap_index)
- `start_at timestamptz`, `timer_s float null`, `elapsed_s float null`, `distance_m float null`
- `avg_speed_mps float null`, `avg_hr_bpm float null`, `max_hr_bpm float null`
- `lap_trigger String(30) null` — `manual|distance|time|session_end|...` as decoded
- `wkt_step_index int null` — FIT lap field 71

**`activity_workout_steps`**
- `activity_id uuid fk`, `message_index int` — UQ(activity_id, message_index)
- `step_name String(100) null`, `intensity String(20) null` — `active|rest|warmup|cooldown|recovery|interval|other`
- `duration_type String(30)`, `duration_value float null` — time in s, distance in m (scaled per FIT profile)
- `target_type String(30) null`, `target_low float null`, `target_high float null` — speed in m/s, HR in bpm
- `repeat_from int null`, `repeat_count int null` — for `repeat_until_*` steps

**`activity_streams`** (one row per activity; arrays aligned by index)
- `activity_id uuid pk fk`
- `t_s int[]` — seconds since session start
- `hr_bpm smallint[]`, `speed_mps real[]`, `distance_m real[]`, `altitude_m real[]`, `cadence real[]` — nulls allowed per element
- `timer_on int[][]` — `[[start_s, end_s], ...]` reconstructed from Event msg 21
- `sample_count int`, `max_gap_s int`

Position (lat/long) is **not** stored outside the raw FIT (privacy; not needed in P0).

### 2.2 Check-ins, symptoms, RPE (0011) — D6, D8

**`checkins_v2`** (`Checkin` in `app/checkin_models.py`; legacy `app.models.Checkin` stays)
- `idempotency_key String(100) unique`, `version int default 1`
- `kind String(20)` — `exception|post_run|delayed_followup`
- `observed_at timestamptz`, `recorded_at timestamptz default now()`
- `fatigue numeric(3,1) null` — 0–10
- `illness String(10) null` — `none|possible|present`
- `gait_change String(10) null` — `yes|no|unsure`
- `context_tags String(30)[] not null default '{}'` — subset of `heat|travel|poor_sleep|unusual_surface|equipment`
- `activity_id uuid null fk activities.id` — the run this check-in follows up
- `prompt_id uuid null fk prompts.id`
- `note text null`
- `schema_version smallint default 2`

**`checkin_v2_revisions`** (v2; written on every PATCH, before applying it)
- `checkin_id uuid fk`, `version int` — UQ(checkin_id, version)
- `payload jsonb` — full prior check-in incl. its symptom reports
- `recorded_at timestamptz default now()`

**`symptom_reports`** (0..n per check-in)
- `checkin_id uuid fk`, `site String(60)`, `side String(10)` — `left|right|both|na`
- `severity numeric(3,1)` — 0–10 (0 valid)
- `timing String(20)` — `during|immediately_after|next_morning|hours_24_48|later|unknown`

**`session_rpe`**
- `activity_id uuid null fk`, `strong_workout_id uuid null fk strong_workouts.id`, `manual_session_id uuid null fk`
- CHECK exactly one subject non-null
- `rpe numeric(3,1)` — 0–10
- `source String(12)` — `manual|garmin_fit`
- `collected_at timestamptz`, `collection_delay_s int null`
- UQ(activity_id, source), UQ(strong_workout_id, source), UQ(manual_session_id, source)
- Effective RPE = `manual` row if present else `garmin_fit` (`metrics.md` §4)

### 2.3 Calendar (0012) — D2, D10, E10

Model: **logical sessions with per-session revisions; a calendar version is the set of revisions written by one change.**

**`calendar_versions`**
- `number int unique not null` — monotonic, assigned under the `app_state` row lock
- `parent_number int null`
- `kind String(20)` — `bootstrap|manual_edit|proposal_accept|rollback|legacy_import`
- `actor String(10)` — `system|user|coach`
- `reason text null`
- `proposal_id uuid null fk coach_proposals.id` — set when `kind=proposal_accept` (FK added in 0015)
- `restored_from_number int null` — set when `kind=rollback`
- `block_version_id uuid null fk block_versions.id` — active block version at creation (FK added in 0013)
- `created_at timestamptz default now()`

**`calendar_session_revisions`**
- `session_uid uuid not null` — stable logical session ID
- `revision int not null` — 1 = original; UQ(session_uid, revision)
- `calendar_version_number int not null fk calendar_versions.number`
- `deleted bool default false`
- `local_date date not null`, `slot smallint not null default 0` — order within a day
- `kind String(12)` — `run|strength|cross|rest|mobility`
- `recipe_id String(10) null` — `REC001`–`REC010`; required when `kind=run` unless `custom=true` or `placeholder=true` or imported `legacy_unstructured=true` (E9)
- `custom bool default false`
- `locked bool default false` — protected from coaching/rollback mutation
- `legacy_unstructured bool default false` — import-only; structured validation exemption, never means assessed
- `legacy_payload jsonb null` — original source target, immutable
- `placeholder bool default false` — quality slot awaiting selection (bootstrap); `recipe_id` null, `custom` false
- `intent String(200)` — one-line purpose
- `certainty String(12)` — `committed|provisional`
- `planned_duration_s int null`, `planned_distance_m int null`
- `structure jsonb null` — ordered list; each item is either a step `{type:'warmup|work|recovery|cooldown', duration_type:'time|distance', duration_value, target:{modality:'speed|hr|effort', low, high, effort_cue}}` or a repeat block `{type:'repeat', count:int≥2, steps:[step, …]}` (one nesting level; steps inside execute in order `count` times, e.g. work+recovery interleaved)
- `strength_slot_id uuid null fk strength_routine_slots.id` — when `kind=strength`
- `notes text null`
- Index: (calendar_version_number), (local_date)

State at version V (SQL contract):
```sql
SELECT DISTINCT ON (session_uid) *
FROM calendar_session_revisions
WHERE calendar_version_number <= :V
ORDER BY session_uid, calendar_version_number DESC;
-- then drop rows where deleted = true
```
Head = `app_state.calendar_head_version` (0 means empty; version numbers start at 1). Original = revision 1. Current = state at head. Proposed = `coach_proposal_changes`. Completed = `session_completions`.

**`session_completions`**
- `session_uid uuid not null`
- `activity_id uuid null fk`, `strong_workout_id uuid null fk`, `manual_session_id uuid null fk` — at most one non-null; all null allowed only when `status in ('skipped','unknown')`
- `status String(24)` — `completed_as_planned|completed_modified|partial|moved|skipped|extra|unknown` (`metrics.md` §4)
- `match_method String(20)` — `explicit|auto_same_day|confirmed_move|user_marked|none`
- `modification_reason String(40) null` — `symptom_onset|fatigue|illness|schedule|weather|equipment|other`
- `reason_note text null`, `version int default 1`, `updated_at timestamptz`
- UQ(session_uid); UQ(activity_id); UQ(strong_workout_id); UQ(manual_session_id)
- `extra` rows use a synthetic `session_uid` with no revision.

### 2.4 Blocks, goals, events, strength routine (0013) — D12, D13, E15, E16

**`blocks`**: `block_uid uuid unique`, `created_at`.
**`block_versions`**
- `block_uid uuid fk blocks.block_uid`, `version int` — UQ(block_uid, version)
- `status String(16)` — `draft|active|consolidating|completed|replaced|ended`
- `objective text`, `rationale text`
- `maintained_qualities text[]`, `non_goals text[]`
- `eligible_recipe_ids String(10)[]`, `progression_dimension String(40)` — `duration|frequency|long_run|quality_volume|intensity|none`
- `constraints jsonb` — `[{kind, text}]`
- `start_date date`, `review_date date`
- `completion_indicators text[]`, `early_review_triggers text[]`
- `objective_status String(20)` — `unresolved|partially_achieved|achieved|not_achieved`
- `created_at`, `proposal_id uuid null`
- Active block = latest version of the block whose status ∈ {active, consolidating}; at most one (enforced in service).

**`block_decisions`** (append-only)
- `block_uid uuid null`, `decision String(12)` — `start|continue|extend|consolidate|transition|replace|end`
- `from_version int null`, `to_version int null`, `rationale text`, `evidence_ids text[]`, `policy_ids text[]`, `confidence String(10)`, `proposal_id uuid null`, `decided_at timestamptz`

**`goals`**: `text`, `horizon String(12)` (`3_6_months|season|long_term`), `priority smallint` (1 = highest), `status String(10)` (`active|paused|done|dropped`), `version int`.
**`events`**: `name`, `event_date date`, `distance_m int null`, `priority String(20)` (`target|supported_exposure|benchmark|optional`, E11), `status String(12)` (`planned|registered|completed|cancelled`), `result_s int null`, `version int`.
**`strength_routine_slots`** (D13): `label String(40)`, `default_weekday smallint` (0 = Mon), `lower_body_cost String(10)` (`low|moderate|high`), `typical_duration_s int null`, `main_lower_body_lifts text[]`, `active bool`, `version int`.

### 2.5 Anchors, metrics, prompts (0014)

**`intensity_anchors`** (`metrics.md` §3)
- `anchor_key String(40) unique` — e.g. `hr_threshold_lower-2026-12-03`
- `kind String(30)` — `hr_aerobic_upper|hr_threshold_lower|speed_aerobic_upper|speed_threshold_lower|performance_5k|performance_1mile|performance_3min|performance_20_30min`
- `value_low float`, `value_high float null`, `unit String(8)` — `bpm|mps|s|m`; CHECK `value_high IS NULL OR value_low <= value_high`
- `protocol String(24)`, `confidence String(12)`, `status String(12)`
- `calibrated_at timestamptz`, `valid_from date`, `review_after date`
- `source_activity_id uuid null`, `source_event_id uuid null`, `proposal_id uuid null`
- `conditions text null`, `notes text null`, `supersedes_key String(40) null`
- Unit/kind compatibility (CHECK): `hr_*`→`bpm`; `speed_*`→`mps`; `performance_5k`, `performance_1mile`→`s` (time for fixed distance); `performance_3min`→`m` (distance for fixed time); `performance_20_30min`→`mps` (average speed; exact duration in `conditions`). `unit` enum `bpm|mps|s|m`.

**`metric_configs`**: `metric_id String(60)`, `method_version String(40)`, `config jsonb`, `config_hash String(64)` — UQ(metric_id, method_version, config_hash). Not seeded by migration: TASK-011 provides `ensure_metric_config(session, metric_id, method_version, config) -> str` (get-or-create, returns `config_hash`), called by each metric module at recompute.

**`metric_results`**
- `metric_id`, `method_version`, `subject_type String(12)` (`activity|session|window|night|report`), `subject_key String(120)` (e.g. activity UUID, `w7:2026-11-11`)
- `window_start timestamptz null`, `window_end timestamptz null`, `window_label String(40) null`
- `status String(16)`, `quality_status String(14) null`, `value jsonb null`, `unit String(16) null`
- `reason_codes String(40)[]`, `quality_flags String(40)[]`, `source_refs jsonb`, `anchor_keys String(40)[]`
- `config_hash String(64)`, `anchor_set_hash String(64) null`, `calculated_at timestamptz`
- `dependency_hash String(64)`, `timezone String(100)`, `is_current bool default true` — source/config/anchor/plan identity (§6)
- UQ(metric_id, method_version, subject_key, config_hash, coalesce(anchor_set_hash,''), dependency_hash) → idempotent historical upsert; partial unique index (metric_id, method_version, subject_key) WHERE is_current. Invalidate old row then upsert/promote atomically.

**`prompts`**
- `kind String(20)` — `rpe|delayed_symptom|unmatched_session|missing_activity`
- `activity_id uuid null`, `session_uid uuid null`
- `opens_at timestamptz`, `closes_at timestamptz null`
- `status String(10)` — `open|answered|dismissed|expired`
- UQ(kind, activity_id, session_uid) — generator is idempotent

### 2.6 Coach (0015) — D1, D2, D8

**`coach_snapshots`**
- `operation String(32)` — `proceed_or_modify_today|review_rolling_plan|review_training_block|select_quality_session|recalibrate_intensity|handle_goal_or_race_change`
- `as_of date`, `generated_at timestamptz`
- `calendar_version_number int`, `block_version_id uuid null`, `data_revision int`
- `payload jsonb` — §4.1
- `source_fingerprint String(64)`, `source_versions jsonb`, `kb_digest String(64)` — checked at submit and acceptance (§6)
- `payload_sha256 String(64)`, `kb_package_version String(30)`, `kb_routes jsonb` — `[{path, sections[]|record_ids[]}]`
- `approx_tokens int` — `ceil(len(json)/4)` of payload + KB excerpts

**`coach_proposals`**
- `operation`, `snapshot_id uuid fk`, `base_calendar_version int`, `base_block_version_id uuid null`
- `status String(20)` — `pending|accepted|partially_accepted|rejected|stale|invalid`
- `submitted_at`, `decided_at null`
- `summary text`, `rationale text`, `confidence jsonb` — `{decision, evidence, data}` each `high|moderate|low`
- `evidence_ids text[]`, `policy_ids text[]`, `recipe_ids text[]`
- `follow_up text null`, `escalation String(32) null` — an operation key the coach recommends next
- `block_change jsonb null`, `anchor_changes jsonb null` — §4.2
- `payload jsonb` — full submitted document
- `decision_idempotency_key String(100) null unique`, `decision_hash String(64) null`, `decision_result jsonb null` — terminal retry contract (§6)
- `validation_errors jsonb null`, `skill_version String(20)`, `input_hash String(64)` — UQ(input_hash) for idempotent resubmit

**`coach_proposal_changes`**
- `proposal_id uuid fk`, `change_id String(12)` — `c1`, `c2`, …; UQ(proposal_id, change_id)
- `op String(10)` — `add|modify|move|delete`
- `session_uid uuid null` — null for `add`
- `before jsonb null`, `after jsonb null` — revision field sets
- `reason text`
- `decision String(10)` — `pending|accepted|rejected`

**`daily_guidance`** (E13: only when a check-in or explicit request exists)
- `local_date date`, `checkin_id uuid null fk`, `engine String(20)` — `local_rules.v2`
- `decision String(24)` — `proceed|modify|reschedule|rest|seek_clinical_input` (matches existing rules output)
- `session_uid uuid null`, `rationale text`, `missing_inputs String(40)[]`
- `coach_review_suggested bool`, `trigger_codes String(40)[]`
- `created_at timestamptz default now()`
- `input_hash String(64)` — UQ(local_date, input_hash)

## 3. HTTP API (all under `/api/v1`, existing envelope)

New routers: `api/calendar.py`, `api/checkins.py` (new `/v2/checkins`, leaves legacy routes intact), `api/metrics.py`, `api/planning.py`, `api/anchors.py`, `api/coach.py` (coexists with legacy coach routes until TASK-068). Each is registered in `main.py` before the SPA catch-all.

### 3.1 Calendar
| Method | Path | Body / params | Returns |
| --- | --- | --- | --- |
| GET | `/calendar` | `start` (date, default today−7), `end` (default today+13), `version` (default head) | `{version, head, today, timezone, start, end, last_planned_date, sessions:[SessionState], completions:[Completion]}` — `today` in profile timezone; `last_planned_date` = max `local_date` of non-deleted sessions at head or null (D19) |
| GET | `/calendar/versions` | `limit` ≤ 50 | `{items:[CalendarVersion]}` |
| GET | `/calendar/diff` | `from`, `to` | `{changes:[{session_uid, op, before, after}]}` |
| POST | `/calendar/bootstrap` | `{anchor_date, pattern:{quality:1,long:1}, start_date}` | new version; 409 `calendar_exists` if head ≠ 0 |
| POST | `/calendar/edits` | `{expected_head, edits:[{op, session_uid?, fields}], reason?}` | new version; 409 `calendar_head_moved` |
| POST | `/calendar/rollback` | `{expected_head, to_version, reason?}` | new version (`kind=rollback`) |
| PUT | `/calendar/completions/{session_uid}` | `{expected_version?, activity_id?, strong_workout_id?, manual_session_id?, status?, modification_reason?, reason_note?}`; when a subject is linked, `status` is omitted and computed by `planned_actual_session` and written back; without a subject, `status` ∈ {`skipped`, `unknown`} is required | Completion |

`SessionState` = revision fields + `session_uid`, `revision`, `is_original`, `changed_by_version`.

Example `POST /calendar/edits`:
```json
{"expected_head": 7, "reason": "work trip",
 "edits": [{"op": "move", "session_uid": "5b1e…", "fields": {"local_date": "2026-11-14"}}]}
```
→ `201 {"data": {"version": 8, "kind": "manual_edit", "stale_proposals": ["9c2d…"]}}`

### 3.2 Check-ins, RPE, prompts
| Method | Path | Notes |
| --- | --- | --- |
| POST | `/v2/checkins` | body: `kind, observed_at, fatigue?, illness?, gait_change?, context_tags[], symptoms:[{site, side, severity, timing}], activity_id?, prompt_id?, note?, idempotency_key`; 201 create / 200 replay; response includes `daily_guidance` when `kind=exception` |
| PATCH | `/v2/checkins/{id}` | versioned |
| GET | `/v2/checkins` | `start`, `end` |
| PUT | `/activities/{id}/rpe` | `{rpe}` → manual `session_rpe` |
| PUT | `/strength/history/{workout_id}/rpe` | `{rpe}` |
| GET | `/prompts` | prompts with `status='open'` and `opens_at <= now()` (not-yet-open prompts are hidden), newest first |
| POST | `/prompts/{id}/dismiss` | |

### 3.3 Metrics and activity detail
| Method | Path | Returns |
| --- | --- | --- |
| GET | `/metrics/windows` | `as_of` → 7/14/28/56-day results for volume, sRPE, intensity, long-run, spacing |
| GET | `/metrics/recovery` | `start`, `end` → per-night signals, baseline state, flags, discordance |
| GET | `/activities/{id}/execution` | laps, steps, per-rep results, planned-vs-actual, RPE, linked symptoms |
| GET | `/metrics/explain/{result_id}` | method, config, inputs, source refs, exclusions |

### 3.4 Blocks, goals, events, anchors, strength routine
CRUD-style, versioned: `GET/POST/PATCH /goals`, `GET/POST/PATCH /events`, `GET/POST /anchors` (POST creates a new anchor and supersedes per `supersedes_key`), `GET/PUT /strength-routine` (full replace with `expected_version`), `GET /blocks/active`, `GET /blocks/{block_uid}/history`. Blocks are created/changed only by accepting a proposal.

### 3.5 Coach (UI side)
| Method | Path | Notes |
| --- | --- | --- |
| GET | `/coach/proposals` | `status` filter |
| GET | `/coach/proposals/{id}` | proposal + changes + diff against current head |
| POST | `/coach/proposals/{id}/decision` | `{idempotency_key, expected_head, accept_change_ids:[...], reject_change_ids:[...], accept_block_change:bool, accept_anchor_changes:[keys]}` → new calendar version; 409 `proposal_stale` if head ≠ `base_calendar_version` |
| GET | `/coach/v2/daily` | today's latest `daily_guidance` or `null` — implemented in P0-A by TASK-013 (`api/checkins.py`), not by TASK-063 |

New snapshot generation and proposal submission are CLI-only (§5). Existing agent endpoints remain until TASK-068, then become read/schema adapters or explicit non-writing upgrade errors; no auto-activation path survives the authority switch.

## 4. Coach documents

### 4.1 Snapshot payload (`coach_snapshots.payload`)

Adopts Workstream B `athlete_state_snapshot.schema.json` v1 field names with these P0 projections. Sections absent from the projection are omitted, not null.

`select_quality_session` uses the Rolling projection.

| Section | Daily | Rolling | Block | Calibration | Race change |
| --- | --- | --- | --- | --- | --- |
| `snapshot_meta` (ids, as_of, versions, timezone) | ✓ | ✓ | ✓ | ✓ | ✓ |
| `goals_and_constraints` (goals, strength routine, run cycle anchor, events) | constraints only | ✓ | ✓ | – | ✓ |
| `calendar` (state at head, ±window) | today−3..today+3 | today−14..today+13 | today−28..today+13 | – | today..today+13 |
| `block` (active version summary or null) | id + objective | ✓ | ✓ + history | objective | ✓ |
| `completed_exposures` (runs/lifts with class, timer_s, distance, RPE, completion status) | last 72 h | 14 d | 28 d | relevant only | 14 d |
| `load_shape` (metric results 7/14/28[/56/84]) | 7 d | 7/14/28 | 7/14/28/56/84 | – | 7/14/28 |
| `execution` (work_interval_execution per quality session) | last quality | 14 d | 28 d | candidate sessions | – |
| `symptoms` (timelines + delayed responses) | 14 d | 28 d | block | – | 28 d |
| `recovery` (multisignal per night + baseline) | last 3 nights | 14 d | block summary | – | – |
| `anchors` (active + history) | targets for today | active | active + history | full history | active |
| `prior_decisions` (proposals, accepted changes, outcomes) | last 3 | last 2 weekly | block decisions | anchor history | – |
| `data_quality` (freshness per dataset, missing/stale flags) | ✓ | ✓ | ✓ | ✓ | ✓ |
| `drill_down_queries` (names of available `coach query` commands) | ✓ | ✓ | ✓ | ✓ | ✓ |

### 4.2 Proposal document (submitted by the skill)

```json
{
  "schema_version": "coach_proposal.v1",
  "operation": "review_rolling_plan",
  "snapshot_id": "uuid",
  "base_calendar_version": 7,
  "base_block_version_id": "uuid|null",
  "summary": "Repeat last week's structure; extend long run 10 min.",
  "rationale": "…",
  "confidence": {"decision": "moderate", "evidence": "moderate", "data": "high"},
  "changes": [
    {"change_id": "c1", "op": "modify", "session_uid": "uuid",
     "after": {"planned_duration_s": 4800, "intent": "Long aerobic run, conversational"},
     "reason": "No delayed symptoms after last two long runs."},
    {"change_id": "c2", "op": "add",
     "after": {"local_date": "2026-11-21", "kind": "run", "recipe_id": "REC001", "intent": "Easy",
               "planned_duration_s": 2400},
     "reason": "Fills cycle opportunity."}
  ],
  "preserved": ["uuid", "uuid"],
  "block_change": null,
  "anchor_changes": [],
  "evidence_ids": ["E-…"], "policy_ids": ["P019"], "recipe_ids": ["REC001", "REC002"],
  "observations_used": ["metric_result uuid", "checkin uuid"],
  "follow_up": "Delayed symptom check after Sunday long run.",
  "escalation": null,
  "skill_version": "running-coach.v1"
}
```
`block_change` (block operations): `{decision, block_uid|null, version_fields:{…block_versions columns…}}`.
`anchor_changes` (calibration): `[{kind, value_low, value_high, unit, protocol, confidence, calibrated_at, source_activity_id, conditions, supersedes_key}]`.
Validation rules → `coaching_contract.md` §4.

## 5. CLI (`uv run python -m app.cli <cmd>` from `backend/`; real mode via `scripts/with-mode real`)

| Command | Args | Output / effect |
| --- | --- | --- |
| `fit-inventory` | `--limit 20` | downloads FIT for the N most recent runs into raw store; prints redacted JSON: FIT message/field inventory **and** key paths + value types (no values) of Personal API responses for activity detail, activity workouts, sleep summaries, HRV summaries, daily heart rate for the same dates (G2) |
| `fit-backfill` | `--since YYYY-MM-DD` | fetch + decode FIT for runs with `fit_status in (not_fetched, decode_error)` |
| `metrics-recompute` | `--metric <id>|all` `--since` | recompute metric results idempotently |
| `coach snapshot` | `--operation <op>` `--as-of YYYY-MM-DD` | prints `{snapshot_id, payload, kb:{package_version, excerpts:[{path, section|record_id, text}]}, approx_tokens}`; persists `coach_snapshots` |
| `coach query` | `<name> [--activity-id] [--start --end] [--from --to] [--result-id]` (`--result-id` for `explain_metric`) | names: `activity_execution`, `long_run_history`, `recovery_nights`, `calendar_diff`, `explain_metric` |
| `coach submit` | `--file proposal.json` | validates; prints `{proposal_id, status, errors[]}`; exit 0 = pending, 2 = invalid, 3 = stale |
| `strong-import` | `<csv> [--apply]` | wraps existing `app.services.strong_import` |

Exit codes for all commands: 0 success, 1 unexpected error, 2 validation error, 3 conflict/stale, 4 data unavailable (e.g., KB integrity failure).

## 6. Shared interfaces and wire authority (remaining-MVP freeze)

This section supersedes old handoff assumptions and duplicated DTO blocks. All names below are required. Existing public APIs stay until TASK-068; no staging namespace is invented. All new calendar, checkin, routine, anchor, goal/event and coach writes are disabled with 409 `planning_not_active` while authority is `legacy`; isolated tests may seed authority `calendar`. New `/v2/checkins` and `/coach/v2/daily` names are permanent and do not collide with old routes. New writes become available together at cutover. Framework envelope/error conventions remain §0.

### 6.1 Calendar/check-in/routine DTOs

- `CalendarView={today,timezone,start,end,version:int,head:int,last_planned_date:date|null,sessions:SessionState[],completions:Completion[]}`. Empty head/version=0; no row for version 0. Requested nonexistent version→404 `calendar_version_not_found`; start>end→422 `invalid_date_window`. `last_planned_date` is global head maximum, independent of selected display range/version.
- `SessionFields` write fields: local_date, slot (integer ≥0, default0), kind (`run|strength|cross|rest|mobility`), recipe_id nullable, custom=false, placeholder=false, intent, planned_duration_s nullable positive integer, planned_distance_m nullable positive integer, structure nullable, strength_slot_id nullable, notes nullable, locked=false. `extra=forbid`: certainty and import-only fields rejected. `SessionState` adds id (revision row UUID), session_uid, revision, calendar_version_number, deleted, certainty, is_original, changed_by_version, legacy_unstructured, legacy_payload. Certainty derives from profile-local today; dates ≤today+6 committed (including history), later provisional. Date eligibility remains operation validation, not certainty.
- Ordinary `PlannedStep={type:'warmup'|'work'|'recovery'|'cooldown',duration_type:'time'|'distance',duration_value:finite positive number,target:StepTarget|null}`. `StepTarget={modality:'speed'|'hr'|'effort',low:number|null,high:number|null,effort_cue:string|null}`; numeric modalities require finite ordered bounds ≥0, HR bounds >0; effort requires nonblank cue and null numeric bounds. Null target means no numeric target, not zero. `RepeatBlock={type:'repeat',count:int>=2,steps:PlannedStep[]}` (nonempty, no nested blocks). `structure=(PlannedStep|RepeatBlock)[]`, nonempty if supplied. No stored `step`/`repeat` on plain steps. Max100 expanded steps; reject overflow `invalid_structure`.
- TASK-012 owns pure `services/calendar_structure.py::expand_structure(structure:list[dict])->list[dict]`: validate above; each result copies an ordinary step and adds `step_path` (`'0'` or `'1.steps.0'`), `expanded_step` (1-based sequence), `repeat_index` (zero-based iteration or null). Iterate block repetitions outside block steps: work,recovery,work,recovery. Frontend `flattenStructure` uses identical ordering.
- `Completion` = §2.3 fields plus `local_date`: subject's canonical local date; if no subject, planned local date; null only for unknown synthetic extra. Linked PUT forbids status; unlinked PUT requires skipped|unknown. Existing completion requires expected_version; new requires absent/0. Conflicts409 `version_conflict`, subject reused409 `subject_already_linked`. For confirmed_move the overall status remains moved while planned_actual recomputes measurement components for every linked row. Explicit and confirmed_move associations never become auto matches. Preserve reasons on recompute.
- `CheckinV2` = §2.2 columns + `symptoms:SymptomReport[]`, `daily_guidance:DailyGuidance|null`; `SymptomReport` = id plus input fields. PATCH requires expected_version and captures full prior payload/symptoms. Replay same idempotency key+canonical body returns original201-body at200; different body409 `idempotency_conflict`. Post-run/delayed require activity_id; exception permits null. Explicit prompt must match activity and kind, be open or expired, and be answered atomically (dismissed is rejected); reject unrelated prompt422 `prompt_subject_mismatch`. Symptom arrays replace wholesale on PATCH. Unknown measurements stay null.
- `DailyGuidance` = all §2.6 fields including id, created_at (UTC), input_hash. Decision enum remains `proceed|modify|reschedule|rest|seek_clinical_input`. GET `/coach/v2/daily` selects today's latest by created_at,id and returns object|null; it never creates rows. Explicit POST `/coach/v2/daily/request` with `{}` computes/persists today guidance. No check-in/request means no persisted downgrade.
- `RpeResult={activity_id:uuid|null,strong_workout_id:uuid|null,manual_session_id:uuid|null,rpe:number,source:'manual',collected_at:instant,collection_delay_s:int|null}`. Exactly one subject. PUT manual RPE upserts manual source, never deletes Garmin source. Local-date filters use profile timezone and inclusive date bounds. GET collections (versions, checkins, prompts, anchors, goals, events, coach proposals, block history) return `{items:[...]}`.
- `StrengthRoutine={version:int,slots:StrengthRoutineSlot[],suggested:boolean,schedule:ConfirmedSchedule}`. Slot includes id and §2.4 fields. `ConfirmedSchedule` contains current profile fields `strength_days_confirmed,strength_schedule_mode,scheduled_strength_days,strength_week_a_start,strength_week_a_days,strength_week_b_days,mobility_week_a_days,mobility_week_b_days,mobility_optional_days`; mode `weekly|alternating`. Profile remains the sole recurrence authority. Routine PUT `{expected_version,slots:[slot fields excluding id/version]}` changes lift templates only; cannot reset or infer schedule. Preserve existing profile schedule editor/API. In bootstrap/import reuse `domain.cycle.recurring_sessions`; map mobility to distinct kind mobility, optional flag preserved in legacy_payload for imported rows. No automatic recurrence beyond last planned date. Suggested slots are advisory when no routine; never overwrite confirmed alternating days.
- Metric result/value DTOs are `metrics.md` contracts; metric API outer wrappers remain `{as_of,windows,spacing,symptoms}` (each window also carries srpe_strength), `{start,end,nights}`, and ActivityExecution from TASK-030. Missing result null differs from known metric zero. No frontend may invent a value absent from these contracts.

### 6.2 FIT decoder contract (TASK-004 produces; TASK-010 consumes)

Frozen dataclasses in `app/adapters/garmin/fit.py`, no ORM or IO. Every optional field explicitly defaults None. All decoded instants timezone-aware UTC; all offsets measured from session.start_at. Tuples below immutable and sorted; dicts only redacted metadata (no raw SDK messages).

```python
DecodedSession(start_at: datetime, sport: str, elapsed_s: float|None,
 timer_s: float|None, distance_m: float|None, workout_rpe: float|None,
 workout_feel: int|None)
DecodedLap(lap_index: int, start_at: datetime, timer_s: float|None,
 elapsed_s: float|None, distance_m: float|None, avg_speed_mps: float|None,
 avg_hr_bpm: float|None, max_hr_bpm: float|None,
 lap_trigger: str|None, wkt_step_index: int|None)
DecodedStep(message_index: int, step_name: str|None, intensity: str|None,
 duration_type: str, duration_value: float|None, target_type: str|None,
 target_low: float|None, target_high: float|None,
 repeat_from: int|None, repeat_count: int|None)
DecodedStream(t_s: tuple[int,...], hr_bpm: tuple[int|None,...],
 speed_mps: tuple[float|None,...], distance_m: tuple[float|None,...],
 altitude_m: tuple[float|None,...], cadence: tuple[float|None,...],
 timer_on: tuple[tuple[int,int],...], sample_count: int, max_gap_s: int,
 quality_flags: tuple[str,...])
DecodedFit(fit_sha256: str, profile_version: str, sdk_version: str,
 session: DecodedSession, laps: tuple[DecodedLap,...],
 steps: tuple[DecodedStep,...], stream: DecodedStream,
 message_inventory: dict[str,int], device: dict, field_names: dict[str,tuple[str,...]])
extract_fit(zip_bytes: bytes) -> bytes
decode_fit(fit_bytes: bytes) -> DecodedFit
decode_fit_zip(zip_bytes: bytes) -> DecodedFit
```

`FitDecodeError(code:str)` exposes `.code`. Codes: bad_zip, zip_member_count, zip_member_too_large, invalid_fit, invalid_crc, decode_failed, missing_session, ambiguous_session, missing_start, invalid_stream_time. ZIP exactly one case-insensitive .fit member, extracted limit50MiB checked both declared and streamed length; no disk extraction. FIT must contain one session; unsupported sport decodes but ingestion skips non-run. SDK21.221.0, fresh Decoder for signature, integrity and read; `convert_datetimes_to_dates=False,expand_sub_fields=False,convert_types_to_strings=True`, apply scaling/components enabled. SDK-scaled record/session/lap fields used once. Raw main workout duration/targets scaled explicitly: time/1000, distance/100, speed/1000, HR>100→raw−100 else None; repeat duration value is start step index; repeat_steps count from raw target value. workout_rpe raw/10, only0..10 accepted; workout_feel0..100 else None. FIT epoch offset631065600; profile version unsigned little-endian header bytes2:4, rendered decimal string. RUN_SPORTS frozenset(running,trail_running,treadmill_running).

Records sorted by timestamp. Duplicate timestamp identical values collapse; conflicting channel values become None for that channel and DUPLICATE_RECORD_CONFLICT. Reject fractional/negative offsets, never silently round. Nonfinite channel values→None; missing enhanced speed falls back to speed, enhanced altitude→altitude. Missing HR/speed stays null. Event timer start→stop/stop_all half-open segments; merge overlaps/adjacency. An unmatched start may close at explicit session end (start+elapsed); flag TIMER_END_INFERRED. Missing/contradictory timer events→empty timer_on, TIMER_EVENTS_MISSING or TIMER_EVENTS_AMBIGUOUS; never claim uninterrupted recording from absent events. Timer sum versus session timer difference >max(1s,1% of canonical session timer) adds TIMER_MISMATCH; reconstructed timer-trace outputs become not_assessable. Valid summary timer remains available to volume/completion (E33 planner reconciliation). Preserve flags in activity_streams `quality_flags text[] default '{}'`. `max_gap_s=0` for <2 records. G2 runtime evidence remains pending; synthetic shape is frozen, not an FR265 observation.

### 6.3 Metric foundation (TASK-011)

`metrics/contract.py`: StrEnum Status (six values §2.5), QualityStatus(good,limited,insufficient); frozen `MetricResultData` (alias `MetricResult`) fields exactly §2.5 except ORM id/is_current; array fields tuple; source_refs dict; dependency_hash/timezone default empty pending engine fill; calculated_at optional default None. `config_hash(config:Mapping)->str` SHA256 sorted compact canonical JSON, allow_nan=False. `coverage_label(valid_s,eligible_s)->QualityStatus|None`: None if eligible<=0, otherwise thresholds .90/.70 without rounding; invalid negative/nonfinite values raise ValueError. `rolling_window(today,n)->(date,date)` inclusive n days `(today-(n-1),today)`.

`integrate_timer_on(t_s:list[int],timer_on:list[tuple[float,float]],max_gap_s:int)->list[tuple[int|None,float,bool]]`: ordered half-open union; intervals with no leading observation or after final sample use index None/known False, including wholly missing trace. Interior index i identifies [t_i,t_i+1), known only 0<dt<=max_gap. Every eligible timer second appears exactly once. t_s must strictly increase; invalid→ValueError('invalid_stream_order'); malformed timer interval or max_gap<=0→ValueError('invalid_timer'). Caller decides channel value validity. `plausible_hr(v)` finite30..230; `plausible_speed(v)` finite0..10. Detailed arithmetic/missing rules → metrics §2.

`RunFact(activity_id,start_at,end_at,local_date,sport,timer_s,distance_m,workout_label,source_refs:dict={},source_revision:str='')` frozen dataclass (dict default_factory). `load_runs(session,start_date,end_date_excl)->list[RunFact]`: resolved/nonexcluded three run sports, sorted start_at/id, half-open local range. `activities_coverage_complete(session,start_date,end_date_excl)->bool`: complete activities coverage for every local date. `latest_results(session,metric_id,method_version,subject_keys)->dict[str,MetricResultRow]` only is_current rows, no timestamp fallback. `ensure_metric_config(session,metric_id,method_version,config)->str` race-safe get-or-create hash; no migration seeds.

`metrics/anchors.py`: `ActiveAnchor(anchor_key,kind,value_low,confidence,review_after,valid_from,content_hash)`; `active_anchors(session,on_date)->dict[str,ActiveAnchor]`; `anchor_set_hash(Iterable[ActiveAnchor])->str|None`. Immutable content hash includes all numerical/protocol/evidence/calibration fields (excludes mutable status). Choose greatest valid_from≤date in explicit same-kind supersedes chain, then calibrated_at, then anchor_key; same-date correction requires supersedes_key pointing at current successor. Superseded rows remain valid for earlier dates. `status='expired'` does not erase past applicability; rejected/invalid rows excluded. valid_from earlier than predecessor forbidden422 `anchor_backdate_conflict`. PATCH numerical anchor contents forbidden; correction inserts successor. Zone pair invalid ordering returns missing/invalid reason; no physiology conversion.

`metrics/engine.py`: `register(metric_id,method_version,depends_on:tuple[str,...])` decorates `compute(session,subject_key)->list[MetricResultData]`; `REGISTRY:dict[str,RegisteredMetric]`; `parse_scope(scope:str)` validates TASK-030 grammar activity:<uuid>, strength:strong:<uuid>, strength:manual:<uuid>, checkin:<uuid>, calendar, anchors:<ISOdate>, recovery_dates:<ISOdate>[,<ISOdate>...], timezone, all:<ISOdate>; `recompute(session,scope)->list[MetricResultData]`; `upsert_results(session,results)->None`. Foundation METRIC_MODULES=(); TASK-030 installs modules and transactional invalidation. No engine commit. dependency_hash canonicalizes immutable source revisions/raw hashes, explicit selected plan version and stable completion association/manual-input hash (subject,match_method,reasons,user-input revision; excludes derived status/version to avoid self-cycles), effective anchor hashes, config hash, timezone and dependent result hashes. Source refs must carry these facts; absent required provenance→invalid result, not invented identity. Invalidate old current signature then upsert/promote new in one transaction; preserve previous rows for explanations. Source/device recovery partition travels in source_refs. Recompute/order/invalidation specifics owned by TASK-030, not ORM global hooks invented here.

### 6.4 Coach freshness and atomic decisions

TASK-061 snapshot records source_versions and source_fingerprint from one pure canonical serializer over selected canonical activity revisions+exclusion/link state, checkin IDs/versions, recovery IDs/provenance/values, profile version/timezone/recurrence, routine version, goal/event versions, effective anchor content, calendar/block heads, imported history epoch, KB digest+selected records. Sort by stable IDs, preserve arrays when order meaningful, SHA256 sorted compact JSON, prohibit NaN. Include missing markers and source coverage. Exclude generated_at, calculated_at, data_revision-only noise and proposal insertion itself. TASK-061 proposal submit/decision services (called by062 snapshot/063 API) recompute the same fingerprint under advisory lock71382413 at submit AND acceptance; mismatch409 `stale_evidence`, no activation. TTL/head checks are additional. Re-run current safety and subset invariants before writing.

`decision` requires `idempotency_key`8..100 plus §3.5 selections. Canonical sorted selection hash stored with terminal result atomically. Same key+same selection returns exact recorded result/version, even if head later moved. Different key attempting same terminal selection also returns existing result; any changed selection after terminal decision→409 `decision_conflict`; reuse key for another proposal→409 `idempotency_conflict`. Check terminal replay before freshness. Fresh decision validates partition of all change IDs (accepted/rejected disjoint union), block/anchor selections and resulting whole-state constraints. Reject-all and semantic no-op produce no calendar version; audit decision still persists. Commit calendar/block/anchor/decision atomically; any exception rolls all back. No hidden automatic activation route after TASK-068.

## 7. Populated-data import and authority handoff (TASK-068)

`app_state.planning_authority String(12) default 'legacy' CHECK legacy|calendar`. `legacy_import_runs`: id UUID, key String unique (`remaining_mvp_v1`), source_fingerprint String64, imported_at UTC, report JSONB, undo_payload JSONB nullable. `legacy_import_map`: id UUID, import_id FK, source_table String60, source_id UUID, target_kind String40, target_id UUID nullable, payload JSONB, payload_sha256 String64; UQ(source_table,source_id,target_kind). These are immutable provenance, included in backups. Physical legacy tables remain retained. `calendar_session_revisions` adds import-only source payload/marker/locked fields (§2.3). Calendar source mappings permit a read-only archive with no invented past calendar versions.

`services/legacy_cutover.py::migrate_legacy_state(session,*,dry_run:bool)->MigrationReport` owns no commit. Report `{key,already_imported,source_fingerprint,counts:dict,calendar_head,undo_available,errors:[]}`. Under advisory71382413 then app_state FOR UPDATE, capture active `plan_data` membership (latest applicable CoachPlanRevision.payload.active_session_ids, including rows belonging to older plans). Historical source payloads and revisions map individually. Resolve effective active plan using existing `_active` semantics; do not pick by plan_id alone or flatten old history into fake new coaching decisions. Source hash/row counts and mapping counts are checked before authority switch. Existing calendar nonempty without matching import marker→409 `cutover_target_not_empty`. Validation error rolls back all writes; dry-run uses a savepoint and rolls it back.

Current member UUIDs become stable session_uid. Include linked historical source sessions as historical calendar revisions when outside current membership, preserving source IDs and completed facts; archive withdrawn/future obsolete sessions without reactivating them. For same-date kinds preserve deterministic slot by sorted source UUID. Explicit minutes*60 and km*1000 accepted only if finite integral SI values, otherwise keep duration/distance null plus original payload. Map known kinds run,strength,mobility,cross,rest directly; other kinds produce `unsupported_legacy_kind` in report and abort cutover without changing raw source rows; no guessed mapping. Prose runs legacy_unstructured=true, recipe=null/custom=false; original intent/purpose and full target stay visible. No recipe or numeric intensity is inferred. Completion subject link preserved, status unknown pending metric evaluation; same-day ambiguity never drops old explicit link.

Old checkins/revisions remain archive schema_version1 with unchanged payload, IDs and timestamps, not forced into v2 numeric fields. GET `/history/checkins` merges tagged v1 and v2 records sorted observed_at/id; v1 edit UI becomes read-only archive after cutover. Existing `/checkins` GET and agent revisions GET remain faithful compatibility readers. All legacy write routes (checkins, plans, old completion links, local coach decisions, auto-submit) reject409 `legacy_write_disabled` after authority switch unless explicitly routed through approved new transaction service. Profile/activity/Strong/manual/import writes continue normally and trigger new invalidation.

Capture `agent_plans.revertible()` latest eligible changed revision and its before/after snapshots before cutover. `undo_payload` stores original revision ID, current fingerprint and immutable mapping. `GET /history/agent-undo` returns availability, original revision, protected session IDs and preview diff. `POST /history/agent-undo` body `{idempotency_key,expected_head,revision_id,reason}` delegates to new calendar transaction, rechecks same protections as old rollback (historical/completed/locked, current latest eligible source), creates a NEW rollback version for permitted inverse edits, marks pending proposals stale, preserves completed facts and stores replay result in legacy_undo_requests (§7.3). Subsequent user calendar change invalidates this one legacy undo with409 `legacy_undo_stale`; new normal calendar undo remains. No-change reviews do not hide eligible undo. Latest old undo thus remains usable immediately after import, never writes legacy tables.

The authority flag switches only after import validation and after new UI/helper is deployed. After switch legacy mutation guards and new routes agree in the same transaction. Recurring profile strength/mobility remains unchanged and renders through templates; no hidden new plan generation. Failure leaves complete old app operational. Export/restore and populated 0009 synthetic fixture tests are required before shipping; actual athlete database execution is release work, never planning.

### 7.1 Exact service entrypoints for integration consumers

All below use caller-owned transaction; none commits. Calendar writers acquire advisory71382413 then app_state lock (reentrant within transaction).

- `calendar.state_at(session, version:int)->list[dict]`; `calendar.calendar_view(session,start:date,end:date,version:int|None=None)->dict`; `calendar.calendar_diff(session,from_version:int,to_version:int)->dict` returns `{changes}`.
- `calendar.apply_edits(session,expected_head:int,edits:list[dict],reason:str|None,*,kind:str='manual_edit',actor:str='user',proposal_id:UUID|None=None,block_version_id:UUID|None=None)->dict` returns CalendarWriteResult. Protected rows remain protected for every actor; proposal subset validation precedes this call. Caller avoids semantic no-op (service422 edit_no_change).
- `calendar.write_bootstrap(session,anchor_date:date,start_date:date)->dict`; `calendar.bootstrap_plan(anchor_date:date,start_date:date,today:date,run_history:list[dict],strength_occurrences:list[dict])->list[dict]` pure. `calendar.seed_demo_calendar(session,*,anchor_date:date,start_date:date,now:datetime,history_edits:list[dict])->dict` is fixture-only, checks settings mode demo/test, rejects real with403 demo_seed_forbidden, requires empty head and creates version1 same deterministic current bootstrap with supplied now, then version2 containing supplied historical add/edit fixtures; history_edits permit pastdates only in this explicit helper (not normal apply_edits). No live route exposes it. Does not bypass authority or overwrite imported state.
- `calendar.rollback_calendar(session,expected_head:int,to_version:int,reason:str|None)->dict`; `calendar.put_completion(session,session_uid:UUID,body:dict,*,assess:Callable[[Session,UUID],None])->SessionCompletion`.
- `metrics.anchors.create_anchor(session,fields:dict)->dict`: canonical anchor create/supersede validation and serializer; POST handler delegates. `metrics.anchors.active_anchors` and hash signatures §6.3 unchanged.
- CalendarView adds `undo:{target_version:int,eligible:bool,protected_session_uids:uuid[]}|null`: compare head state against parent of latest version with actual revision changes, skip no-change audit decisions. Null at empty or imported baseline; imported legacy undo uses `/history/agent-undo` separately. eligible means at least one inverse future/uncompleted/unlocked change remains. CalendarWriteResult adds `preserved_session_uids:uuid[]` default[], used by rollback.

### 7.2 Additional integration guarantees

TASK-003 extends GET `/profile` data with read-only `planning_authority:'legacy'|'calendar'`, sourced from AppState/defaultlegacy, including no-profile response. It is not a profile field or envelope property. Profile PUT ignores this supplied field, preserving existing GET/spread/PUT clients; it never changes AppState authority. New clients omit it. A request with opposite authority still performs permitted profile edits without changing authority. TASK-039 extends existing Profile DTO, TASK-050 selects navigation from this response before068 exists. TASK-003 may edit core.py profile serialization/validation only; no unrelated route removal.

TASK-011 contract.py additionally exports `completion_association_hash(completion)->str`: SHA256 canonical subject UUIDs, session_uid, match_method, modification_reason/reason_note and user-input revision; excludes derived status/version/updated_at. Add SessionCompletion `input_version int default1` incremented only on user association/reason changes, never assessment. `metric_source_refs(session,activity_id:UUID,session_uid:UUID|None=None,calendar_version:int|None=None)->dict` returns `{activity:{id,source_revision,source_refs},fit:{id,fit_sha256,zip_sha256,raw_object_id,sdk_version,profile_version,quality_flags}|null,plan:{session_uid,revision_id,calendar_version,structure_hash}|null,completion_association_hash:str|null}`. Plan selects requested version or current; source joins use RunFact identity and fit row; no derived-status cycle.

`coach_decision_keys` (migration0015, model CoachDecisionKey): `idempotency_key String100 PK`, `proposal_id UUID FK coach_proposals`, `decision_hash String64`, `result JSONB`, `created_at timestamptz default now()`. Global key namespace; every successful terminal replay under a new key inserts an alias to same immutable decision/result in same transaction. Reuse any key for another proposal/different selection409. Proposal decision fields remain primary terminal result; alias table prevents a replay-only key from being reused elsewhere. All write mutations coordinate advisory71382413, no commit in services.

TASK-030 owns one coalesced source data_revision bump and derived recompute per outer transaction for NEW v2 services, including calendar/block/anchor/checkin/routine/goal/event writes. Replay/derived-only/GET do not bump. Normal new services mutate ORM source rows observed by030 listeners (no pre030 listener import needed); bulk writes explicitly use metrics.engine.enqueue_scopes(session,scopes). Never call bump_data_revision independently; preserve existing legacy bump behavior beforecutover. Source_scope collector must capture old/new beforeflush. Read-only decision collector is TASK-061 `services/decision_inputs.py::collect_decision_inputs(session,operation:str,as_of:date,*,now:datetime,kb:VerifiedKnowledge)->dict` containing source_versions,source_fingerprint,safety_guard; `decision_input_fingerprint` same args→str. It imports neither snapshot nor proposal module. Resolver/VerifiedKnowledge details pinned TASK-061, no circular ownership.

Global write lock order: every new mutation service (calendar, completion, checkin/RPE/prompt, anchors, routine, goals/events, proposal decisions and cutover) acquires PostgreSQL transaction advisory lock71382413 BEFORE any app_state FOR UPDATE and before source mutation. Never take app_state first and defer advisory to030 commit hook. TASK-030 owns db.bump_data_revision coordination: in calendar authority acquire same advisory before app_state, coalesce one source bump; in legacy preserve established semantics. Existing source helpers calling bump use that coordinated entrypoint.

### 7.3 Readiness clarification — calendar/legacy handoff

This section resolves readiness_data.md findings; it overrides earlier shorthand about response timing and replay.

**Completion transaction.** `calendar.put_completion(session,session_uid:UUID,body:dict,*,assess:Callable[[Session,UUID],None])->SessionCompletion` mutates/flushes association, invokes required `assess(session,session_uid)`, flushes derived fields, and returns ORM row (not a precommit DTO). Missing assessor is configuration error, never an unknown-success response. TASK-030 exports `metrics.engine.assess_completion(session,session_uid:UUID)->None`: recompute the linked planned_actual subject through registered025 compute/writeback, including confirmed_move semantics, no commit; source/dependency invariants unchanged. TASK-012 router uses FastAPI dependency `get_completion_assessor()` returning this callable; in TASK-012 bare-app tests override with deterministic fixture assessor, and production router stays unregistered until030. TASK-030 mounts router and supplies real dependency. Route calls service, commits caller transaction (existing get_session does not commit), refreshes row, then `calendar.completion_data(session,row)->dict` builds §6.1 Completion and envelope at committed data_revision. Commit failure returns no success body. Before_commit may repeat deterministic assessment but cannot append duplicate dependency rows. Test fake assessor writes completed_modified; HTTP result must equal stored postcommit status/version. Real030 tests compare all linked methods and injected commit failure.

**Rollback protection.** Compute candidate UID union over latest revisions (including tombstones) at current and target versions. A UID is protected if EITHER revision has local_date<athlete_today or locked=true, OR any completion association exists for UID with a subject, OR current completion is skipped (explicit historical user decision). A protected UID retains exactly its current state, including current tombstone/absence; target-only protected rows are skipped, never resurrected. List protected UIDs in preserved_session_uids. Target-only future unlocked/uncompleted rows may be restored. Undo eligibility uses this same predicate, not a weaker current-only test. If no permitted diff remains return rollback_no_change; a mixture applies permitted diff and preserves protected rows. New test: target contains yesterday's session deleted at current head plus a future changed session; rollback leaves yesterday absent and restores only future one. Both protected-only→422 and mixed→newversion cases required.

**Demo history edits.** `history_edits` is a list of `{op:'add',session_uid:UUID,fields:SessionFields}` only; explicit nonzero UUID required, unique across list/current state; reject modify/move/delete, duplicate/existing UID, invalid fields. This seeder copies supplied UID to logical session_uid and generates new revision-row UUIDs; ordinal order is supplied list order. Version1=current bootstrap, version2=manual_edit(actor system, reason synthetic history fixture) only when history_edits nonempty; empty list returns version1, no empty version2. Returns CalendarWriteResult for final version. Example fixed clock2026-11-16T17:00Z, anchor2026-11-02,start2026-11-16, add UUID00000000-0000-4000-8000-000000000042 on2026-11-14 with kindrun/recipeREC003/customfalse/placeholderfalse/intentIntervals/structure[work(time60,targetnull)]/duration60: head2, state1 excludes historical UID, state2 contains it with revision1. No ordinary API can supply this historical exception.

**Legacy undo replay store.** Add `legacy_undo_requests` in0012; model LegacyUndoRequest in calendar_models: idempotency_key String100 PK, import_id UUID FK legacy_import_runs.id, request_hash String64, result JSONB, created_at timestamptz defaultnow. Immutable insert-only durable replay; raw import report/undo_payload never mutated after initial commit. Request hash canonicalizes revision_id, expected_head and reason (excludes key). Under advisory71382413: lookup key FIRST; same hash returns saved exact result even after head changes, different hash409 idempotency_conflict. New key must pass original imported head/fingerprint/eligible target checks; after any prior undo or later calendar change it fails409 legacy_undo_stale. One transaction writes inverse calendar version and replay row, guaranteeing one unique key result. Concurrent identical key requests serialize and replay; concurrent different keys yield one success and one stale. No terminal result stored in mutable import report. `/history/agent-undo` availability reads request table to indicate already used.

**Canonical preservation scope.** TASK-068 takes before/after hashes of ALL rows in plan_versions,planned_sessions,completion_links,checkins,checkin_revisions,weekly_snapshots,coach_plan_revisions,coach_recommendations,coach_outcomes,coach_outcome_events,profile_versions,manual_sessions,strong_workouts,activities,activity_sources,source_records,raw_objects. Include archived/draft/rejected/superseded/unmapped rows. For each row serialize all persisted columns by sorted column name: UUID lowercase hyphen string; aware timestamps UTC ISO8601 with exactly six fractional digits and Z; dates YYYY-MM-DD; Decimal plain fixed decimal string preserving DB scale; floats finite JSON numbers (reject NaN/Inf), bytes lowercase hex; JSONB recursively sorted object keys, preserve array order; SQL NULL and JSON null both JSON null in their respective field context. UTF-8 compact JSON ensure_ascii=False, allow_nan=False. Per-row SHA256; per-table SHA256 sorted list of [primary_key,row_sha]; count compared separately. No physical PostgreSQL row-byte comparison. Source files verified by stored SHA, not copied into logs. Exclude only AppState and new tables from source-equivalence set because they intentionally change. Upgrade adds default/null Activity columns before both cutover snapshots; compare identical column projection at start/end of cutover.

**Old writer inventory/guard sites.** All paths `/api/v1` prefixed. `legacy_cutover.require_legacy_write(session)->None` acquires advisory71382413, plain-reads authority, raises409 legacy_write_disabled before mutation if calendar; same transaction retains lock through existing commits. Insert at entry before ORM row locks in core.post_checkin (POST/checkins), core.patch_checkin (PATCH/checkins/{id}), core.post_plan (POST/plans), core.decide_plan (shared POST/plans/{id}/accept and reject), core.post_completion_link (POST/completion-links), core.delete_completion_link (DELETE/completion-links/{id}), core.post_weekly_snapshot (POST/weekly-snapshots), coaching._post (shared POST/coach/daily and weekly), coaching.post_outcome (POST/coach/recommendations/{id}/outcome). In agent_plans.submit and rollback call it immediately after existing advisory acquisition and before any replay/current-state lookup; _persist additionally asserts held authority before writes as internal defense. agent.proposals and rollback_revision delegate guarded services, no HTTP-only precheck. Existing commits keep lock until complete. All listed legacy source GETs stay read-only and available. Profile/annotation/manual/ingest/conflict resolution remain permitted through coordinated source revision helper. Read authority helper `planning_authority(session)->str` uses plain read, no mutation or rowlock.

**Helper artifact handoff.** TASK-065 artifact manifest `coach-helper.manifest.json` (repo skill directory) exact fields `{artifact_version:'going-bananas-coach.MVP-1.0',protocol:'coach_proposal.v1',required_authority:'calendar',activation:'manual',files:[{path,sha256}]}`. Hash every relative regular file except manifest; paths sorted, no symlinks/traversal. Existing helper is legacy-only; replacement is calendar-only and must fail closed without auto fallback when authority mismatch. Read-only GET/profile supplies authority; `coach schema` supplies schema_version coach_proposal.v1 and activation manual (no database mutation). Release owner verifies artifact hashes plus mocked helper tests, stores previous helper artifact/hash and tested backup before quiescence. Keep API/worker/automatic clients stopped during external install; install replacement, verify installed hash, while API/worker remain stopped run local read-only `coach schema` command and verify schema protocol; only then run local DB cutover command and commit calendar authority. Start API, verify GET/profile authority=calendar, then resume worker/UI/helper. No new maintenance server mode is implied. Install/precommit failure: DB remainslegacy, restore previous helper and verify old hash before resuming. Postcommit install mismatch (e.g. restart discovers drift): do not revert DB automatically or run oldhelper; keep API/worker stopped, reinstall verified replacement then resume, or execute manager-approved full DB+files restore procedure. Endpoint authority guards prevent bypass even if a stale helper survives. External artifact installation and real cutover remain release-owner work, not ordinary packet edits.

VerifiedKnowledge is TASK-061 frozen(digest,selection,selected_records,policy_ids,recipe_ids,evidence_ids); TASK-060 verify_selection returns mapping used by caller to construct it. Snapshot selection persists kb_routes and payload.snapshot_meta.knowledge.selected_records. Proposal submit/decision require resolve_kb callback. Decision hash includes proposal_id, sorted accepted/rejected change IDs, block acceptance bool, sorted anchor keys; excludes idempotency key/expected_head. Base mismatch proposal_stale, source mismatch stale_evidence. Existing source writers may call coordinated db.bump_data_revision; the ban on direct bumps applies to new services, not preserved importer paths.

Legacy safety continuity: decision-input collector/snapshots include schema_version1 legacy checkins with observed_at in [now−72h,now], original categorical values/IDs/versions and revision provenance, even after authority switches. Fingerprint these inputs. `legacy_safety_active` is true if any included row has gait='affected', symptoms='severe', or symptoms='moderate' and change='worse'; V12 safety_guard is OR of this flag and current v2 safety facts. Keep qualitative source representation; never convert categories into numerical severity/fatigue. Snapshot exposes the old observation explicitly with its timestamp and missing v2 fields. TASK-068 synthetic fixture includes a recent severe legacy checkin; postcutover snapshot preserves it and hard safety guard remains true.
