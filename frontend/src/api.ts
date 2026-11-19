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

// TRANSITIONAL (ARCH-14y9): importers move to lib/structure, lib/session, lib/routes in ARCH-14y2-14y9, then api.ts is deleted
export { flattenStructure, formatStep } from './lib/structure'
export { sessionTitle, sessionMarker } from './lib/session'
export { pageHref } from './lib/routes'
