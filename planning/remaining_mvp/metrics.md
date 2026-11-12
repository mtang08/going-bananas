# Going Bananas — P0 metrics (remaining-MVP contract, 2026-11-12)

Status: **reviewed by user 2026-11-11** (D17). Parameters below are planner decisions that close every "configurable / engineering choice" left open by Workstream B. Canonical/synthetic contracts freeze now; G2 gates real-device acceptance/release only. No unseen FR265 capability is verified. Normative reconciliations in §§6–10 supersede older summary language.

## 0. Sources this document freezes against

| Ref | Reference relative to /Users/mtang/dev/going_bananas_planning_handover (unchanged; no copy) |
| --- | --- |
| B-common | `going_bananas_metrics_repair/metrics_research_handoff/metric_specs/00_common_metric_contract.md` |
| B-specs | same folder, `<metric_id>.md` |
| B-design | `going_bananas_metrics_repair/metrics_research_handoff/design_evaluations.md` |
| B-schema | `going_bananas_metrics/athlete_state_snapshot.schema.json` + `athlete_state_examples/*.json` |
| A-calib | `going_bananas_periodization/.../proposed_patch/running_coach_kb/topics/intensity_calibration_and_testing.md` |

Workers implement this frozen contract and exact packets without research retrieval. Original evidence remains in the unchanged external handover; research_intake.md records provenance. This file fixes engineering choices and overrides research examples where stated.

## 1. P0 metric list (decision D3: full FIT in P0)

| metric_id | P0 slice | Primary inputs | FIT needed |
| --- | --- | --- | --- |
| `intensity_anchor_registry.v1` (control) | P0-A | user/coach-accepted anchors | no |
| `run_volume_frequency.v1` | P0-A | session timer time, distance | no (summary JSON fallback) |
| `planned_actual_session.v1` | P0-A | calendar, activity, laps/steps | steps only |
| `intensity_time_distribution.v1` | P0-A | records, events, anchors | yes |
| `work_interval_execution.v1` | P0-A | plan steps, FIT steps/laps/records | yes |
| `long_run_exposure.v1` | P0-A | runs, classification, symptoms | no |
| `session_rpe_load.v1` | P0-A | timer time, RPE (Garmin or manual) | `workout_rpe` optional |
| `symptom_response_timeline.v1` | P0-A | check-ins | no |
| `recovery_multisignal_summary.v1` | P0-A | Personal API sleep/HRV/daily HR, check-ins | no |
| `hard_session_spacing.v1` | P0-A | calendar, activities, strength | no |

P1 (not built in P0): `comparable_effort_speed`, `aerobic_decoupling`, `transparent_hr_load`, `terrain_exposure`. Excluded: see `progress.md` E6.

## 2. Common parameters (override B-common "engineering defaults")

| Parameter | Value |
| --- | --- |
| Result `status` enum | `available, partial, missing, invalid, not_applicable, not_assessable` |
| `quality_status` enum | `good, limited, insufficient` |
| `max_record_gap_s` | 10 |
| Trace coverage labels | good ≥ 0.90; limited 0.70–<0.90; insufficient < 0.70 |
| Local-day assignment | activity local start time in profile IANA timezone (E5) |
| Rolling windows | 7, 14, 28, 56, 84 local days; window N = `[today−N+1, today+1)` local dates; 84 used only in block projection |
| Units stored | s, m, m/s, bpm, °C; pace only at presentation |
| Duration for load/volume | FIT session `total_timer_time`; if no FIT, Personal API `duration` field (`GATED`), else `missing` (never elapsed or moving) |
| Idempotence key | `(metric_id, method_version, subject_key, dependency_hash)` → historical upsert; one current row |
| Config storage | one versioned `metric_config` record per method version; every result stores `config_hash` |

## 3. Intensity anchors and zones

### 3.1 Vocabulary (reconciles A-calib and B-spec)

- `confidence`: `high | moderate | low | insufficient` (A-calib). Replaces B's `uncertainty` field.
- `status`: `provisional | active | expired | invalid` (B). Only `active` anchors feed metrics.
- `review_after`: default `calibrated_at + 84 days`; after it the anchor stays `active` and results carry flag `ANCHOR_REVIEW_DUE`. No automatic expiry.
- `protocol`: `race_5k | time_trial_5k | time_trial_1mile | time_trial_3min | time_trial_20_30min | workout_derived | lab_test | manual` (D14).

### 3.2 Anchor kinds

| kind | unit | Used by |
| --- | --- | --- |
| `hr_aerobic_upper` | bpm | HR zones |
| `hr_threshold_lower` | bpm | HR zones |
| `speed_aerobic_upper` | m/s | speed zones |
| `speed_threshold_lower` | m/s | speed zones |
| `performance_5k`, `performance_1mile` | s; performance_3min=m; performance_20_30min=mps (A18) | stored context only; never converted into zone anchors by code |

The app performs **no physiological conversion** (e.g., 5K → threshold). Zone anchors are entered by the user or accepted from a `recalibrate_intensity` proposal, which states method and confidence.

### 3.3 Zone model — 3 zones per modality (matches B-schema examples `easy_s/moderate_s/high_s`)

```text
zone(v) = easy      if v <  aerobic_upper
          moderate  if aerobic_upper <= v < threshold_lower
          high      if v >= threshold_lower
config error if aerobic_upper >= threshold_lower
```

- Modalities: `hr`, `speed`. Power excluded in P0. Each modality publishes its own distribution; never blended.
- A modality is assessable only when both of its kinds have an `active` anchor with confidence ≠ `insufficient`; else `not_assessable` reason `ANCHOR_MISSING`.
- Result carries the lower of the two anchor confidences and flag `LOW_CONFIDENCE_ANCHOR` when `low`.
- Narrow pace/HR **targets** in planned sessions require `moderate|high` confidence (A-calib); otherwise targets are effort-based.

## 4. Per-metric parameters

### `run_volume_frequency.v1`
B-spec as written. Also report previous non-overlapping window totals. Sport filter: `activities.sport IN ('running','trail_running','treadmill_running')` (values from `adapters/garmin/normalize.py:81-83`).

### `planned_actual_session.v1`
- Matching, unknown/ambiguous state and all-link writeback use §8 (exactly one eligible unlinked plan AND subject). No-activity remains unknown until explicit resolution; complete coverage yields NO_ACTIVITY_FOUND.
- Components use unrounded ratio boundaries: duration/distance met≥.90, partially_met≥.50, otherwise not_met; EXCEEDED if>1.15. Steps met≥1, partially_met≥.50. Target met≥.75, partially_met≥.40. Missing required evidence not_assessable, never compliant.
- Overall status uses the single precedence in §8; measured components retained even when moved/skipped. Versioned engineering heuristics, not scientific coaching thresholds.

### `intensity_time_distribution.v1`
B-spec formula with §3 zones. Boundary rule: lower bound inclusive, upper exclusive. Emit per activity and per rolling window (sums of per-activity seconds, each carrying its anchor set version).

### `work_interval_execution.v1`
- Segment source: plan steps + FIT `wkt_step_index` only (B precedence 1–2). Manual annotation and auto-detection: P1.
- **Mismatch rule (D9):** compare plan work steps to FIT workout work steps after expanding repeats. If count differs or any `duration_type` differs (time vs distance) → whole session work-step evaluation `not_assessable`, reason `WATCH_WORKOUT_MISMATCH`; UI shows both step lists.
- HR summary: exclude first 60 timer-on seconds of each work step; report HR only for work steps ≥ 180 s timer time; never a pass/fail input.
- A work step without valid speed samples → that rep's speed components `not_assessable`, reason `NO_SPEED_SAMPLES`.
- Report per-rep values plus `CV_speed`, `last_first_change_pct`, `completed_work_s`, `planned_work_s`, `target_coverage`. No composite.

### `long_run_exposure.v1`
- Classification precedence: plan link to REC002 → manual annotation `long` → rule `long_rule.v1` (timer duration ≥ 1.33 × median timer duration of prior 28-day runs, requires ≥ 4 prior runs) with `classification_confidence=low`.
- Stale baseline flag `RETURN_FROM_BREAK` when no run in the prior 14 local days.
- Prior-maximum window: **30 days** before the run start, current run excluded (B-spec `long_run_exposure.v1`; not one of the §2 rolling windows by design).
- Weekly share uses the 7-day window **including** the current run.

### `session_rpe_load.v1`
- RPE source precedence: `manual` > `garmin_fit` (`session.workout_rpe / 10`, `GATED`). Both stored.
- Prompt: Home shows RPE prompt for a synced run lacking RPE until 48 h after run end; after that RPE stays `missing`; store `collection_delay_s`.
- Running and strength loads tagged separately; P0 strength sRPE only from manual entry.

### `symptom_response_timeline.v1`
- Timing enum: `during | immediately_after | next_morning | hours_24_48 | later | unknown`.
- Delayed prompt: opens 16 h after end of a long run (classified per above) or of any run with a symptom report in the prior 14 days; closes 48 h after run end; one prompt per qualifying run. Unanswered → `unknown`.
- Recurrence lookback: 28 days.

### `recovery_multisignal_summary.v1`
- Signals: sleep duration (Personal API sleep summaries), overnight HRV (HRV summaries), resting HR (daily heart rate). Exact JSON fields `GATED` (repo already stores these as `recovery_observations`; verify mapping in G2).
- Baseline window: prior 60 local nights; states `none` < 14 valid, `provisional` 14–27, `established` ≥ 28 (B-spec counts).
- HRV ln, other signals untransformed; baseline and z/unknown rules defined in §9.
- Adverse-direction flag (heuristic, labeled): HRV z ≤ −1.5, RHR z ≥ +1.5, sleep z ≤ −1.5.
- Subjective/adverse/discordance use three-valued logic in §9; missing never false. No combined score.
- Sleep regularity and stage data: not built in P0.

### `hard_session_spacing.v1`
- Classes: `quality` = recipes REC003, REC004, REC005, REC006, REC008, REC009; `long` = REC002 (or long classification); `lower_body_strength` = strength sessions whose routine-template slot has `lower_body_cost ∈ {moderate, high}` (D13).
- Strong timing: start time as written + duration when present; if duration missing, end = unknown → hours reported as a range over that local date with `confidence=low`.

## 5. G2 evidence and release gate

Freeze SDK 21.221.0 options, canonical SI contracts, missing-safe behavior and synthetic fixtures now. No packet waits for planning-time inventory. TASK-004 implements inventory after implementation approval; TASK-010 integrates against synthetic contracts. Real-device acceptance requires integration manager/Astra review of redacted device/firmware and SDK/options, immutable raw hashes, representative easy/paused/structured/repeated/incomplete-workout inventories, field types/missingness, timer reconciliation, repeat/lap mapping, speed/RPE units, API recovery-date and timer semantics. Missing representative evidence means unverified, not absent. Record capability pass/fail/unverified; full P0-A signoff requires all included capabilities passing or explicit user-approved scope reduction.

Locked SDK evidence: SDK expanded duration_time is seconds, duration_distance meters; selected decoder uses expand_sub_fields=False and scales raw workout duration/targets once per schemas6.2. workout_rpe scale 1 retains CR10×10, divide once by 10. Canonical repeat_count means total block executions. Device correspondence remains unverified. API duration is not promoted to timer until semantic evidence passes; otherwise timer missing. Initial plausibility remains finite HR30–230 and speed0–10 inclusive; no new physiological thresholds.

## 6. Shared arithmetic and provenance — normative

Schema §6 owns Python signatures. MetricResultData (alias MetricResult) includes timezone, dependency_hash and source_refs. CONFIG includes every threshold/rule. Pure functions receive dates/now/inputs: no DB/network/clock. Engine supplies dependency hash/calculation timestamp/current-row state. Dependencies include selected source revisions/raw hashes, config, timezone, effective anchors, plan revisions and upstream dependency hashes. Preserve history; latest_results selects is_current, never newest obsolete signature.

Records/laps/events share FIT session start origin. Decoder sorts records, collapses exact duplicates, nulls conflicting same-timestamp modality values with DUPLICATE_RECORD_CONFLICT; nonfinite timestamps invalidate. Pure integration rejects non-increasing timestamps. Union overlapping/adjacent timer ranges; reject inverted ranges, ignore zero lengths. integrate_timer_on emits `(index|None, seconds, known)` covering the entire timer union. Record i supplies [t_i,t_i+1); gaps>10s unknown; uncovered leading/trailing portions index=None, known=False. No records means wholly unknown. Unknown timer state is missing, never assumed elapsed. Eligible=full timer union; valid+unknown=eligible. E33 TIMER_MISMATCH at abs(timer_union−session_timer)>max(1s,.01*session_timer) makes reconstructed timer-dependent trace metrics not_assessable; canonical session-timer volume remains valid.

coverage_label compares unrounded valid/eligible; eligible<=0=>None. All measurements finite. Round final outputs only: seconds/meters/AU/bpm/hours1dp; ratios/coverage/speed/CV/change-percent3dp; z2dp. Weighted median: sort (value,positive timer weight), first cumulative>=half; at exactly half average current and next value. HR lag removes first60 timer-on seconds across pauses, require step timer>=180; never scores execution.

All-unknown aggregates are null when sessions exist but none measurable. Valid zero remains zero. Empty complete window=>count0,sum0.0; empty incomplete=>missing,null sums,SYNC_COVERAGE_INCOMPLETE. Known subtotals are partial with missing counts. Missing durations make duration coverage unknown; session coverage supplies quality capped limited. Previous windows carry independent coverage. Unknown/nonpositive ratio denominator=>null; incomplete comparators/shares add PARTIAL_COMPARATOR/PARTIAL_WEEK.

Anchor rows are immutable effective-dated succession; supersession does not deactivate earlier historical eligibility. Schema §6 selects historical effective anchors and hashes immutable content. Performance units follow A18: 5K/1mile=s; 3min=m; 20–30min=mps with duration in conditions. No physiological conversion.

## 7. Structure and interval arithmetic

Canonical one-level nested repeats stay in storage/API. TASK012 services/calendar_structure.py:expand_structure returns ordered plain steps plus step_path, expanded_step(1-based), repeat_index(0-based|null). Work/recovery interleave. Watch repeats retain message indices while expanding positions. Forward/missing repeat references=>MALFORMED_REPEAT; unsupported types=>UNSUPPORTED_REPEAT. Lap index sequence must exactly match a prefix of expanded watch steps; mismatches never guessed. Partial final lap has actual/planned ratio. Zero work steps=>not_applicable NO_WORK_STEPS.

Required speed means a planned work step with target modality speed and finite ordered numeric bounds; HR/effort/null targets do not require speed. Optional speed still reports available/partial/not_assessable separately, but cannot downgrade completion. No scored lap-summary fallback. Null/invalid trace gives NO_STREAM/NO_SPEED_SAMPLES or canonical timer reason; numeric-speed target components become not_assessable while lap completion remains measurable. Target coverage includes only valid speed-target timer seconds, absent eligible target time=>null. HR/effort targets unscored. HR never affects status.

Observed rep means mapped lap exists. Fully completed requires actual timer (time plan) or distance (distance plan) known and actual/planned>=1. n_observed counts mapped laps; n_completed counts fully completed reps; step_completion_ratio=n_completed/n_planned. Missing required actual=>ratio null,rep partial COMPLETION_VALUE_MISSING. Underfilled rep=>partial INCOMPLETE_WORK_STEP. completed_work_s/m sum observed laps including partial reps: none observed=>0 known observed work; observed but all unknown=>null; mixed=>known subtotal with PARTIAL_WORK_TIMER/PARTIAL_WORK_DISTANCE. Any unknown observed work measurement makes overall partial WORK_MEASUREMENT_MISSING. Required speed unavailable/limited makes overall partial; optional speed absent does not. Exact output fields/status ordering in TASK022, which is the executable contract.

CV uses sample SD of unrounded speed means from fully_completed reps with speed_status available (coverage>=.90), requires >=2 and positive mean. Last-first requires original first and last planned work reps both fully completed and speed_status available, firstmean>0. Stopped-after2-of4 => last_first null, never substitute second for last. Missing lap elapsed bounds never become timer-as-elapsed; use next lap start only when present, else trace unassessable. No composite.

## 8. Matching, completion and spacing

Preserve explicit/user_marked/confirmed_move links. Same-day auto-match requires exactly one unlinked eligible plan AND one eligible same-kind subject. Multiple either side=>unknown with AMBIGUOUS_MATCH and ordered candidates. ±1-day run candidates require confirmation. Extra only when no eligible plan in those dates. Delete stale auto links after date/kind changes; do not silently retarget explicit. No matching before calendar origin or head=0. Extras uuid5 namespace e35269d4-74b0-53bf-8a74-f01b3ef69218, name `extra:{subject_key}`. Strong/manual distinct; explicit resolved duplicates excluded, unresolved overlap flagged, never guessed dedupe.

Components require positive planned duration/distance. Structured plan creates required step and speed-target components; unavailable evidence=>not_assessable. No evaluable components=>unknown INSUFFICIENT_PLAN. Overall precedence: explicit skipped; confirmed_move=>moved; extra=>extra; linked step<1 AND duration<.90=>partial; modification reason or partial/not_met=>completed_modified; every required component met=>completed_as_planned; otherwise unknown COMPONENT_NOT_ASSESSABLE. Metric partial for unknown required components. symptom_onset/fatigue/illness add SENSIBLE_MODIFICATION. Recompute/write status for **every linked completion**, preserve move/reason provenance; increment completion version only on actual change. Ambiguous is reason/match state, never completion enum.

Spacing UTC gap=[next_start.low-prev_end.high,next_start.high-prev_end.low]/3600; retain negative overlap. Unknown planned time spans local day, DST-aware. Strong known start/missing end=>end[start,next midnight]; no valid start=>whole-day range. Confidence high only exact bounds. Linked plan+actual counted once using actual; skipped omitted. Sort start.low then subject key. Multi-class exposure cannot pair with itself. w14 includes as_of−7 through as_of+6; output consecutive exposure gaps and each session's nearest earlier/later exposure per class. Classes unchanged from §4.

## 9. Recovery, symptoms and prompts

Night D baseline[D−60,D), partition by source account/kind/statistic-definition/documented device generation. Unknown device is explicit token plus SOURCE_DEVICE_UNKNOWN; never blend across known changes. Latest resolved observation per night, unresolved conflict invalid. HRV>0,RHR30–230,sleep(0,86400], finite. ln HRV, original other units. z=.6745*(x−median)/MAD; baseline<14 or MAD0=>null, transformed raw deviation retained. none<14,provisional14–27,established>=28; valid prior14<7=>BASELINE_STALE. Threshold unrounded z. Adverse false only when z assessable, else null. any_adverse true if any true; false iff all three false; otherwise null. Latest nonnull fatigue/illness independently on D: subjective true if fatigue>=7 OR illness possible/present; false iff fatigue<7 AND illness none; otherwise null. Discordance XOR only both known. w7 summary nights with any valid signal;5/7=.714 limited. Missing dates explicit.

Symptoms explicit activity_id first; otherwise most recent **known actual end** within inclusive0–48h, UUID ascending tie. Timer time cannot establish actual end across pauses. Unknown end=>hours null,END_TIME_UNKNOWN,no inferred association/timed prompt. Explicit timing still buckets; unknown timing with unknown hours=>unknown bucket. Explicit delayed_followup with empty symptoms=>none_reported, no response=>unknown. Long-run and symptoms share linked_activity_for_checkin.

RPE prompt opens known end, closes+48h; delayed opens+16h/closes+48h; persist future rows immediately. Visible opens<=now<closes. Delayed qualifies long or positive symptom in[start−14d,start). Unknown end suppresses timed prompt. RPE answered only valid effective RPE; delayed only delayed_followup linked by activity/prompt; missing/unmatched only valid linked completion OR explicit user_marked skipped/unknown resolution, never mere row existence. Dismissed stays dismissed; expired may become answered on later explicit response, never automatically reopened. DB unique stable kind+subject dedupe. Missing prompts prior7 days excluding today, ignore certainty; ambiguous/moved include today. Expire obsolete match prompts.

## 10. Recompute and tests

TASK030 collects old AND new identities/dates/links before_flush; after_flush stores scope sets. before_commit flushes sources, serializes via app-state row, then guarded passes: rematch → symptoms/volume/long-run/sRPE/intensity/intervals/recovery subjects → planned_actual/writeback → spacing/windows → prompts. Derived writes do not enqueue or bump source revision; derived flush shares source transaction, rollback removes all together. Register once. Bulk dependency mutations forbidden unless explicitly enqueue old/new scopes.

Deleted/excluded subjects invalidate current rows. Activity changes recompute subsequent long-run candidates through+30 local days, symptom associations within48h, old/new calendar links and overlapping stored windows through+83 (volume previous comparison through+167). Recovery change D recomputes D..D+60 plus summaries. Anchor changes recompute from earliest changed validity through successor (conservative all later allowed). Plans/check-ins/strength invalidate linked subjects and date windows; timezone change rebuilds all. Historical rows retained, current flags superseded atomically. ensure_windows refreshes dependencies; ensure_nights never missing-only. Reads may persist derived rows, never bump source revision. Same dependency CLI rerun keeps row counts stable.

Pure fixtures no ORM/network/clock. Integration requires isolated TEST_DATABASE_URL guarded against real/demo URLs, fixed clock/timezone, rollback cleanup, bare routers before wiring, no live clients. Required cases: trace edges/pauses, zero/unknown, source partition, recovery correction, anchor succession, every-link writeback, mismatch, old/new scopes, no-op/idempotence, rollback, DST, prompt boundaries. No application tests run during planning.

