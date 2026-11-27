import type { components } from '../generated/backend'
import type { WorkoutFeedback } from './checkins'
import type { components as CalendarComponents } from '../generated/calendar'
import type { components as CompletionComponents } from '../generated/completion'
import type { PlannedActualValue } from './metrics'
type CalendarSchemas = CalendarComponents['schemas']
export type SessionKind = SessionFields['kind']
export type Certainty = SessionState['certainty']
export type StepType = PlannedStep['type']
export type StepTarget = NonNullable<CalendarSchemas['StepTarget']>
export type PlannedStep = CalendarSchemas['PlannedStep']
export type RepeatBlock = CalendarSchemas['RepeatBlock']
export type StructureItem = CalendarSchemas['StructureItem']
export interface ExpandedStep extends PlannedStep {
  step_path: string
  expanded_step: number
  repeat_index: number | null
}
export type Effort = CalendarSchemas['Effort']
export type SessionBrief = NonNullable<CalendarSchemas['SessionBrief']>
export type SessionFields = CalendarSchemas['SessionFields']
export type SessionState = CalendarSchemas['SessionState']
export type Completion = CompletionComponents['schemas']['Completion'] &
  Pick<CalendarSchemas['CalendarCompletion'], 'distance_m' | 'timer_s'>
export type CompletionStatus = Completion['status']
export type MatchMethod = Completion['match_method']
export type ModificationReason = NonNullable<Completion['modification_reason']>
export type RecordedRun = CalendarSchemas['RecordedRun']
export type CalendarView = CalendarSchemas['CalendarView']
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
export type CalendarVersion = components['schemas']['CalendarVersion']
export type CalendarVersionKind = CalendarVersion['kind']
export type CalendarDiff = CalendarSchemas['CalendarDiff']
export type ChangeOp = CalendarDiff['changes'][number]['op']
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
export type CompletionPut = CompletionComponents['schemas']['CompletionInput']
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
export interface ReviewFollowUp {
  proposal_id: string
  session_uid: string
  op: 'add' | 'move' | 'modify'
  reason: string
  accepted: {
    local_date: string
    intent: string
    duration_s: number | null
    distance_m: number | null
    effort: Effort | null
  }
  edited_since: boolean
  modification_reason: ModificationReason | null
  outcome: DigestOutcome
  actual: Pick<
    NonNullable<DigestRow['actual']>,
    'id' | 'subject' | 'local_date' | 'duration_s' | 'distance_m' | 'rpe'
  > | null
  response: Pick<
    WorkoutFeedback,
    'observed_at' | 'hours_after_end' | 'pain_reported' | 'gait_change' | 'symptoms'
  > | null
  next_check: { on: string; check: string } | null
}
export interface WeeklyDigest {
  decision_follow_up: ReviewFollowUp | null
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
    by_kind: Record<'run' | 'strength' | 'cross' | 'mobility' | 'rehab', DigestCounts>
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
