export interface Profile {
  version: number
  timezone: string
  cycle_anchor: string | null
  anchor_confirmed: boolean
  strength_days_confirmed: boolean
  scheduled_strength_days: number[]
  strength_schedule_mode: 'weekly' | 'alternating'
  strength_week_a_start: string | null
  strength_week_a_days: number[]
  strength_week_b_days: number[]
  mobility_week_a_days: number[]
  mobility_week_b_days: number[]
  mobility_optional_days: number[]
  facts: Record<string, unknown>
  preferences: Record<string, unknown>
  unknowns: string[]
}
