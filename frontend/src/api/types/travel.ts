export type EventCategory =
  | 'flight'
  | 'lodging'
  | 'ground_travel'
  | 'reservation'
  | 'out_of_office'
  | 'appointment'
  | 'work'
  | 'social'
  | 'other'
export const CATEGORY_LABELS: Record<EventCategory, string> = {
  flight: 'Flight',
  lodging: 'Lodging',
  ground_travel: 'Train/bus/car',
  reservation: 'Reservation',
  out_of_office: 'Out of office',
  appointment: 'Appointment',
  work: 'Work',
  social: 'Social',
  other: 'Other',
}
export type TripStatus = 'pending' | 'confirmed' | 'dismissed' | 'needs_review'
export type TripSource = 'detected' | 'manual'
export type TripConfidence = 'high' | 'medium' | 'low'
export type RunningAccess = 'normal' | 'limited' | 'none'
export type GymAccess = 'full' | 'limited' | 'none'
export type DayAvailability = 'normal' | 'reduced' | 'unavailable'
export const RUNNING_ACCESS_LABELS: Record<RunningAccess, string> = {
  normal: 'Normal',
  limited: 'Limited',
  none: 'None',
}
export const GYM_ACCESS_LABELS: Record<GymAccess, string> = {
  full: 'Full gym',
  limited: 'Limited equipment',
  none: 'No gym',
}
export const DAY_AVAILABILITY_LABELS: Record<DayAvailability, string> = {
  normal: 'Normal',
  reduced: 'Shorter or alternative',
  unavailable: 'Unavailable',
}
export interface DayAvailabilityEntry {
  date: string
  availability: DayAvailability
}
export interface ManualTripInput {
  start_date: string
  end_date: string
  destination_tz: string
  destination_label?: string | null
  running_access?: RunningAccess | null
  gym_access?: GymAccess | null
  day_availability?: DayAvailabilityEntry[]
}
export interface GcalStatus {
  connected: boolean
  window: { days_back: number; days_ahead: number }
  last_sync: null | {
    started_at: string
    finished_at: string | null
    status: 'complete' | 'failed'
    error_code: string | null
    counters: Record<string, number>
  }
  last_success_at: string | null
}
export interface GcalTripCounters {
  created: number
  updated: number
  flagged: number
  deleted: number
}
export interface GcalSyncResult {
  sync: {
    started_at: string
    finished_at: string
    window: { start: string; end: string }
    counters: {
      fetched: number
      created: number
      changed: number
      unchanged: number
      removed: number
      restored: number
    }
  }
  trips: GcalTripCounters
}
export interface CalendarEvent {
  id: string
  event_type: string
  summary: string | null
  all_day: boolean
  start_at: string | null
  end_at: string | null
  start_date: string | null
  end_date: string | null
  start_tz: string | null
  end_tz: string | null
  local_date: string
  busy: boolean
  response_status: string | null
  category: EventCategory
  category_source: 'auto' | 'athlete'
  auto_category: EventCategory
  flight_code: string | null
  destination_label: string | null
  location_codes: string[]
  removed: boolean
  trip_id: string | null
  version: number
}
export interface EventPatchResult {
  event: CalendarEvent
  trips: GcalTripCounters
}
export type LegTimezoneBasis = 'calendar_endpoints' | 'calendar_display' | 'fallback'

export interface TripLeg {
  event_id: string
  seq: number
  summary: string | null
  flight_code: string | null
  depart_at: string | null
  arrive_at: string | null
  depart_tz: string
  arrive_tz: string
  depart_local: string | null
  arrive_local: string | null
  timezone_basis: LegTimezoneBasis
  removed: boolean
}
export interface DetectedTrip {
  start_date: string
  end_date: string | null
  destination_label: string | null
  destination_tz: string
  confidence: TripConfidence
  stops: { label: string | null; tz: string; arrive_date: string }[]
}
export interface Trip {
  id: string
  status: TripStatus
  start_date: string
  end_date: string | null
  destination_label: string | null
  destination_tz: string
  source: TripSource
  confidence: TripConfidence | null
  edited: boolean
  review_reason: 'source_changed' | 'source_removed' | null
  detected: Partial<DetectedTrip>
  running_access: RunningAccess | null
  gym_access: GymAccess | null
  day_availability: DayAvailabilityEntry[]
  travel_days: string[]
  legs: TripLeg[]
  version: number
}
export interface TripPatch {
  expected_version: number
  status?: 'confirmed' | 'dismissed' | 'pending'
  accept_detected?: boolean
  start_date?: string
  end_date?: string | null
  destination_label?: string | null
  destination_tz?: string
  running_access?: RunningAccess | null
  gym_access?: GymAccess | null
  day_availability?: DayAvailabilityEntry[]
}
