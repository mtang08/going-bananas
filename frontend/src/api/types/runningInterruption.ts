export interface RunningInterruption {
  reason: 'schedule' | 'travel' | 'illness' | 'other'
  starts_on: string
  return_on: string | null
  review_on: string | null
}

export interface InterruptionRun {
  session_uid: string
  local_date: string
  intent: string
  recipe_id: string | null
  planned_duration_s: number | null
  planned_distance_m: number | null
}

export interface RunningInterruptionView {
  today: string
  profile_version: number
  interruption: RunningInterruption | null
  phase: 'planned' | 'paused' | 'review_due' | 'returning' | null
  affected_runs: InterruptionRun[]
  affected_runs_omitted: number
  first_run: InterruptionRun | null
  recorded_return: { activity_id: string; local_date: string } | null
  review_reason: string | null
}
