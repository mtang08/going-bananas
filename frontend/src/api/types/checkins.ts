import type { components as Feedback } from '../generated/feedback'
import type { CheckinExceptions } from './exceptions'
export type CheckinKind = 'exception' | 'post_run' | 'delayed_followup'
export type Illness = 'none' | 'possible' | 'present'
export type GaitChange = 'yes' | 'no' | 'unsure'
export type ContextTag = 'heat' | 'travel' | 'poor_sleep' | 'unusual_surface' | 'equipment'
export type Side = 'left' | 'right' | 'both' | 'na'
export type SymptomTiming =
  'during' | 'immediately_after' | 'next_morning' | 'hours_24_48' | 'later' | 'unknown'
export interface SymptomInput {
  site: string
  side: Side
  severity: number
  timing: SymptomTiming
}
export interface SymptomReport extends SymptomInput {
  id: string
}
export interface CheckinCreate {
  kind: CheckinKind
  observed_at: string
  pain_reported?: boolean | null
  fatigue?: number | null
  illness?: Illness | null
  gait_change?: GaitChange | null
  context_tags: ContextTag[]
  symptoms: SymptomInput[]
  activity_id?: string | null
  prompt_id?: string | null
  note?: string | null
  idempotency_key: string
}
export interface CheckinV2 {
  id: string
  version: number
  kind: CheckinKind
  observed_at: string
  recorded_at: string
  pain_reported: boolean | null
  fatigue: number | null
  illness: Illness | null
  gait_change: GaitChange | null
  context_tags: ContextTag[]
  symptoms: SymptomReport[]
  activity_id: string | null
  prompt_id: string | null
  note: string | null
  schema_version: number
  exceptions?: CheckinExceptions
}
export type Prompt = Feedback['schemas']['Prompt']
export type PromptKind = Prompt['kind']
export interface WorkoutFeedback {
  prompt: (Omit<Prompt, 'status'> & { status: Prompt['status'] | 'scheduled' }) | null
  checkin_id: string | null
  observed_at: string | null
  recorded_at: string | null
  hours_after_end: number | null
  pain_reported: boolean | null
  gait_change: GaitChange | null
  symptoms: SymptomInput[]
}
export type PromptList = Feedback['schemas']['Prompts']
export type RpeResult = Feedback['schemas']['ManualRPE']
export interface CheckinRequest {
  kind: CheckinKind
  prompt: Prompt | null
  activityId: string | null
} // UI-only: what opens the check-in modal
export const TIMING_LABELS: Record<SymptomTiming, string> = {
  during: 'During the run',
  immediately_after: 'Immediately after',
  next_morning: 'Next morning',
  hours_24_48: '24–48 hours after',
  later: 'Later',
  unknown: 'Not sure',
}
export const SIDE_LABELS: Record<Side, string> = {
  left: 'Left',
  right: 'Right',
  both: 'Both',
  na: 'Not applicable',
}
export const REASON_LABELS: Record<
  'symptom_onset' | 'fatigue' | 'illness' | 'schedule' | 'weather' | 'equipment' | 'other',
  string
> = {
  symptom_onset: 'Symptoms started',
  fatigue: 'Fatigue',
  illness: 'Illness',
  schedule: 'Schedule',
  weather: 'Weather',
  equipment: 'Equipment',
  other: 'Other',
}
