import type { QueryClient } from '@tanstack/react-query'
import { RECIPE_LABELS } from './api/types/calendar'
import type {
  Completion,
  ExpandedStep,
  PlannedStep,
  SessionKind,
  SessionMarker,
  SessionState,
  StructureItem,
} from './api/types/calendar'
export type Mode = 'demo' | 'real' | 'test'
export interface Envelope<T> {
  schema_version: string
  data_revision: number
  mode: Mode
  data: T
}
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
export interface SyncDataset {
  dataset: string
  status?: string
  last_attempt_at?: string | null
  last_success_at?: string | null
  newest_observation_at?: string | null
  requested_start?: string | null
  requested_end?: string | null
  fully_enumerated?: boolean | null
  reason?: string | null
}
export interface SyncJob {
  id: string
  dataset: string
  status: 'queued' | 'running' | 'retry_wait' | 'succeeded' | 'failed'
  error_code?: string | null
}
export interface SyncStatus {
  datasets?: SyncDataset[]
  active_jobs?: SyncJob[]
}

export function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  return (
    date.getUTCFullYear() === year && date.getUTCMonth() + 1 === month && date.getUTCDate() === day
  )
}

export interface ApiFieldError {
  code?: string
  path?: string
  field?: string
  message: string
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public retryable = false,
    public fields: ApiFieldError[] = [],
  ) {
    super(message)
  }
}

const BASE = '/api/v1'
export async function api<T>(path: string, options: RequestInit = {}): Promise<Envelope<T>> {
  const headers = new Headers(options.headers)
  if (options.body) headers.set('Content-Type', 'application/json')
  if (options.method && options.method !== 'GET') headers.set('X-Local-Request', '1')
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, { ...options, headers, credentials: 'same-origin' })
  } catch {
    throw new ApiError(
      0,
      'disconnected',
      'Cannot reach the local server. Check that the app is running.',
      true,
    )
  }
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ApiError(
      response.status,
      'invalid_response',
      'The server returned an unreadable response.',
    )
  }
  if (!response.ok) {
    const problem = (
      body as {
        error?: { code?: string; message?: string; retryable?: boolean; fields?: ApiFieldError[] }
      }
    ).error
    throw new ApiError(
      response.status,
      problem?.code || 'request_failed',
      problem?.message || 'The request failed.',
      problem?.retryable,
      problem?.fields,
    )
  }
  if (!body || typeof body !== 'object' || !('data' in body))
    throw new ApiError(response.status, 'invalid_response', 'The server response is missing data.')
  return body as Envelope<T>
}

export const query = (params: Record<string, string | number | undefined | null>) => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params))
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  return search.toString() ? `?${search}` : ''
}

export const post = <T>(path: string, data: unknown) =>
  api<T>(path, { method: 'POST', body: JSON.stringify(data) })
export const put = <T>(path: string, data: unknown) =>
  api<T>(path, { method: 'PUT', body: JSON.stringify(data) })
export const patch = <T>(path: string, data: unknown) =>
  api<T>(path, { method: 'PATCH', body: JSON.stringify(data) })

export function localDate(d = new Date()): string {
  const y = d.getFullYear(),
    m = `${d.getMonth() + 1}`.padStart(2, '0'),
    day = `${d.getDate()}`.padStart(2, '0')
  return `${y}-${m}-${day}`
}
export function addDays(date: string, amount: number): string {
  const d = new Date(`${date}T12:00:00`)
  d.setDate(d.getDate() + amount)
  return localDate(d)
}
export function dateLabel(
  date: string,
  options: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' },
): string {
  return new Intl.DateTimeFormat('en-US', options).format(new Date(`${date}T12:00:00`))
}
export function distance(m: number | null | undefined, unit: 'mi' | 'km', digits = 1): string {
  return m == null ? '—' : `${(m / (unit === 'mi' ? 1609.344 : 1000)).toFixed(digits)} ${unit}`
}
export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  const h = Math.floor(seconds / 3600),
    m = Math.floor((seconds % 3600) / 60)
  return h ? `${h}h ${`${m}`.padStart(2, '0')}m` : `${m}m`
}
export function pace(secondsPerKm: number | null | undefined, unit: 'mi' | 'km'): string {
  if (secondsPerKm == null) return '—'
  const seconds = Math.round(secondsPerKm * (unit === 'mi' ? 1.609344 : 1))
  return `${Math.floor(seconds / 60)}:${`${seconds % 60}`.padStart(2, '0')} /${unit}`
}

export * from './api/types/calendar'
export * from './api/types/checkins'
export * from './api/types/coach'
export * from './api/types/metrics'
export * from './api/types/blocks'
export * from './api/types/anchors'

export type Unit = 'mi' | 'km'
export const MISSING = 'missing'

export const fmtDistance = (m: number | null | undefined, unit: Unit): string =>
  m == null ? MISSING : distance(m, unit)
export const fmtDuration = (s: number | null | undefined): string =>
  s == null ? MISSING : duration(s)
export function fmtClock(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s) || s < 0) return MISSING
  const rounded = Math.round(s)
  const seconds = `${rounded % 60}`.padStart(2, '0')
  const minutes = Math.floor(rounded / 60)
  if (rounded < 3600) return `${minutes}:${seconds}`
  return `${Math.floor(rounded / 3600)}:${`${minutes % 60}`.padStart(2, '0')}:${seconds}`
}
export const fmtPaceFromSpeed = (mps: number | null | undefined, unit: Unit): string =>
  mps == null || !Number.isFinite(mps) || mps <= 0 ? MISSING : pace(1000 / mps, unit)
export const fmtPercent = (ratio: number | null | undefined): string =>
  ratio == null ? MISSING : `${Math.round(ratio * 100)}%`
export const fmtRpe = (v: number | null | undefined): string =>
  v == null ? MISSING : `${Number(v.toFixed(1))}/10`
export const statusText = (status: string): string => status.replaceAll('_', ' ')

export function signatureLabel(signature: string | null): string {
  if (!signature) return MISSING
  const body = signature.includes(':') ? signature.slice(signature.indexOf(':') + 1) : signature
  return body
    .split('+')
    .map((part) => {
      const match = /^(\d+)x([td])(\d+)$/.exec(part)
      if (!match) return part
      const [, count, kind, raw] = match
      const value = Number(raw)
      const amount =
        kind === 't'
          ? fmtClock(value)
          : value >= 1000
            ? `${Number((value / 1000).toFixed(2))} km`
            : `${value} m`
      return count === '1' ? amount : `${count} × ${amount}`
    })
    .join(' + ')
}

export function clockToSeconds(text: string): number | null {
  if (!/^\d+:\d{2}(?::\d{2})?$/.test(text)) return null
  const parts = text.split(':').map(Number)
  if (parts.some((part) => !Number.isSafeInteger(part))) return null
  const total =
    parts.length === 2
      ? parts[1] < 60
        ? parts[0] * 60 + parts[1]
        : null
      : parts[1] < 60 && parts[2] < 60
        ? parts[0] * 3600 + parts[1] * 60 + parts[2]
        : null
  return total !== null && Number.isSafeInteger(total) ? total : null
}
export function paceToSpeed(text: string, unit: Unit): number | null {
  const seconds = clockToSeconds(text)
  return seconds == null || seconds <= 0 ? null : (unit === 'mi' ? 1609.344 : 1000) / seconds
}
export function sessionTitle(s: {
  kind: SessionKind
  recipe_id: string | null
  custom: boolean
}): string {
  if (s.kind === 'run')
    return s.recipe_id
      ? (RECIPE_LABELS[s.recipe_id] ?? s.recipe_id)
      : s.custom
        ? 'Custom run'
        : 'Quality slot'
  if (s.kind === 'strength') return 'Strength'
  if (s.kind === 'cross') return 'Cross-training'
  if (s.kind === 'mobility') return 'Mobility'
  return 'Rest'
}
export function flattenStructure(items: StructureItem[]): ExpandedStep[] {
  const validNumber = (value: unknown, positive: boolean): value is number =>
    typeof value === 'number' && Number.isFinite(value) && (positive ? value > 0 : value >= 0)
  const validateStep = (value: unknown): value is PlannedStep => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false
    const step = value as Record<string, unknown>
    if (
      Object.keys(step).some(
        (key) => !['type', 'duration_type', 'duration_value', 'target'].includes(key),
      )
    )
      return false
    if (
      !['warmup', 'work', 'recovery', 'cooldown'].includes(String(step.type)) ||
      !['time', 'distance'].includes(String(step.duration_type)) ||
      !validNumber(step.duration_value, true)
    )
      return false
    if (step.target == null) return true
    if (typeof step.target !== 'object' || Array.isArray(step.target)) return false
    const target = step.target as Record<string, unknown>
    if (Object.keys(target).some((key) => !['modality', 'low', 'high', 'effort_cue'].includes(key)))
      return false
    if (target.modality === 'effort')
      return (
        target.low == null &&
        target.high == null &&
        typeof target.effort_cue === 'string' &&
        Boolean(target.effort_cue.trim())
      )
    if (target.modality !== 'speed' && target.modality !== 'hr') return false
    if (
      !validNumber(target.low, target.modality === 'hr') ||
      !validNumber(target.high, target.modality === 'hr') ||
      target.low > target.high
    )
      return false
    return (
      target.effort_cue == null ||
      (typeof target.effort_cue === 'string' && Boolean(target.effort_cue.trim()))
    )
  }
  if (!Array.isArray(items) || items.length === 0) throw new Error('invalid_structure')
  const expanded: ExpandedStep[] = []
  const append = (step: PlannedStep, step_path: string, repeat_index: number | null) => {
    if (!validateStep(step) || expanded.length >= 100) throw new Error('invalid_structure')
    expanded.push({ ...step, step_path, repeat_index, expanded_step: expanded.length + 1 })
  }
  items.forEach((item, i) => {
    if (!item || typeof item !== 'object' || Array.isArray(item))
      throw new Error('invalid_structure')
    if (item.type !== 'repeat') {
      append(item, `${i}`, null)
      return
    }
    if (
      Object.keys(item).some((key) => !['type', 'count', 'steps'].includes(key)) ||
      !Number.isInteger(item.count) ||
      item.count < 2 ||
      !Array.isArray(item.steps) ||
      item.steps.length === 0 ||
      item.steps.some((child) => !validateStep(child))
    )
      throw new Error('invalid_structure')
    for (let j = 0; j < item.count; j++)
      item.steps.forEach((child, k) => append(child, `${i}.steps.${k}`, j))
  })
  return expanded
}
export function formatStep(step: PlannedStep, unit: Unit): string {
  const labels = { warmup: 'Warm-up', work: 'Work', recovery: 'Recovery', cooldown: 'Cool-down' }
  const amount =
    step.duration_type === 'distance'
      ? `${Math.round(step.duration_value)} m`
      : fmtClock(step.duration_value)
  const target = step.target
  let cue = 'effort'
  if (
    target?.modality === 'speed' &&
    target.low != null &&
    target.high != null &&
    target.low > 0 &&
    target.high > 0
  ) {
    cue = `${fmtPaceFromSpeed(target.high, unit)}–${fmtPaceFromSpeed(target.low, unit)}`
  } else if (target?.modality === 'hr' && target.low != null && target.high != null) {
    cue = `${target.low}–${target.high} bpm`
  } else if (target?.modality === 'effort' && target.effort_cue?.trim()) {
    cue = target.effort_cue.trim()
  }
  return `${labels[step.type]} ${amount} · ${cue}`
}
export function sessionMarker(
  s: SessionState,
  c: Completion | undefined,
  today: string,
): SessionMarker {
  if (c?.status === 'completed_as_planned') return 'completed'
  if (c?.status === 'completed_modified') return 'modified'
  if (c?.status === 'partial') return 'partial'
  if (c?.status === 'moved') return 'moved'
  if (c?.status === 'skipped') return 'missed'
  if (c?.activity_id || c?.strong_workout_id || c?.manual_session_id) return 'recorded'
  return s.local_date < today ? 'not_recorded' : 'planned'
}
export function invalidateKeys(qc: QueryClient, keys: readonly (readonly unknown[])[]): void {
  for (const key of keys) void qc.invalidateQueries({ queryKey: [...key] })
}
export const pageHref = {
  home: '#home',
  calendar: '#calendar',
  trends: '#trends',
  settings: '#settings',
  activity: (id: string) => `#activity/${encodeURIComponent(id)}`,
} as const
export const qk = {
  calendar: ['v2', 'calendar'] as const,
  calendarView: (version: number | 'head') => ['v2', 'calendar', 'view', version] as const,
  calendarVersions: ['v2', 'calendar', 'versions'] as const,
  calendarDiff: (from: number, to: number) => ['v2', 'calendar', 'diff', from, to] as const,
  weeklyDigest: (weekStart: string | 'current') =>
    ['v2', 'calendar', 'weekly-digest', weekStart] as const,
  prompts: ['v2', 'prompts'] as const,
  checkins: ['v2', 'checkins'] as const,
  metrics: ['v2', 'metrics'] as const,
  metricsWindows: ['v2', 'metrics', 'windows'] as const,
  metricsRecovery: (start: string, end: string) =>
    ['v2', 'metrics', 'recovery', start, end] as const,
  activityExecution: (id: string) => ['v2', 'metrics', 'execution', id] as const,
  workoutProgression: (groupBy: string) =>
    ['v2', 'metrics', 'workout-progression', groupBy] as const,
  workoutHistory: (id: string) => ['v2', 'metrics', 'workout-history', id] as const,
  activity: (id: string) => ['v2', 'activity', id] as const,
  activitiesNear: (start: string, end: string) =>
    ['v2', 'activities', start, end, 'running', null] as const,
  coach: ['v2', 'coach'] as const,
  exceptions: ['v2', 'exceptions'] as const,
  goals: ['v2', 'goals'] as const,
  events: ['v2', 'events'] as const,
  anchors: ['v2', 'anchors'] as const,
  strengthRoutine: ['v2', 'strength-routine'] as const,
  blocksActive: ['v2', 'blocks', 'active'] as const,
  blockBenchmarks: ['v2', 'blocks', 'benchmarks'] as const,
  profile: ['profile'] as const,
}
