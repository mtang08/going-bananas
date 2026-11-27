import type { components } from '../generated/planning'
export type Profile = components['schemas']['Profile']

export interface RunningRestriction {
  starts_on: string
  ends_on: string | null
  review_on: string | null
  pause_running: boolean
  no_quality: boolean
  max_distance_m: number | null
  max_duration_s: number | null
  source: string
  wording: string | null
}
