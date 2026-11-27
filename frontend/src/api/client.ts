import type { operations as CalendarOperations } from './generated/calendar'
import type { paths } from './generated/backend'

export type Mode = 'demo' | 'real' | 'test'
export interface Envelope<T> {
  schema_version: string
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
async function requestEnvelope<T extends { data: unknown }>(
  url: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body) headers.set('Content-Type', 'application/json')
  if (options.method && options.method !== 'GET') headers.set('X-Local-Request', '1')
  let response: Response
  try {
    response = await fetch(url, { ...options, headers, credentials: 'same-origin' })
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
  return body as T
}

export function api<T>(path: string, options?: RequestInit) {
  return requestEnvelope<Envelope<T>>(`${BASE}${path}`, options)
}

export const query = (params: Record<string, string | number | undefined | null>) => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params))
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  return search.toString() ? `?${search}` : ''
}

type CalendarRead = CalendarOperations['getCalendar']
type CalendarWeek = CalendarOperations['getCalendarWeek']
type CalendarDiffRead = CalendarOperations['getCalendarDiff']

export function getCalendar(params: NonNullable<CalendarRead['parameters']['query']> = {}) {
  return requestEnvelope<CalendarRead['responses'][200]['content']['application/json']>(
    BASE + '/calendar' + query(params),
  )
}

export function getCalendarWeek(params: NonNullable<CalendarWeek['parameters']['query']> = {}) {
  return requestEnvelope<CalendarWeek['responses'][200]['content']['application/json']>(
    BASE + '/calendar/week' + query(params),
  )
}

export function getCalendarDiff(params: CalendarDiffRead['parameters']['query']) {
  return requestEnvelope<CalendarDiffRead['responses'][200]['content']['application/json']>(
    BASE + '/calendar/diff' + query(params),
  )
}

const proposalListPath = `${BASE}/coach/proposals`
type ProposalListGet = paths[typeof proposalListPath]['get']
export type ProposalListResponse = ProposalListGet['responses'][200]['content']['application/json']
export function listProposals(params: NonNullable<ProposalListGet['parameters']['query']> = {}) {
  return requestEnvelope<ProposalListResponse>(proposalListPath + query(params))
}

const goalsPath = '/api/v1/goals'
type GoalsGet = paths[typeof goalsPath]['get']
type GoalsPost = paths[typeof goalsPath]['post']

export function listGoals() {
  return requestEnvelope<GoalsGet['responses'][200]['content']['application/json']>(goalsPath)
}
export function createGoal(body: GoalsPost['requestBody']['content']['application/json']) {
  return requestEnvelope<GoalsPost['responses'][201]['content']['application/json']>(goalsPath, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

const goalPath = '/api/v1/goals/{goal_id}'
type GoalPatch = paths[typeof goalPath]['patch']
export function patchGoal(
  goalId: GoalPatch['parameters']['path']['goal_id'],
  changes: GoalPatch['requestBody']['content']['application/json'],
) {
  return requestEnvelope<GoalPatch['responses'][200]['content']['application/json']>(
    goalPath.replace('{goal_id}', encodeURIComponent(goalId)),
    { method: 'PATCH', body: JSON.stringify(changes) },
  )
}

export const post = <T>(path: string, data: unknown) =>
  api<T>(path, { method: 'POST', body: JSON.stringify(data) })
export const put = <T>(path: string, data: unknown) =>
  api<T>(path, { method: 'PUT', body: JSON.stringify(data) })
export const patch = <T>(path: string, data: unknown) =>
  api<T>(path, { method: 'PATCH', body: JSON.stringify(data) })
