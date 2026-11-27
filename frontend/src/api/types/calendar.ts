import type { components } from '../generated/backend'
import type { components as CalendarComponents } from '../generated/calendar'
import type { components as CompletionComponents } from '../generated/completion'
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
export type WeeklyProjection = CalendarSchemas['WeeklyProjection']
export type CalendarVersion = components['schemas']['CalendarVersion']
export type CalendarVersionKind = CalendarVersion['kind']
export type CalendarDiff = CalendarSchemas['CalendarDiff']
export type ChangeOp = CalendarDiff['changes'][number]['op']
export type CalendarEdit = CalendarSchemas['CalendarEdit']
export type CalendarEditsRequest = CalendarSchemas['CalendarEditsRequest']
export type CalendarRollbackRequest = CalendarSchemas['CalendarRollbackRequest']
export type CalendarWriteResult = CalendarSchemas['CalendarWriteResult']
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
export type SessionMarker = CalendarSchemas['DigestRow']['outcome']
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
export type DigestSubject = NonNullable<CalendarSchemas['DigestActual']>['subject']
export type DigestCounts = CalendarSchemas['DigestCounts']
export type DigestExecution = NonNullable<CalendarSchemas['DigestExecution']>
export type DigestRow = CalendarSchemas['DigestRow']
export type DigestUnplanned = CalendarSchemas['DigestUnplanned']
export type ReviewFollowUp = NonNullable<CalendarSchemas['ReviewFollowUp']>
export type WeeklyDigest = CalendarSchemas['WeeklyDigest']
