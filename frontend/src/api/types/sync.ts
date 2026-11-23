export interface SyncDataset {
  dataset: string
  status: string
  last_attempt_at: string | null
  last_success_at: string | null
  newest_observation_at: string | null
  requested_start: string | null
  requested_end: string | null
  fully_enumerated: boolean | null
  reason: string | null
}
export interface SyncJob {
  id: string
  dataset: string
  status: 'queued' | 'running' | 'retry_wait' | 'complete' | 'partial' | 'failed'
  next_attempt_at: string | null
  error_code: string | null
}
export interface SyncStatus {
  datasets: SyncDataset[]
  active_jobs: SyncJob[]
  pending_treadmill_runs: PendingTreadmillRun[]
}

export interface PendingTreadmillRun {
  id: string
  local_date: string
}

export interface TreadmillReview extends PendingTreadmillRun {
  preview_token: string
  title: string | null
  distance_m: number | null
  timer_s: number | null
  intervals: {
    lap_index: number
    timer_s: number | null
    intensity: string | null
    recorded_pace_seconds_per_mile: number | null
  }[]
}
