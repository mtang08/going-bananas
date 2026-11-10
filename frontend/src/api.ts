export type Mode = 'demo' | 'real' | 'test'
export interface Envelope<T> { schema_version: string; data_revision: number; mode: Mode; data: T }
export interface Coverage { dataset: string; status: string; start_date?: string | null; end_date?: string | null; completed_at?: string | null; reason?: string | null; last_success?: string | null; latest_observation?: string | null; fully_enumerated?: boolean | null }
export interface Activity { id: string; start_at: string; local_date: string; sport: string; subtype?: string | null; distance_m: number | null; elapsed_s: number | null; moving_s: number | null; moving_pace_s_per_km: number | null; workout_label?: string | null; resolution_state?: string; source?: string | null; provenance?: Record<string, unknown>; annotations?: { version: number; workout_label?: string | null; notes?: string | null; excluded?: boolean }; sources?: unknown[] }
export interface SummaryTotal { distance_m: number; run_count: number; missing_distance_count: number }
export interface StrengthCoverage { source: string; status: string; reason: string; complete: boolean; observed_manual_count: number; observed_imported_count: number }
export interface Summary { as_of: string; timezone: string; metric_version: string; window: { start_date: string; end_date: string }; current_week: SummaryTotal; rolling_7: SummaryTotal; rolling_14: SummaryTotal; selected: SummaryTotal & { longest_elapsed_s: number | null; strength_count: number; strength_duration_s: number; strength_unknown_duration_count: number; low_impact_count: number; low_impact_duration_s: number; workout_distribution: Record<string, number> }; weekly: { start_date: string; end_date: string; distance_m: number; run_count: number; missing_distance_count: number; strength_count: number }[]; recent_runs: Activity[]; coverage: Coverage[]; strength_coverage?: StrengthCoverage }
export interface RecoveryPoint { date: string; value: number; unit: string; statistic: string }
export interface Recovery { timezone: string; series: Record<'sleep' | 'hrv' | 'resting_hr', RecoveryPoint[]>; trailing_7: Record<'sleep' | 'hrv' | 'resting_hr', { mean: number | null; n: number; days: number }>; coverage: Coverage[] }
export interface Checkin { id: string; version: number; observed_at: string; recorded_at: string; symptoms: 'none' | 'mild' | 'moderate' | 'severe'; change: string | null; gait: string; feeling: string; effort: number | null; activity_id: string | null; note: string | null; associations: { activity_id: string; kind: string; elapsed_hours: number | null; timing_uncertain: boolean; day_label: string }[] }
export interface Profile { version: number; timezone: string; cycle_anchor: string | null; anchor_confirmed: boolean; strength_days_confirmed: boolean; scheduled_strength_days: number[]; facts: Record<string, unknown>; preferences: Record<string, unknown>; unknowns: string[] }
export interface ManualSession { id: string; version: number; date: string; time: string | null; kind: string; duration_s: number | null; effort: number | null; note: string | null; linked_activity_id: string | null }
export interface PlanSession { id: string; date: string; kind: string; target?: string | null; completion_link_id?: string | null; completion_activity_id?: string | null; completion_manual_session_id?: string | null }
export interface Plan { id: string; version: number; status: string; start_date: string; end_date: string; profile_version: number; sessions: PlanSession[] }
export interface Plans { items: Plan[]; opportunities: { date: string; fortnight_index: number; slot: number }[]; unscheduled: boolean }
export interface SyncDataset { dataset: string; status?: string; last_attempt_at?: string | null; last_success_at?: string | null; newest_observation_at?: string | null; requested_start?: string | null; requested_end?: string | null; fully_enumerated?: boolean | null; reason?: string | null }
export interface SyncJob { id: string; dataset: string; status: 'queued' | 'running' | 'retry_wait' | 'succeeded' | 'failed'; error_code?: string | null }
export interface SyncStatus { datasets?: SyncDataset[]; active_jobs?: SyncJob[] }
export interface Conflict { id: string; kind: string; status: string; activity_ids: string[]; manual_session_id: string | null; details: Record<string, unknown> }
export interface ImportRecord { id: string; source_kind: string; status: string; started_at: string; finished_at?: string | null; adapter_version?: string | null; counters?: { activities?: ImportCount; recovery?: Partial<Record<'sleep' | 'hrv' | 'resting_hr', ImportCount>>; datasets?: Record<string, {first_date?: string; last_date?: string; count?: number; fully_enumerated?: boolean}>; preserved_only?: Record<string, number>; [key: string]: unknown } }
export interface ImportCount { seen?: number; new_revisions?: number; changed?: number; rejected?: number }

export function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  return date.getUTCFullYear() === year && date.getUTCMonth() + 1 === month && date.getUTCDate() === day
}
export function windowDays(start: string, end: string): number {
  return Math.round((Date.parse(`${end}T12:00:00Z`) - Date.parse(`${start}T12:00:00Z`)) / 86400000) + 1
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public retryable = false) { super(message) }
}

const BASE = '/api/v1'
export async function api<T>(path: string, options: RequestInit = {}): Promise<Envelope<T>> {
  const headers = new Headers(options.headers)
  if (options.body) headers.set('Content-Type', 'application/json')
  if (options.method && options.method !== 'GET') headers.set('X-Local-Request', '1')
  let response: Response
  try { response = await fetch(`${BASE}${path}`, { ...options, headers, credentials: 'same-origin' }) }
  catch { throw new ApiError(0, 'disconnected', 'Cannot reach the local server. Check that the app is running.', true) }
  let body: unknown
  try { body = await response.json() } catch { throw new ApiError(response.status, 'invalid_response', 'The server returned an unreadable response.') }
  if (!response.ok) {
    const problem = (body as { error?: { code?: string; message?: string; retryable?: boolean } }).error
    throw new ApiError(response.status, problem?.code || 'request_failed', problem?.message || 'The request failed.', problem?.retryable)
  }
  if (!body || typeof body !== 'object' || !('data' in body)) throw new ApiError(response.status, 'invalid_response', 'The server response is missing data.')
  return body as Envelope<T>
}

export const query = (params: Record<string, string | number | undefined | null>) => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  return search.toString() ? `?${search}` : ''
}

export const post = <T>(path: string, data: unknown) => api<T>(path, { method: 'POST', body: JSON.stringify(data) })
export const put = <T>(path: string, data: unknown) => api<T>(path, { method: 'PUT', body: JSON.stringify(data) })
export const patch = <T>(path: string, data: unknown) => api<T>(path, { method: 'PATCH', body: JSON.stringify(data) })

export function localDate(d = new Date()): string {
  const y = d.getFullYear(), m = `${d.getMonth() + 1}`.padStart(2, '0'), day = `${d.getDate()}`.padStart(2, '0')
  return `${y}-${m}-${day}`
}
export function addDays(date: string, amount: number): string {
  const d = new Date(`${date}T12:00:00`)
  d.setDate(d.getDate() + amount)
  return localDate(d)
}
export function dateLabel(date: string, options: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }): string {
  return new Intl.DateTimeFormat('en-US', options).format(new Date(`${date}T12:00:00`))
}
export function distance(m: number | null | undefined, unit: 'mi' | 'km', digits = 1): string {
  return m == null ? '—' : `${(m / (unit === 'mi' ? 1609.344 : 1000)).toFixed(digits)} ${unit}`
}
export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60)
  return h ? `${h}h ${`${m}`.padStart(2, '0')}m` : `${m}m`
}
export function pace(secondsPerKm: number | null | undefined, unit: 'mi' | 'km'): string {
  if (secondsPerKm == null) return '—'
  const seconds = Math.round(secondsPerKm * (unit === 'mi' ? 1.609344 : 1))
  return `${Math.floor(seconds / 60)}:${`${seconds % 60}`.padStart(2, '0')} /${unit}`
}
