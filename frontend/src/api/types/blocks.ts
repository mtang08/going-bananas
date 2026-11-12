export type GoalHorizon = '3_6_months' | 'season' | 'long_term'
export interface Goal { id: string; text: string; horizon: GoalHorizon; priority: number; status: 'active' | 'paused' | 'done' | 'dropped'; version: number }
export type GoalCreate = Omit<Goal, 'id' | 'version' | 'status'>
export type GoalPatch = Partial<GoalCreate> & { expected_version: number; status?: Goal['status'] }
export type EventPriority = 'target' | 'supported_exposure' | 'benchmark' | 'optional'
export type EventStatus = 'planned' | 'registered' | 'completed' | 'cancelled'
export interface RaceEvent { id: string; name: string; event_date: string; distance_m: number | null; priority: EventPriority; status: EventStatus; result_s: number | null; version: number }
export type RaceEventCreate = Omit<RaceEvent, 'id' | 'version'>
export type RaceEventPatch = Partial<RaceEventCreate> & { expected_version: number }
export interface StrengthRoutineSlot { id: string | null; label: string; default_weekday: number; lower_body_cost: 'low' | 'moderate' | 'high'; typical_duration_s: number | null; main_lower_body_lifts: string[]; active: boolean; version: number }
export interface ConfirmedSchedule { strength_days_confirmed:boolean;strength_schedule_mode:'weekly'|'alternating';scheduled_strength_days:number[];strength_week_a_start:string|null;strength_week_a_days:number[];strength_week_b_days:number[];mobility_week_a_days:number[];mobility_week_b_days:number[];mobility_optional_days:number[] }
export interface StrengthRoutine { version: number; slots: StrengthRoutineSlot[]; suggested: boolean; schedule: ConfirmedSchedule } // [DTO fixed here] version 0 + suggested=true: nothing saved, slots pre-filled from Strong (D13)
export interface StrengthRoutinePut { expected_version: number; slots: Omit<StrengthRoutineSlot, 'id' | 'version'>[] }
export interface BlockVersion { id: string; block_uid: string; version: number; status: 'draft' | 'active' | 'consolidating' | 'completed' | 'replaced' | 'ended'; objective: string; rationale: string; maintained_qualities: string[]; non_goals: string[]; eligible_recipe_ids: string[]; progression_dimension: string; constraints: {kind: string; text: string}[]; start_date: string; review_date: string; completion_indicators: string[]; early_review_triggers: string[]; objective_status: string; created_at: string; proposal_id: string | null }
export const HORIZON_LABELS: Record<GoalHorizon, string> = { '3_6_months': '3–6 months', season: 'Season', long_term: 'Long term' }
export const EVENT_PRIORITY_LABELS: Record<EventPriority, string> = { target: 'Target', supported_exposure: 'Supported exposure', benchmark: 'Benchmark', optional: 'Optional' }
export const WEEKDAY_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'] as const // index 0 = Monday
