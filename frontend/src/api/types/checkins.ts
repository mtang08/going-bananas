import type { components as Feedback } from '../generated/feedback'
import type { components } from '../generated/checkins'

type Schemas = components['schemas']

export type CheckinKind = Schemas['CheckinKind']
export type Illness = NonNullable<Schemas['CheckinView']['illness']>
export type GaitChange = NonNullable<Schemas['CheckinView']['gait_change']>
export type ContextTag = Schemas['CheckinContextTag']
export type SymptomInput = Schemas['CheckinSymptomInput']
export type Side = SymptomInput['side']
export type SymptomTiming = SymptomInput['timing']
export type CheckinCreate = Schemas['CheckinCreate']
export type DetectedCheckin = Schemas['DetectedCheckin']
export type CheckinExceptions = Schemas['CheckinDetection']

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
