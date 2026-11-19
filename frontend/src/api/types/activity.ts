export interface RunClassification {
  method: string
  suggested_label: 'easy' | 'quality' | 'long' | 'other' | null
  effective_label: 'easy' | 'quality' | 'long' | 'other' | 'unknown'
  label_source: 'manual' | 'source' | 'heuristic' | 'unknown'
  confidence: 'confirmed' | 'medium' | 'low' | 'insufficient'
  reasons: string[]
  metrics?: Record<string, number | string | null>
}
export interface Activity {
  id: string
  start_at: string
  local_date: string
  sport: string
  subtype?: string | null
  distance_m: number | null
  elapsed_s: number | null
  moving_s: number | null
  moving_pace_s_per_km: number | null
  workout_label?: string | null
  classification?: RunClassification
  resolution_state?: string
  source?: string | null
  provenance?: Record<string, unknown>
  annotations?: {
    version: number
    workout_label?: string | null
    notes?: string | null
    excluded?: boolean
  }
  sources?: unknown[]
}
