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
