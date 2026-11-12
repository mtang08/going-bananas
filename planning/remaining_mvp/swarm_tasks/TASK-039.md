# TASK-039 — Frontend API types, query keys, and shared formatters for P0-A


Baseline: going-bananas main @ 5ebf981aa4517f4f73f3c97aa5d43232204466ce + merged dependencies per dependency_graph.md; spec planning/remaining_mvp MVP-1.0; use supplied dependency-complete gb-mvp1-* runtime tag
Wave / priority: P0-A; wave 4 (dependency_graph.md).
Dependencies: TASK-001, TASK-003, TASK-012, TASK-013, TASK-014, TASK-030 (all merged)
File ownership: create `frontend/tests/fixtures/planning-wire.json`;  create `frontend/tests/api-format.test.ts`;  `frontend/src/api.ts` (modify); create `frontend/src/api/types/calendar.ts`, `checkins.ts`, `metrics.ts`, `blocks.ts`, `anchors.ts`, `coach.ts`
Forbidden changes: every other file. Do not delete or rename any existing export in `api.ts` (obsolete v1 types such as `Checkin`, `Plan`, `Conflict` stay; removal is out of scope). No new npm dependency. No React components.

## Objective and observable end state
Every Wave-5 page imports its types, query keys, and formatters from `../api`. `cd frontend && npx tsc --noEmit` passes, and `npm test` passes with the new `frontend/tests/api-format.test.ts`. Example: `fmtPaceFromSpeed(800/205, 'mi')` returns `"6:52 /mi"`; `fmtDuration(null)` returns `"missing"`.

## Inputs and fixed contracts
- `schemas.md` §2.2–2.5 (field names and enums), §3.1–3.4 (endpoints); `metrics.md` §2 (status enums), §3 (anchor vocab), §4; `coaching_contract.md` §4 (certainty), §9 (prompt kinds).
- All field names are snake_case exactly as the API returns them. Units are SI (s, m, m/s, bpm). Every response arrives inside the existing `Envelope<T>`; types below describe `T`.
- Type files under `frontend/src/api/types/` contain only `export type` / `export interface` / `export const` literals. They never import from `../../api` (prevents an import cycle with the re-exports).

### `api/types/calendar.ts`
```ts
export type SessionKind = 'run' | 'strength' | 'cross' | 'rest' | 'mobility'
export type Certainty = 'committed' | 'provisional'
export type StepType = 'warmup' | 'work' | 'recovery' | 'cooldown'
export interface StepTarget { modality: 'speed' | 'hr' | 'effort'; low: number | null; high: number | null; effort_cue: string | null }
export interface PlannedStep { type: StepType; duration_type: 'time' | 'distance'; duration_value: number; target: StepTarget | null }
export interface RepeatBlock { type: 'repeat'; count: number; steps: PlannedStep[] }
export type StructureItem = PlannedStep | RepeatBlock
export interface ExpandedStep extends PlannedStep { step_path: string; expanded_step: number; repeat_index: number | null }
export interface SessionFields { local_date: string; slot: number; kind: SessionKind; recipe_id: string | null; custom: boolean; intent: string; placeholder: boolean; locked: boolean; planned_duration_s: number | null; planned_distance_m: number | null; structure: StructureItem[] | null; strength_slot_id: string | null; notes: string | null }
export interface SessionState extends SessionFields { id: string; certainty: Certainty; legacy_unstructured: boolean; legacy_payload: Record<string, unknown> | null; session_uid: string; revision: number; calendar_version_number: number; deleted: boolean; is_original: boolean; changed_by_version: number }
export type CompletionStatus = 'completed_as_planned' | 'completed_modified' | 'partial' | 'moved' | 'skipped' | 'extra' | 'unknown'
export type MatchMethod = 'explicit' | 'auto_same_day' | 'confirmed_move' | 'user_marked' | 'none'
export type ModificationReason = 'symptom_onset' | 'fatigue' | 'illness' | 'schedule' | 'weather' | 'equipment' | 'other'
export interface Completion { id:string;input_version:number; session_uid: string; activity_id: string | null; strong_workout_id: string | null; manual_session_id: string | null; status: CompletionStatus; match_method: MatchMethod; modification_reason: ModificationReason | null; reason_note: string | null; version: number; updated_at: string; local_date: string | null } // local_date [DTO fixed here]: actual subject date when linked, else planned date
export interface CalendarView { today: string; timezone: string; start: string; end: string; version: number; head: number; undo: {target_version:number;eligible:boolean;protected_session_uids:string[]} | null; last_planned_date: string | null; sessions: SessionState[]; completions: Completion[] } // today/timezone/start/end [DTO fixed here]; head 0 = no calendar yet
export type CalendarVersionKind = 'bootstrap' | 'manual_edit' | 'proposal_accept' | 'rollback' | 'legacy_import'
export interface CalendarVersion { number: number; parent_number: number | null; kind: CalendarVersionKind; actor: 'system' | 'user' | 'coach'; reason: string | null; proposal_id: string | null; restored_from_number: number | null; block_version_id: string | null; created_at: string }
export type ChangeOp = 'add' | 'modify' | 'move' | 'delete'
export interface CalendarDiff { changes: { session_uid: string; op: ChangeOp; before: Partial<SessionFields> | null; after: Partial<SessionFields> | null }[] }
export interface CalendarEdit { op: ChangeOp; session_uid?: string; fields: Partial<SessionFields> }
export interface CalendarEditsRequest { expected_head: number; edits: CalendarEdit[]; reason?: string }
export interface CalendarRollbackRequest { expected_head: number; to_version: number; reason?: string }
export interface CalendarBootstrapRequest { anchor_date: string; pattern: { quality: 1; long: 1 }; start_date: string }
export interface CalendarWriteResult { version: number; kind: CalendarVersionKind; stale_proposals: string[]; preserved_session_uids: string[] }
export interface CompletionPut { expected_version?: number; activity_id?: string | null; strong_workout_id?: string | null; manual_session_id?: string | null; status?: 'skipped' | 'unknown'; match_method?: 'explicit' | 'confirmed_move'; modification_reason?: ModificationReason | null; reason_note?: string | null }
export const RECIPE_LABELS: Record<string, string> = { REC001: 'Easy run', REC002: 'Long run', REC003: 'Threshold intervals', REC004: 'Steady / tempo', REC005: 'VO2 intervals', REC006: 'Short intervals / fartlek', REC007: 'Strides', REC008: 'Hills', REC009: 'Benchmark / race-specific', REC010: 'Low-impact substitution' }
export type SessionMarker = 'planned' | 'completed' | 'modified' | 'partial' | 'moved' | 'missed' | 'not_recorded'
export const MARKER_LABELS: Record<SessionMarker, string> = { planned: 'Planned', completed: 'Completed', modified: 'Completed, modified', partial: 'Partial', moved: 'Moved', missed: 'Missed', not_recorded: 'Not recorded' }
```

### `api/types/checkins.ts`
```ts
import type { DailyGuidance } from './coach'
export type CheckinKind = 'exception' | 'post_run' | 'delayed_followup'
export type Illness = 'none' | 'possible' | 'present'
export type GaitChange = 'yes' | 'no' | 'unsure'
export type ContextTag = 'heat' | 'travel' | 'poor_sleep' | 'unusual_surface' | 'equipment'
export type Side = 'left' | 'right' | 'both' | 'na'
export type SymptomTiming = 'during' | 'immediately_after' | 'next_morning' | 'hours_24_48' | 'later' | 'unknown'
export interface SymptomInput { site: string; side: Side; severity: number; timing: SymptomTiming }
export interface SymptomReport extends SymptomInput { id: string }
export interface CheckinCreate { kind: CheckinKind; observed_at: string; fatigue?: number | null; illness?: Illness | null; gait_change?: GaitChange | null; context_tags: ContextTag[]; symptoms: SymptomInput[]; activity_id?: string | null; prompt_id?: string | null; note?: string | null; idempotency_key: string }
export interface CheckinV2 { id: string; version: number; kind: CheckinKind; observed_at: string; recorded_at: string; fatigue: number | null; illness: Illness | null; gait_change: GaitChange | null; context_tags: ContextTag[]; symptoms: SymptomReport[]; activity_id: string | null; prompt_id: string | null; note: string | null; schema_version: number; daily_guidance: DailyGuidance | null }
export interface CheckinList { items: CheckinV2[] }
export type PromptKind = 'rpe' | 'delayed_symptom' | 'unmatched_session' | 'missing_activity'
export interface Prompt { id: string; kind: PromptKind; activity_id: string | null; session_uid: string | null; opens_at: string; closes_at: string | null; status: 'open' | 'answered' | 'dismissed' | 'expired' }
export interface PromptList { items: Prompt[] }
export interface RpeResult { activity_id: string | null; strong_workout_id: string | null; manual_session_id: string | null; rpe: number; source: 'manual'; collected_at: string; collection_delay_s: number | null } // [DTO fixed here]
export interface CheckinRequest { kind: CheckinKind; prompt: Prompt | null; activityId: string | null } // UI-only: what opens the check-in modal
export const TIMING_LABELS: Record<SymptomTiming, string> = { during: 'During the run', immediately_after: 'Immediately after', next_morning: 'Next morning', hours_24_48: '24–48 hours after', later: 'Later', unknown: 'Not sure' }
export const SIDE_LABELS: Record<Side, string> = { left: 'Left', right: 'Right', both: 'Both', na: 'Not applicable' }
export const REASON_LABELS: Record<'symptom_onset' | 'fatigue' | 'illness' | 'schedule' | 'weather' | 'equipment' | 'other', string> = { symptom_onset: 'Symptoms started', fatigue: 'Fatigue', illness: 'Illness', schedule: 'Schedule', weather: 'Weather', equipment: 'Equipment', other: 'Other' }
```

### `api/types/coach.ts` (TASK-066 extends this file later)
```ts
export type GuidanceDecision = 'proceed' | 'modify' | 'reschedule' | 'rest' | 'seek_clinical_input'
export interface DailyGuidance { id: string; created_at: string; input_hash: string; local_date: string; checkin_id: string | null; engine: string; decision: GuidanceDecision; session_uid: string | null; rationale: string; missing_inputs: string[]; coach_review_suggested: boolean; trigger_codes: string[] }
export const DECISION_LABELS: Record<GuidanceDecision, string> = { proceed: 'Proceed', modify: 'Modify', reschedule: 'Reschedule', rest: 'Rest', seek_clinical_input: 'Seek clinical input' }
```

### `api/types/metrics.ts`
```ts
export type MetricStatus = 'available' | 'partial' | 'missing' | 'invalid' | 'not_applicable' | 'not_assessable'
export interface MetricResult<V> { id: string; metric_id: string; method_version: string; subject_type: 'activity' | 'session' | 'window' | 'night' | 'report'; subject_key: string; window_start: string | null; window_end: string | null; window_label: string | null; status: MetricStatus; quality_status: 'good' | 'limited' | 'insufficient' | null; value: V | null; unit: string | null; reason_codes: string[]; quality_flags: string[]; anchor_keys: string[]; calculated_at: string; source_refs: Record<string, unknown>; config_hash: string; anchor_set_hash: string | null; dependency_hash: string; timezone: string; is_current: boolean }
export interface VolumeTotals { start_date: string; end_date: string; runs_missing_timer: number; runs_missing_distance: number; timer_duration_s: number | null; distance_m: number | null; run_count: number }
export interface VolumeValue extends VolumeTotals { previous: (VolumeTotals & {coverage_complete:boolean}) | null }
export interface LongRunEntry { classification: 'long'; linked_checkin_ids: string[]; prior_max_timer_s:number|null; prior_max_distance_m:number|null; week_timer_s:number|null; week_distance_m:number|null; comparator_window:{start_date:string;end_date:string}; weekly_window:{start_date:string;end_date:string}; activity_id: string; local_date: string; timer_s: number | null; distance_m: number | null; duration_ratio_to_recent_max: number | null; distance_ratio_to_recent_max: number | null; weekly_share_duration: number | null; weekly_share_distance: number | null; classification_source: 'plan_link' | 'manual' | 'long_rule'; classification_confidence: 'high' | 'low'; delayed_symptom_status: 'reported' | 'none_reported' | 'unknown' }
export interface LongRunValue { long_run_count: number; latest: LongRunEntry | null }
export interface SrpeValue { duration_total_s:number|null; duration_with_rpe_s:number|null; sessions_without_load:number; sessions_missing_duration:number; load_au: number | null; sessions_with_rpe: number; sessions_total: number; coverage_duration: number | null; coverage_sessions: number | null }
export interface ZoneDistribution { status: MetricStatus; reason_codes: string[]; easy_s: number | null; moderate_s: number | null; high_s: number | null; valid_s:number|null; fraction_valid:{easy:number;moderate:number;high:number}|null; fraction_timer:{easy:number;moderate:number;high:number}|null; activities_total?:number;activities_counted?:number;activities_without_result?:number; unclassified_s: number | null; unknown_s: number | null; eligible_timer_s: number | null; coverage: number | null; confidence: 'high' | 'moderate' | 'low' | 'insufficient' | null }
export interface IntensityValue { hr: ZoneDistribution; speed: ZoneDistribution; session_timer_s?:number|null; anchor_set_hashes?:string[] }
export type HardClass = 'quality' | 'long' | 'lower_body_strength'
export interface GapRange { low:number|null; high:number|null; confidence:'high'|'low' }
export interface SpacingExposure { subject_key:string;classes:HardClass[];local_date:string;session_uid:string|null;activity_id:string|null;source:string;start_low:string|null;start_high:string|null;end_low:string|null;end_high:string|null }
export interface SpacingValue { sessions:{session_uid:string|null;subject_key:string;local_date:string;hours_since:Partial<Record<HardClass,GapRange>>;hours_until:Partial<Record<HardClass,GapRange>>}[]; sequence: SpacingExposure[]; gaps: { from_class: HardClass; to_class: HardClass; from_date: string; to_date: string; hours_min: number | null; hours_max: number | null; confidence: 'high' | 'low' }[] }
export interface WindowMetrics { days: 7 | 14 | 28 | 56; volume: MetricResult<VolumeValue> | null; srpe: MetricResult<SrpeValue> | null; intensity: MetricResult<IntensityValue> | null; long_run: MetricResult<LongRunValue> | null; srpe_strength: MetricResult<SrpeValue> | null }
export interface MetricWindows { as_of: string; windows: WindowMetrics[]; spacing: MetricResult<SpacingValue> | null; symptoms: MetricResult<SymptomWindowValue> | null } // [DTO fixed here]; null result = not computed → shown "missing"
export interface SymptomWindowValue { checkin_count:number;sites:{site:string;side:string;report_count:number;recurrence_days:number;max_severity:number;latest_severity:number;latest_timing:string;gait_change_reported:boolean}[] }
export interface RecoverySignal { baseline_median:number|null;baseline_mad:number|null;deviation:number|null;reason_codes:string[];quality_flags:string[];partition:string|null; status: MetricStatus; value: number | null; baseline_state: 'none' | 'provisional' | 'established'; valid_nights: number; z: number | null; adverse: boolean | null } // sleep value s, hrv ms, resting_hr bpm
export interface RecoveryNight { status:MetricStatus;quality_status:'good'|'limited'|'insufficient'|null;reason_codes:string[];quality_flags:string[];fatigue:number|null;illness:string|null; local_date: string; sleep: RecoverySignal; hrv: RecoverySignal; resting_hr: RecoverySignal; subjective_poor: boolean | null; discordance: boolean | null }
export interface RecoveryNights { start: string; end: string; nights: RecoveryNight[] } // [DTO fixed here]; one entry per local date in [start,end], missing nights included with status 'missing'
export interface Lap { lap_index: number; start_at: string; timer_s: number | null; elapsed_s: number | null; distance_m: number | null; avg_speed_mps: number | null; avg_hr_bpm: number | null; max_hr_bpm: number | null; lap_trigger: string | null; wkt_step_index: number | null }
export interface WatchStep { message_index: number; step_name: string | null; intensity: string | null; duration_type: string; duration_value: number | null; target_type: string | null; target_low: number | null; target_high: number | null; repeat_from: number | null; repeat_count: number | null }
export interface RepResult { step_path:string;repeat_index:number|null;observed:boolean;fully_completed:boolean;reason_codes:string[];speed_status:MetricStatus;speed_reason_codes:string[];speed_coverage:number|null;target_valid_s:number|null;target_in_range_s:number|null;flags:string[]; rep: number; planned_step: number; lap_index: number | null; status: MetricStatus; planned_duration_type: 'time' | 'distance'; planned_value: number; actual_timer_s: number | null; actual_distance_m: number | null; completion_ratio: number | null; mean_speed_mps: number | null; target_modality: 'speed' | 'hr' | 'effort'; target_low: number | null; target_high: number | null; in_target: boolean | null; hr_median_bpm: number | null }
export interface IntervalValue { n_planned:number;n_observed:number;n_completed:number;step_completion_ratio:number|null;completed_work_m:number|null;planned_work_m:number|null; reps: RepResult[]; cv_speed: number | null; last_first_change_pct: number | null; completed_work_s: number | null; planned_work_s: number | null; target_coverage: number | null }
export type ComponentName = 'duration_ratio' | 'distance_ratio' | 'step_completion_ratio' | 'target_coverage'
export interface PlannedActualValue { overall_status: 'completed_as_planned' | 'completed_modified' | 'partial' | 'moved' | 'skipped' | 'extra' | 'unknown'; certainty:import('./calendar').Certainty|null;kind:import('./calendar').SessionKind|null;candidate_activity_ids:string[];calendar_version:number|null;match_method:import('./calendar').MatchMethod; components: { name: ComponentName; value: number | null; status: 'met' | 'partially_met' | 'not_met' | 'not_assessable' }[] }
export type FitStatus = 'not_fetched' | 'fetched' | 'decoded' | 'unavailable' | 'decode_error'
export interface LinkedSymptom { checkin_id: string; observed_at: string; kind: 'exception' | 'post_run' | 'delayed_followup'; site: string; side: 'left' | 'right' | 'both' | 'na'; severity: number; timing: 'during' | 'immediately_after' | 'next_morning' | 'hours_24_48' | 'later' | 'unknown'; hours_after_end: number | null }
export interface ActivityExecution { // [DTO fixed here]
  activity: { id: string; start_at: string; end_at: string | null; local_date: string; sport: string; distance_m: number | null; timer_s: number | null; elapsed_s: number | null; fit_status: FitStatus }
  planned: { session_uid: string; local_date: string; kind: string; recipe_id: string | null; custom: boolean; intent: string; planned_duration_s: number | null; planned_distance_m: number | null; structure: import('./calendar').StructureItem[] | null;legacy_unstructured:boolean;legacy_payload:Record<string,unknown>|null;placeholder:boolean;locked:boolean } | null
  completion: import('./calendar').Completion | null
  laps: Lap[]; watch_steps: WatchStep[]
  planned_actual: MetricResult<PlannedActualValue> | null
  intervals: MetricResult<IntervalValue> | null
  intensity: MetricResult<IntensityValue> | null
  rpe: { effective: number | null; source: 'manual' | 'garmin_fit' | null; manual: number | null; garmin_fit: number | null; srpe_load_au: number | null }
  symptoms: LinkedSymptom[]
}
```

### `api/types/blocks.ts`
```ts
export type GoalHorizon = '3_6_months' | 'season' | 'long_term'
export interface Goal { id: string; text: string; horizon: GoalHorizon; priority: number; status: 'active' | 'paused' | 'done' | 'dropped'; version: number }
export type GoalCreate = Omit<Goal, 'id' | 'version'>
export type GoalPatch = Partial<GoalCreate> & { expected_version: number }
export type EventPriority = 'target' | 'supported_exposure' | 'benchmark' | 'optional'
export type EventStatus = 'planned' | 'registered' | 'completed' | 'cancelled'
export interface RaceEvent { id: string; name: string; event_date: string; distance_m: number | null; priority: EventPriority; status: EventStatus; result_s: number | null; version: number }
export type RaceEventCreate = Omit<RaceEvent, 'id' | 'version'>
export type RaceEventPatch = Partial<RaceEventCreate> & { expected_version: number }
export interface StrengthRoutineSlot { id: string; label: string; default_weekday: number; lower_body_cost: 'low' | 'moderate' | 'high'; typical_duration_s: number | null; main_lower_body_lifts: string[]; active: boolean; version: number }
export interface ConfirmedSchedule { strength_days_confirmed:boolean;strength_schedule_mode:'weekly'|'alternating';scheduled_strength_days:number[];strength_week_a_start:string|null;strength_week_a_days:number[];strength_week_b_days:number[];mobility_week_a_days:number[];mobility_week_b_days:number[];mobility_optional_days:number[] }
export interface StrengthRoutine { version: number; slots: StrengthRoutineSlot[]; suggested: boolean; schedule: ConfirmedSchedule } // [DTO fixed here] version 0 + suggested=true: nothing saved, slots pre-filled from Strong (D13)
export interface StrengthRoutinePut { expected_version: number; slots: Omit<StrengthRoutineSlot, 'id' | 'version'>[] }
export interface BlockVersion { block_uid: string; version: number; status: 'draft' | 'active' | 'consolidating' | 'completed' | 'replaced' | 'ended'; objective: string; rationale: string; maintained_qualities: string[]; non_goals: string[]; eligible_recipe_ids: string[]; progression_dimension: string; start_date: string; review_date: string; completion_indicators: string[]; early_review_triggers: string[]; objective_status: string; created_at: string }
export const HORIZON_LABELS: Record<GoalHorizon, string> = { '3_6_months': '3–6 months', season: 'Season', long_term: 'Long term' }
export const EVENT_PRIORITY_LABELS: Record<EventPriority, string> = { target: 'Target', supported_exposure: 'Supported exposure', benchmark: 'Benchmark', optional: 'Optional' }
export const WEEKDAY_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const // index 0 = Monday
```

### `api/types/anchors.ts`
```ts
export type AnchorKind = 'hr_aerobic_upper' | 'hr_threshold_lower' | 'speed_aerobic_upper' | 'speed_threshold_lower' | 'performance_5k' | 'performance_1mile' | 'performance_3min' | 'performance_20_30min'
export type AnchorProtocol = 'race_5k' | 'time_trial_5k' | 'time_trial_1mile' | 'time_trial_3min' | 'time_trial_20_30min' | 'workout_derived' | 'lab_test' | 'manual'
export type AnchorConfidence = 'high' | 'moderate' | 'low' | 'insufficient'
export interface IntensityAnchor { id: string; anchor_key: string; kind: AnchorKind; value_low: number; value_high: number | null; unit: 'bpm' | 'mps' | 's' | 'm'; protocol: AnchorProtocol; confidence: AnchorConfidence; status: 'provisional' | 'active' | 'expired' | 'invalid'; calibrated_at: string; valid_from: string; review_after: string; source_activity_id: string | null; source_event_id: string | null; proposal_id: string | null; conditions: string | null; notes: string | null; supersedes_key: string | null }
export interface AnchorCreate { kind: AnchorKind; value_low: number; value_high: number | null; unit: 'bpm' | 'mps' | 's' | 'm'; protocol: AnchorProtocol; confidence: AnchorConfidence; calibrated_at: string; conditions: string | null; notes: string | null; supersedes_key: string | null }
export interface AnchorList { items: IntensityAnchor[] }
export const ANCHOR_KIND_LABELS: Record<AnchorKind, string> = { hr_aerobic_upper: 'Aerobic upper (HR)', hr_threshold_lower: 'Threshold lower (HR)', speed_aerobic_upper: 'Aerobic upper (pace)', speed_threshold_lower: 'Threshold lower (pace)', performance_5k: '5K performance', performance_1mile: '1 mile performance', performance_3min: '3 minute performance', performance_20_30min: '20–30 minute performance' }
export const ANCHOR_UNIT: Record<AnchorKind, 'bpm' | 'mps' | 's' | 'm'> = { hr_aerobic_upper: 'bpm', hr_threshold_lower: 'bpm', speed_aerobic_upper: 'mps', speed_threshold_lower: 'mps', performance_5k: 's', performance_1mile: 's', performance_3min: 'm', performance_20_30min: 'mps' }
export const PROTOCOL_LABELS: Record<AnchorProtocol, string> = { race_5k: '5K race', time_trial_5k: '5K time trial', time_trial_1mile: '1 mile time trial', time_trial_3min: '3 minute time trial', time_trial_20_30min: '20–30 minute time trial', workout_derived: 'Workout-derived', lab_test: 'Lab test', manual: 'Manual entry' }
```

## Implementation procedure
1. Create the six files under frontend/src/api/types with the complete concrete interfaces above. Add `planning_authority: 'legacy'|'calendar'` to the existing Profile interface; it is emitted by TASK003 at GET/profile.data.planning_authority, not on Envelope, and is excluded from PUT/profile. No dependency on068. The only fixtures owned here are frontend/tests/fixtures/planning-wire.json; backend tasks retain their independently owned response tests.
2. In `frontend/src/api.ts`, append (do not reorder existing code):
   - `export * from './api/types/calendar'` and the same for `checkins`, `coach`, `metrics`, `blocks`, `anchors`.
   - If `api.ts` does not already export `type Unit`, add `export type Unit = 'mi' | 'km'`.
   - `export const MISSING = 'missing'`.
   - `fmtDistance(m: number | null | undefined, unit: Unit): string` → `m == null ? MISSING : distance(m, unit)`.
   - `fmtDuration(s: number | null | undefined): string` → `s == null ? MISSING : duration(s)`.
   - `fmtClock(s: number | null | undefined): string` → null → `MISSING`; else round to integer seconds; `< 3600` → `m:ss`; else `h:mm:ss` (`205`→`"3:25"`, `3725`→`"1:02:05"`).
   - `fmtPaceFromSpeed(mps: number | null | undefined, unit: Unit): string` → null or `<= 0` → `MISSING`; else `pace(1000 / mps, unit)`.
   - `fmtPercent(ratio: number | null | undefined): string` → null → `MISSING`; else `` `${Math.round(ratio * 100)}%` ``.
   - `fmtRpe(v: number | null | undefined): string` → null → `MISSING`; else `` `${Number(v.toFixed(1))}/10` ``.
   - `statusText(status: string): string` → `status.replaceAll('_', ' ')` (`not_assessable` → `not assessable`).
   - `clockToSeconds(text: string): number | null` → accepts `m:ss` or `h:mm:ss` (minutes/seconds 0–59 after the first field); returns `null` for anything else.
   - `paceToSpeed(text: string, unit: Unit): number | null` → `s = clockToSeconds(text)`; null or 0 → null; else `(unit === 'mi' ? 1609.344 : 1000) / s`.
   - `sessionTitle(s: { kind: SessionKind; recipe_id: string | null; custom: boolean }): string` → run: `RECIPE_LABELS[recipe_id]` if recipe_id; else `custom ? 'Custom run' : 'Quality slot'`; strength `'Strength'`; cross `'Cross-training'`; rest `'Rest'`.
   - `flattenStructure(items: StructureItem[]): ExpandedStep[]`: ordinary item emits once with step_path `${i}`, repeat_index null; repeat block validates integer count≥2 and plain child steps, then for each repetition j emits children k in order with step_path `${i}.steps.${k}`, repeat_index j. expanded_step is output index+1. Reject nested blocks and expansion beyond100 steps; never mutate input.
   - `formatStep(step: PlannedStep, unit: Unit): string`: label Warm-up/Work/Recovery/Cool-down, then duration or distance, then target. Null target -> "effort"; speed uses high-to-low pace, HR low-to-high bpm, effort cue defaults "effort". Example single work 800m at3.8–4.0 -> "Work 800 m · 6:42 /mi–7:04 /mi". All pages map flattenStructure(structure), never map raw blocks to formatStep.
   - `sessionMarker(s: SessionState, c: Completion | undefined, today: string): SessionMarker` → `c?.status`: `completed_as_planned`→`completed`; `completed_modified`→`modified`; `partial`→`partial`; `moved`→`moved`; `skipped`→`missed`; otherwise (`unknown`, `extra`, undefined): `s.local_date < today` → `not_recorded`, else `planned`.
   - `invalidateKeys(qc: QueryClient, keys: readonly (readonly unknown[])[]): void` → `for (const k of keys) void qc.invalidateQueries({ queryKey: [...k] })` (import `type QueryClient` from `@tanstack/react-query`).
   - `fetchDailyGuidance(): Promise<DailyGuidance | null>` → `(await api<DailyGuidance | null>('/coach/v2/daily')).data`; endpoint ships in TASK-013. Only a successful null means no guidance; HTTP errors remain visible.
   - `pageHref = { home: '#home', calendar: '#calendar', trends: '#trends', settings: '#settings', activity: (id: string) => `#activity/${encodeURIComponent(id)}` } as const`.
   - `qk` exactly (profile is the single unprefixed exception):
```ts
export const qk = {
  calendar: ['v2', 'calendar'] as const,
  calendarView: (version: number | 'head') => ['v2', 'calendar', 'view', version] as const, // GET /calendar (default range) or ?version=N
  calendarVersions: ['v2', 'calendar', 'versions'] as const,                               // GET /calendar/versions?limit=20
  calendarDiff: (from: number, to: number) => ['v2', 'calendar', 'diff', from, to] as const,
  prompts: ['v2', 'prompts'] as const,                                                     // GET /prompts
  checkins: ['v2', 'checkins'] as const,
  metrics: ['v2', 'metrics'] as const,
  metricsWindows: ['v2', 'metrics', 'windows'] as const,                                   // GET /metrics/windows (server today)
  metricsRecovery: (start: string, end: string) => ['v2', 'metrics', 'recovery', start, end] as const,
  activityExecution: (id: string) => ['v2', 'metrics', 'execution', id] as const,          // GET /activities/{id}/execution
  activity: (id: string) => ['v2', 'activity', id] as const,                               // existing GET /activities/{id}
  activitiesNear: (start: string, end: string) => ['v2', 'activities', start, end, 'running', null] as const,
  coach: ['v2', 'coach'] as const,
  coachDaily: ['v2', 'coach', 'daily'] as const,         // cache value is DailyGuidance | null (NOT an envelope)
  goals: ['v2', 'goals'] as const, events: ['v2', 'events'] as const, anchors: ['v2', 'anchors'] as const,
  strengthRoutine: ['v2', 'strength-routine'] as const,
  blocksActive: ['v2', 'blocks', 'active'] as const,
  profile: ['profile'] as const,                   // same key the existing Settings uses
}
```
3. Create `frontend/tests/api-format.test.ts` (this file is owned by this task) with the tests below.

## Tests and expected results
`cd frontend && npx tsc --noEmit && npx vitest run tests/api-format.test.ts` — all pass. Assertions:
- `fmtPaceFromSpeed(800/205,'mi')` → `"6:52 /mi"`; `fmtPaceFromSpeed(0,'km')` → `"missing"`; `fmtPaceFromSpeed(null,'km')` → `"missing"`.
- `fmtClock(205)` → `"3:25"`; `fmtClock(3725)` → `"1:02:05"`; `fmtDuration(null)` → `"missing"`; `fmtPercent(0.756)` → `"76%"`; `fmtRpe(7)` → `"7/10"`; `fmtRpe(6.5)` → `"6.5/10"`.
- `clockToSeconds('6:52')` → `412`; `clockToSeconds('1:02:05')` → `3725`; `clockToSeconds('6:75')` → `null`; `paceToSpeed('8:00','mi')` ≈ `3.3528` (toBeCloseTo 4).
- `sessionTitle({kind:'run',recipe_id:null,custom:false})` → `"Quality slot"`; with `REC002` → `"Long run"`.
- `formatStep` example above → `"Work 800 m · 6:42 /mi–7:04 /mi"`.
- Anchor mappings: performance_3min ->m, performance_20_30min ->mps; DTO fixtures accept values900m and3.2mps respectively; reject the opposite units in backend061 and verify labels in044.
- `sessionMarker`: past session no completion → `not_recorded`; future no completion → `planned`; status `skipped` → `missed`; `completed_modified` → `modified`.
- `fetchDailyGuidance` with200 null resolves null; with404 or500 rejects.
- `qk.calendarView('head')` deep-equals `['v2','calendar','view','head']`.

## Acceptance checklist
- [ ] Six type files exist with exactly the listed exports; none imports from `../../api`.
- [ ] `api.ts` re-exports them and adds the listed helpers, `qk`, `pageHref`; no existing export removed.
- [ ] `npx tsc --noEmit`, `npm run lint`, and `npm test` pass (existing tests unchanged and green).

## Completion report
Changed/created file list; output of the three commands; any blocker.

## Escalation rule
If an exact file/function/contract differs from the pinned source or a requirement is underspecified, STOP and return a short blocker. Do not invent a new schema, behavior, dependency, UX, or alternative implementation.

## Planner-level details I fixed
List wrappers `{items}` (existing API pattern); `RaceEvent` name (avoids DOM `Event`); `CheckinV2` name (v1 `Checkin` type still exists); `qk.coachDaily` caches a bare value; successful null on `/coach/v2/daily` = no guidance; errors remain visible; intensity value carries both modalities with per-modality status; `fmtClock` for laps/reps.


## Wire fixture and conformance tests
Copy the static planning/remaining_mvp/contracts/frontend-wire.json to owned frontend/tests/fixtures/planning-wire.json, then extend only that frontend fixture with named examples: empty CalendarView head/version0,undo null; populated view undo protected ID; rollback WriteResult preserved_session_uids; guidance null and full created_at/input_hash; weekly/alternating routine profile projections; all-known and all-missing volume/SRPE; null metric result versus available numeric zero; nested repeat structure and imported legacy_unstructured. Each object is parsed as unknown then checked by test type guard against concrete fields; no casts hiding missing fields. Backend fixtures are not edited or shared by this task. Test Profile authority is GET data field, excluded from writes; exact qk arrays and profile exception. All pages map flattenStructure, expanded max100, null target safe.
