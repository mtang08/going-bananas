import { fmtClock, fmtPaceFromSpeed, type Unit } from './lib/format'
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

export * from './api/types/calendar'
export * from './api/types/checkins'
export * from './api/types/coach'
export * from './api/types/metrics'
export * from './api/types/blocks'
export * from './api/types/anchors'
// TRANSITIONAL (ARCH-14y9): importers move to the type modules in ARCH-14y2-14y9, then api.ts is deleted
export * from './api/types/activity'
export * from './api/types/profile'
export * from './api/types/sync'
// TRANSITIONAL (ARCH-14y9): importers move to api/queryKeys in ARCH-14y2-14y9, then api.ts is deleted
export { qk, invalidateKeys } from './api/queryKeys'
// TRANSITIONAL (ARCH-14y9): importers move to lib/format in ARCH-14y2-14y9, then api.ts is deleted
export {
  validDate,
  localDate,
  addDays,
  dateLabel,
  distance,
  duration,
  pace,
  MISSING,
  fmtDistance,
  fmtDuration,
  fmtClock,
  fmtPaceFromSpeed,
  fmtPercent,
  fmtRpe,
  statusText,
  signatureLabel,
  clockToSeconds,
  paceToSpeed,
  type Unit,
} from './lib/format'

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
export const pageHref = {
  home: '#home',
  calendar: '#calendar',
  trends: '#trends',
  settings: '#settings',
  activity: (id: string) => `#activity/${encodeURIComponent(id)}`,
} as const
