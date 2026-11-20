import type { SessionPatchRef } from './exceptions'
import type { PlannedActualValue } from './metrics'
export type SessionKind = 'run' | 'strength' | 'cross' | 'rest' | 'mobility'
export type Certainty = 'committed' | 'provisional'
export type StepType = 'warmup' | 'work' | 'recovery' | 'cooldown'
export interface StepTarget {
  modality: 'speed' | 'hr' | 'effort'
  low: number | null
  high: number | null
  effort_cue: string | null
}
export interface PlannedStep {
  type: StepType
  duration_type: 'time' | 'distance'
  duration_value: number
  target: StepTarget | null
}
export interface RepeatBlock {
  type: 'repeat'
  count: number
  steps: PlannedStep[]
}
export type StructureItem = PlannedStep | RepeatBlock
export interface ExpandedStep extends PlannedStep {
  step_path: string
  expanded_step: number
  repeat_index: number | null
}
export interface SessionFields {
  local_date: string
  slot: number
  kind: SessionKind
  recipe_id: string | null
  custom: boolean
  intent: string
  placeholder: boolean
  locked: boolean
  planned_duration_s: number | null
  planned_distance_m: number | null
  structure: StructureItem[] | null
  strength_slot_id: string | null
  notes: string | null
}
export interface SessionState extends SessionFields {
  id: string
  certainty: Certainty
  legacy_unstructured: boolean
  legacy_payload: Record<string, unknown> | null
  session_uid: string
  revision: number
  calendar_version_number: number
  deleted: boolean
  is_original: boolean
  changed_by_version: number
  exception_patch: SessionPatchRef | null
}
export type CompletionStatus =
  | 'completed_as_planned'
  | 'completed_modified'
  | 'partial'
  | 'moved'
  | 'skipped'
  | 'extra'
  | 'unknown'
export type MatchMethod = 'explicit' | 'auto_same_day' | 'confirmed_move' | 'user_marked' | 'none'
export type ModificationReason =
  'symptom_onset' | 'fatigue' | 'illness' | 'schedule' | 'weather' | 'equipment' | 'other'
export interface Completion {
  id: string
  input_version: number
  session_uid: string
  activity_id: string | null
  strong_workout_id: string | null
  manual_session_id: string | null
  status: CompletionStatus
  distance_m?: number | null
  timer_s?: number | null
  match_method: MatchMethod
  modification_reason: ModificationReason | null
  reason_note: string | null
  version: number
  updated_at: string
  local_date: string | null
} // local_date [DTO fixed here]: actual subject date when linked, else planned date
export interface RecordedRun {
  activity_id: string
  local_date: string
  distance_m: number | null
  timer_s: number | null
}
export interface CalendarView {
  today: string
  timezone: string
  start: string
  end: string
  version: number
  head: number
  undo: { target_version: number; eligible: boolean; protected_session_uids: string[] } | null
  last_planned_date: string | null
  sessions: SessionState[]
  completions: Completion[]
  recorded_runs: RecordedRun[]
} // today/timezone/start/end [DTO fixed here]; head 0 = no calendar yet
export interface WeeklyProjection {
  week_start: string
  week_end: string
  today: string
  timezone: string
  calendar_version: number
  actual_distance_m: number
  remaining_distance_m: number
  projected_distance_m: number
  actual_runs: number
  remaining_runs: number
  estimated_runs: number
  missing_actual_runs: number
  missing_planned_runs: number
  unrecorded_past_runs: number
  pace_sample_count: number
  pace_mps: number | null
  plan_available: boolean
  plan_through: string | null
  activity_coverage_complete: boolean
}
export type CalendarVersionKind =
  'bootstrap' | 'manual_edit' | 'proposal_accept' | 'rollback' | 'legacy_import'
export interface CalendarVersion {
  id: string
  number: number
  parent_number: number | null
  kind: CalendarVersionKind
  actor: 'system' | 'user' | 'coach'
  reason: string | null
  proposal_id: string | null
  restored_from_number: number | null
  block_version_id: string | null
  created_at: string
}
export type ChangeOp = 'add' | 'modify' | 'move' | 'delete'
export interface CalendarDiff {
  changes: {
    session_uid: string
    op: ChangeOp
    before: Partial<SessionFields> | null
    after: Partial<SessionFields> | null
  }[]
}
export interface CalendarEdit {
  op: ChangeOp
  session_uid?: string
  fields: Partial<SessionFields>
}
export interface CalendarEditsRequest {
  expected_head: number
  edits: CalendarEdit[]
  reason?: string
}
export interface CalendarRollbackRequest {
  expected_head: number
  to_version: number
  reason?: string
}
export interface CalendarWriteResult {
  version: number
  kind: CalendarVersionKind
  stale_proposals: string[]
  preserved_session_uids: string[]
}
export interface CompletionPut {
  expected_version?: number
  activity_id?: string | null
  strong_workout_id?: string | null
  manual_session_id?: string | null
  status?: 'skipped' | 'unknown' | 'completed_as_planned'
  modification_reason?: ModificationReason | null
  reason_note?: string | null
}
export const RECIPE_LABELS: Record<string, string> = {
  REC001: 'Easy run',
  REC002: 'Long run',
  REC003: 'Threshold intervals',
  REC004: 'Steady / tempo',
  REC005: 'VO2 intervals',
  REC006: 'Short intervals / fartlek',
  REC007: 'Strides',
  REC008: 'Hills',
  REC009: 'Benchmark / race-specific',
  REC010: 'Low-impact substitution',
}
export type SessionMarker =
  | 'planned'
  | 'completed'
  | 'modified'
  | 'partial'
  | 'moved'
  | 'missed'
  | 'recorded'
  | 'not_recorded'
export const MARKER_LABELS: Record<SessionMarker, string> = {
  planned: 'Planned',
  completed: 'Completed',
  modified: 'Completed, modified',
  partial: 'Partial',
  moved: 'Moved',
  missed: 'Missed',
  recorded: 'Recorded · comparison unavailable',
  not_recorded: 'Not recorded',
}

export type DigestOutcome = SessionMarker
export type DigestSubject = 'activity' | 'strong_workout' | 'manual_session'
export interface DigestCounts {
  planned: number
  planned_to_date: number
  done: number
}
export interface DigestExecution {
  assessment_status: 'available' | 'partial' | 'missing' | null
  reason_codes: string[]
  quality_flags: string[]
  components: PlannedActualValue['components']
  reps_planned: number | null
  reps_completed: number | null
}
export interface DigestRow {
  session_uid: string
  local_date: string
  slot: number
  kind: SessionKind
  class: string
  recipe_id: string | null
  custom: boolean
  intent: string | null
  key: boolean
  changed: boolean
  outcome: DigestOutcome
  modification_reason: ModificationReason | null
  planned_duration_s: number | null
  planned_distance_m: number | null
  planned_distance_estimated: boolean
  actual: {
    subject: DigestSubject
    id: string
    local_date: string
    duration_s: number | null
    distance_m: number | null
    sport: string | null
    avg_hr_bpm: number | null
    moving_pace_s_per_km: number | null
    rpe: number | null
    rpe_source: 'manual' | 'garmin_fit' | null
  } | null
  execution: DigestExecution | null
}
export interface DigestUnplanned {
  subject: DigestSubject
  id: string
  local_date: string
  kind: string
  duration_s: number | null
  distance_m: number | null
}
export interface WeeklyDigest {
  schema: 'weekly_digest.v1'
  week_start: string
  week_end: string
  today: string
  days_elapsed: number
  timezone: string
  calendar_version: number
  plan_available: boolean
  activity_coverage_complete: boolean
  totals: {
    sessions: DigestCounts & {
      by_outcome: Record<DigestOutcome, number>
      removed: number
      unplanned: number
    }
    by_kind: Record<'run' | 'strength' | 'cross' | 'mobility', DigestCounts>
    time: {
      planned_s: number
      planned_to_date_s: number
      planned_unknown: number
      actual_s: number
      actual_unknown: number
      unplanned_s: number
    }
    run_distance: {
      planned_m: number
      planned_to_date_m: number
      planned_estimated: number
      planned_unknown: number
      actual_m: number
      actual_unknown: number
    }
    key_sessions: DigestCounts & { by_outcome: Record<DigestOutcome, number> }
  }
  sessions: DigestRow[]
  unplanned: DigestUnplanned[]
  removed: { session_uid: string; local_date: string; kind: SessionKind }[]
}
