import type { components as Backend } from '../generated/backend'
import type { components } from '../generated/planning'
export type Goal = Backend['schemas']['Goal']
export type GoalCreate = Backend['schemas']['GoalCreate']
export type GoalHorizon = Goal['horizon']
export type EventPurpose = RaceEvent['purpose']
export type EventStatus = RaceEvent['status']
export type RaceEventCreate = components['schemas']['EventInput']
export type TargetEventStatus = ActiveBlock['target_event_status']
export type IndicatorSource = Indicator['source']
export type RaceEvent = components['schemas']['RaceEvent']
export type OutlineStep = components['schemas']['OutlineStep']
export type TargetEvent = components['schemas']['TargetEvent']
export type EventBlock = components['schemas']['EventBlock']
export type StrengthRoutineSlot = components['schemas']['StrengthRoutineSlot']
export type ConfirmedSchedule = components['schemas']['ConfirmedSchedule']
export type StrengthRoutine = components['schemas']['StrengthRoutine']
export type Indicator = components['schemas']['Indicator']
export type BlockVersion = components['schemas']['BlockVersion']
export type ActiveBlock = components['schemas']['ActiveBlock']
export type BlockBenchmark = components['schemas']['BlockBenchmark']
export type BenchmarkStatus = components['schemas']['BenchmarkStatus']
export type BenchmarkRecord = components['schemas']['BenchmarkRecord']

export const HORIZON_LABELS: Record<GoalHorizon, string> = {
  '3_6_months': '3–6 months',
  season: 'Season',
  long_term: 'Long term',
}
export const EVENT_PURPOSE_LABELS: Record<EventPurpose, string> = {
  pr: 'Race it (PR attempt)',
  benchmark: 'Benchmark effort',
  training: 'Training run',
}
export const WEEKDAY_LABELS = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
] as const // index 0 = Monday

export const RUN_SPORTS: readonly string[] = ['running', 'trail_running', 'treadmill_running'] // mirrors backend RUN_SPORTS
