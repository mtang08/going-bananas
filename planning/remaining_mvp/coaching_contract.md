# Going Bananas — coaching contract (MVP-1.0, planning freeze candidate)

Scope: the deterministic app ↔ Codex skill boundary, KB retrieval, proposal validation and acceptance, daily rules fallback, triggers, and the calendar bootstrap. Data shapes → `schemas.md`. Decisions → `decisions.md`.

## 1. Responsibilities

| Concern | Owner |
| --- | --- |
| Identity, arithmetic, metrics, data quality, versioning, calendar integrity, validation | App (deterministic) |
| Interpreting context, choosing changes, explaining tradeoffs, stating uncertainty | Skill (LLM) |
| Approving material changes | User, in the app UI |
| General coaching knowledge | KB (`running_coach_kb/` 1.1.0+privacy1); never runtime athlete facts |

The skill never writes directly to the database. `coach submit` stores a pending proposal only; applying requires the separate user decision endpoint. The app never calls a model.

## 2. Operations

| Operation (KB route key) | Typical trigger | May change | Session date scope |
| --- | --- | --- | --- |
| `proceed_or_modify_today` | `coach_review_suggested` on today's guidance | sessions | today … today+3 |
| `review_rolling_plan` | banner on the profile's `weekly_review_weekday` (default Sunday, `profile_versions.preferences.weekly_review_weekday`, 0 = Mon … 6 = Sun; editable in Settings) when no `review_rolling_plan` proposal was decided in the prior 6 days (Q-C4) | sessions | today … today+13 |
| `select_quality_session` | sub-step of rolling review; also standalone for a quality slot with `recipe_id = null` | sessions (quality slots only) | today … today+13 |
| `review_training_block` | block `review_date` ≤ today, early trigger, or no active block after setup | block + sessions | today … today+13 |
| `recalibrate_intensity` | event/benchmark result recorded, or user request | anchors (+ target fields) | today … today+13 |
| `handle_goal_or_race_change` | event created/changed with priority `target` or `supported_exposure` | block + sessions | today … today+13 |

Layer rules (KB `workflows/block_review.md` layer table): daily never changes block, run frequency, or strength count; rolling stays inside the active block's `eligible_recipe_ids`; only block/race operations change the block.

## 3. Skill

### 3.1 Location and packaging
`going-bananas/.codex/skills/going-bananas-coach/SKILL.md` (repo-local, versioned with the app; `skill_version: running-coach.v1`). User confirmed Codex only. TASK-065 packages the current helper contract in this repo-local source and extends it for pending proposals. The installed external skill is preserved until TASK-068 explicitly updates it during authorized implementation; no silent overwrite or second platform.

### 3.2 Procedure (normative text for SKILL.md)
1. Determine the operation from the user's request; default `review_rolling_plan`.
2. Run `scripts/with-mode ${GB_MODE:-real} bash -c 'cd backend && uv run python -m app.cli coach snapshot --operation <op>'` (all CLI calls in this procedure use the same `GB_MODE`; `GB_MODE=demo` is used for case evaluation).
3. Read only the snapshot payload and the KB excerpts it returns. Do not open KB files or repo source directly (`deep_evidence_audit` is not a P0 operation).
4. If a needed fact is missing, run at most 3 `coach query` commands from `drill_down_queries`.
5. If a missing input blocks a useful decision (KB `daily_recommendation.md` clarification rule), ask the user one question, then continue.
6. Write the proposal (`schemas.md` §4.2) to `private/<GB_MODE>/coach/proposals/<UTC timestamp>-<op>.json`.
7. Run `coach submit --file <path>`. Exit 2 → fix the listed errors and resubmit (max 2 retries). Exit 3 → regenerate from step 2 once.
8. Report to the user: summary, each change with reason, confidence, follow-up, and "Review in the app: Home → Pending proposal".
9. Never quote secrets, raw GPS, or full activity streams.

### 3.3 Output content per operation (KB `COACHING_GUIDE.md` §8)
- Daily: decision, session intent, change from plan, rationale, IDs, confidence, missing/stale inputs, follow-up.
- Rolling: actual vs planned, adaptation vs tolerance, delayed symptoms, strength interactions, block alignment, committed/provisional changes, tradeoffs, IDs, uncertainty, escalation.
- Block: lifecycle decision, objective status, exposure, adaptation, tolerance, maintained qualities, next emphasis, eligible recipes, 14-day implications, review conditions.
- Calibration: comparability facts, retain/update decision, old/candidate anchors, method/date/confidence, unsupported conversions, first-use guardrails.
- Race change: event priority/purpose, block impact, preserved/dropped objective, changes, deferred taper/testing items.

All of the above go in `summary`, `rationale`, `changes[].reason`, `confidence`, `follow_up`, `escalation`, and the ID arrays.

## 4. Proposal validation (deterministic, `coach submit` and again on partial acceptance)

Errors return `{code, path, message}`; any error → status `invalid` (exit 2), except V3 → `stale` (exit 3).

| ID | Rule |
| --- | --- |
| V1 | Document matches `coach_proposal.v1` (Pydantic model; unknown fields rejected) |
| V2 | `snapshot_id` exists, its `operation` equals the proposal's, and it was generated ≤ 24 h before submission |
| V3 | Calendar and block bases match; snapshot decision-input fingerprint and KB digest match current sources at submit and acceptance. Empty calendar head is 0; absent block is null. Changed sources return stale even if the calendar head is unchanged. |
| V4 | `change_id` unique; each `session_uid` exists and is not deleted at head; a session appears in at most one change; `preserved` IDs exist |
| V5 | Every touched session's before and after `local_date` lies within the operation's date scope (§2) |
| V6 | `add`/`modify` with `kind=run`: `recipe_id` ∈ REC001–REC010, or `custom=true` with non-empty `structure`; if a block is active, `recipe_id` ∈ its `eligible_recipe_ids` unless the operation changes the block |
| V7 | Resulting calendar has ≤ 1 run per local date |
| V8 | Every resulting run date is a run-cycle opportunity (`domain/cycle.py` parity from the confirmed anchor); otherwise the change must carry `"material_flags": ["off_cycle_run"]` and the operation must be `review_rolling_plan`, `review_training_block`, or `handle_goal_or_race_change` |
| V9 | Each Mon–Sun week fully inside the scope keeps ≥ 2 strength sessions; a strength move must carry `"material_flags": ["strength_move"]`; daily operation may not move strength |
| V10 | Per Mon–Sun week: ≤ 1 session classed `long`; quality count not increased by a `move` (anti make-up pileup) |
| V11 | `policy_ids`, `recipe_ids`, `evidence_ids` all resolve in the loaded KB |
| V12 | Safety guard (hard block, Q-C2): if the snapshot shows, within the last 72 h, `gait_change=yes`, a symptom severity ≥ 6.5, `illness=present`, or an active clinical restriction, or legacy_safety_active, then no change in today…today+3 may add a run, increase `planned_duration_s`, or set a quality recipe |
| V13 | `block_change.decision`: `start` only when no active block; other decisions require an active block; `review_date > start_date`; `eligible_recipe_ids ⊆ REC001–REC010` |
| V14 | `anchor_changes`: kind/unit compatible, enums valid, `value_low ≤ value_high` |
| V15 | `select_quality_session` may only modify sessions that are quality slots (quality recipe or `placeholder = true`); a modify that sets `recipe_id` clears `placeholder` |

Certainty is derived by the app, never taken from the proposal: after any write, sessions dated today…today+6 are `committed`, today+7…today+13 `provisional`.

## 5. Acceptance

`POST /coach/proposals/{id}/decision` requires `idempotency_key`, `expected_head`, complete disjoint accepted/rejected change IDs, `accept_block_change`, and accepted anchor keys.
1. Acquire advisory transaction lock 71382413, then app-state row lock, then proposal row lock. Identical terminal selection replay (same or new key) returns the stored result (including the original version) before freshness checks. Same key/different selection or changed terminal selection returns409 `decision_conflict`; reuse of a key for another proposal returns409 `idempotency_conflict`. Same terminal selection with a new key also returns the stored result.
2. Check calendar/block bases, snapshot age/date, current source fingerprint and KB digest. Changed source input sets proposal stale and returns 409 `stale_evidence`; moved head/block returns409 `proposal_stale`; no calendar/anchor/block writes. Load current safety facts, never rely only on old snapshot flags.
3. Build the selected document and revalidate V4–V15, including block eligibility and anchor-dependent targets against the resulting selected state. An invalid subset returns 422 and writes nothing. Reject-all is recorded without a new calendar version. A true empty proposal can be accepted as no-change, also without a calendar version.
4. In one transaction persist accepted session revisions, optional block version/history and anchors, proposal/change decisions, decision request hash and response, and source-revision invalidation. Use calendar/anchor services rather than copied persistence logic; bump source revision once, recompute metrics/prompts once. Mark other pending proposals stale when their decision inputs change. No automatic acceptance or retry.
5. Latest eligible changed revision supports protected compensating undo. Preserve completed/locked/historical sessions and immutable evidence. No-change reviews do not hide undo. The result lists restored and preserved session IDs; the UI must not promise historical byte equality. TASK-068 supplies the equivalent adapter for existing legacy history.

`submit_proposal` also serializes with this lock and replays identical content without creating duplicates. Snapshot identity excludes generated timestamps and derived-only writes, includes actual source versions, profile, recurrence, completions, calendar/block/anchor dependencies and KB digest. Preserve current `agent_plans` evidence-hash and revision guarantees until cutover.

## 6. KB routed retrieval (additive extension to the installed v1.1 loader)

1. Read `running_coach_kb/manifest.json`; require `schema_version == "1.1"`.
2. For every entry in `files` with non-null `sha256`, verify byte count and SHA-256; any mismatch → `KnowledgeIntegrityError` (CLI exit 4; API 503). Path traversal/symlink guards from the current loader are kept.
3. Route = `manifest.routing[operation]`. Include every `minimum` item:
   - `{path, sections[]}` → extract each section by exact heading text. A section starts at a line `#{1,6} <text>` (text compared after stripping leading/trailing spaces) and ends before the next heading of the same or higher level. Missing heading → `KnowledgeIntegrityError`.
   - `{state: ...}` → satisfied by the snapshot payload; nothing loaded.
4. Conditional items are chosen by the snapshot builder with this trigger table; each adds the whole named topic file:

| Trigger in snapshot | Adds |
| --- | --- |
| any symptom report in window, or delayed-response prompt answered | `topics/ptt_and_load_tolerance.md` |
| any recovery adverse flag or discordance, or illness ≠ none | `topics/recovery_and_daily_adaptation.md` |
| lower-body strength within 48 h of a touched session, or a strength move considered | `topics/hybrid_strength_and_scheduling.md` |
| operation rolling/block and long-run change possible | `topics/long_runs_and_race_development.md` |
| operation rolling/block | `topics/aerobic_progression.md` |
| quality slot in scope | `topics/intensity_and_workout_methods.md` |
| operation calibration, or anchors with confidence `low|insufficient` used for a target | `topics/intensity_calibration_and_testing.md` |
| operation block/race | `topics/periodization_and_training_blocks.md`; race also `topics/races_tapers_and_transitions.md` |

5. Recipes: include records for every `recipe_id` of sessions in scope. Only for `review_rolling_plan` and `select_quality_session`, also include, for quality slots in scope, the active block's `eligible_recipe_ids` (all quality recipes when no block). Daily never receives candidate recipe lists. Evidence registry and source registry: only for `deep_evidence_audit`.
   Policies: policy records carry no `decision_ids` field, so the loader uses this fixed map (planner call, from policy titles):

| Operation | Policy records |
| --- | --- |
| `proceed_or_modify_today` | P001, P002, P004, P005, P006, P012, P013, P015, P018 |
| `review_rolling_plan` | P001, P003, P006, P007, P008, P009, P010, P012, P013, P014, P015, P016, P017 |
| `select_quality_session` | P009, P014, P015, P020 |
| `review_training_block` | P003, P007, P009, P014, P019, P021 |
| `recalibrate_intensity` | P010, P015, P020, P021 |
| `handle_goal_or_race_change` | P019, P022, P023 |

   P011 ("Schedule strength as a coequal goal") is excluded from all routes: it conflicts with the 1.1 priority wording (running first, two lifts as a commitment; `baseline_audit.md` §5.2) and with D13.
6. Manifest amendment A1 (applied by TASK-060 overlay): in `routing.select_quality_session`, the section name for `topics/intensity_and_workout_methods.md` "Two demanding exposures within seven runs per fortnight" is replaced by "Two demanding exposures within the agreed rolling-cycle run count" (actual heading, line 64 of that file). All other routed headings verified present exactly once.
7. Return `{package_version, excerpts:[{path, section|record_id, text}], chars, approx_tokens}`. No truncation; budget overruns are logged, not cut (safety outranks the target).

## 7. Daily rules fallback `local_rules.v2` (`backend/app/services/coaching.py`)

Implement v2 in new `services/daily_guidance.py`; keep legacy coaching.py unchanged until068. Symptom bands: zero none; (0,3] mild; (3,6.5) moderate; ≥6.5 severe. Values are continuous, not half-point buckets. Worse means greater severity than previous same site/side report within7days; fatigue≥7 adverse; gait=yes, illness=possible/present and nonempty clinical restriction map to the defined rules. Unknown inputs stay unknown and never alone downgrade. Keep explicit no-anchor/no-plan guardrails.

Runs on POST /v2/checkins exception or explicit POST /coach/v2/daily/request {}. GET /coach/v2/daily is pure latest persisted read; never refresh on GET. Compute idempotent input_hash; store created_at and enum seek_clinical_input. No current check-in means planned session stands with missing confidence inputs. coach_review_suggested when decision≠proceed, severity>3 or worsening, gait change, possible/present illness, two unknown/skipped committed runs in7days, or delayed follow-up symptom. Evidence IDs are selected KB policy records, never executable policy activation.

## 8. Calendar bootstrap (D10) — `POST /calendar/bootstrap`

Inputs: confirmed `anchor_date`, strength routine slots, pattern `{quality: 1, long: 1}`, `start_date` (default today). Deterministic fill for `[start_date, start_date+13]`:
1. Run dates = cycle opportunities (`cycle.opportunity`) in the range.
2. For each Mon–Sun week overlapping the range, considering only dates inside the range (weeks are clipped to `[start_date, start_date+13]`): `long` = the latest run date in that week falling on Sat/Sun, else the latest run date in that week. `quality` = the earliest run date in that week that is ≥ 2 days before the week's long run, else none for that week.
3. Easy runs: `recipe_id=REC001`, `planned_duration_s` = median `timer_s` of non-long runs in the prior 28 days rounded to the nearest 300 s; if < 3 such runs, 1,800 s.
4. Long run: `REC002`, `planned_duration_s` = max `timer_s` of long-classified runs in the prior 28 days rounded down to 300 s; if none, 1.33 × easy duration rounded to 300 s.
5. Quality slot: `recipe_id = null`, `custom = false`, `placeholder = true`, `intent = "Quality slot — selected at first review"`, duration = easy duration. The first `review_rolling_plan`/`select_quality_session` run fills it. No physiology in code.
6. Strength/mobility: use confirmed profile `recurring_sessions`, including alternating rotation and optional mobility. Routine templates decorate sessions; never reset recurrence to Monday/Friday.
7. Certainty per §4. Writes calendar version 1 (`kind=bootstrap`, `actor=system`).

## 9. Prompt generator (`backend/app/services/prompts.py`)

Runs after every sync page commit and every check-in/calendar write; idempotent via `prompts` UQ.
- `rpe`: run activity synced, no effective RPE; opens at sync, closes `end_at + 48 h`.
- `delayed_symptom`: run classified long, or any run with a symptom report in the prior 14 days; opens `end_at + 16 h`, closes `end_at + 48 h`.
- `unmatched_session`: run activity with ≥ 2 same-day candidates or a ±1-day move candidate (`metrics.md` §4).
- `missing_activity`: run session dated in [today−7, today−1] with no completion after a sync covering its date (certainty not considered).
- Answering: `rpe` → answered when an effective RPE exists; `delayed_symptom` → answered by `POST /v2/checkins` with `kind=delayed_followup` and the `prompt_id` or matching `activity_id`; `unmatched_session`/`missing_activity` → answered when a completion exists for the session.
Expired prompts become `expired`; their data stays `missing/unknown`.

## 10. Coexistence and ownership

TASK-060 extends `load_knowledge`/`KnowledgeContext` with routed selection; it must retain existing callers and selective policy/source/recipe behavior. Do not recopy the already-installed KB 1.1.0+privacy1 package or replace all existing tests. Snapshot projection is platform-neutral. The current `/coach/agent` service and `core.get_context`/`summary` stay until TASK-068 changes write authority; legacy reads remain afterward. New deterministic guidance is `/coach/v2/daily`; new check-ins are `/v2/checkins`, avoiding collisions with working legacy contracts. New writes require calendar authority. `planning_authority=legacy` means no replacement automatic writes, no empty bootstrap over an existing plan, and no replacement live navigation.

Structure is the schema Step|RepeatBlock union (count≥2, one level, target nullable). Expansion interleaves child steps for each repetition and derives step_path string, 1-based expanded_step and zero-based nullable repeat_index; no stored per-step `repeat` convention. Recipe candidates remain selective: daily receives current relevant recipes only. Preserve hard resource bounds and privacy exclusions; report budget overruns without silently dropping safety evidence.

## Preserved schema1 safety during cutover

Snapshots and source fingerprints include original legacy check-ins observed in the inclusive72h UTC window ending now, as categorical schema1 facts with IDs/version/time and severity_numeric:null. No conversion to numeric symptom severity, fatigue or illness is allowed. `legacy_safety_active` is true for gait affected, symptoms severe, or symptoms moderate with change worse; V12 treats it as an additional active guard at submit and acceptance, independent of newer v2 feedback. Snapshot `legacy_checkins` is separate from v2 measurements and excludes notes. Original rows are authoritative; imported archive mappings are not duplicate observations. Older/future rows are excluded from this compatibility guard.
