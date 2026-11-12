import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Home } from '../src/pages/Home'
import type { CalendarView, DailyGuidance, SessionState } from '../src/api'

const session = (id: string, day: string, overrides: Partial<SessionState> = {}): SessionState => ({
  id, session_uid: id, local_date: day, slot: 1, kind: 'run', recipe_id: 'REC001', custom: false,
  intent: 'Comfortable effort', placeholder: false, locked: false, planned_duration_s: 1800,
  planned_distance_m: null, structure: null, strength_slot_id: null, notes: null, certainty: 'committed',
  legacy_unstructured: false, legacy_payload: null, revision: 1, calendar_version_number: 2,
  deleted: false, is_original: true, changed_by_version: 2, ...overrides,
})
const baseSessions = () => [session('s1', '2026-11-11'), session('s2', '2026-11-13', { recipe_id: null, placeholder: true, is_original: false }),
  session('s3', '2026-11-19', { recipe_id: 'REC002', certainty: 'provisional' })]
let calendar: CalendarView
let guidance: DailyGuidance | null
let error = false
let requests: { url: string; method: string; body: unknown; headers: Headers }[]
const onCheckin = vi.fn()
const clients: QueryClient[] = []
beforeEach(() => {
  requests = []; error = false; guidance = null; onCheckin.mockReset()
  calendar = { today: '2026-11-11', timezone: 'America/New_York', start: '2026-11-04', end: '2026-11-24',
    head: 2, version: 2, undo: null, last_planned_date: null, sessions: baseSessions(), completions: [] }
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input), method = init?.method ?? 'GET'
    requests.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null, headers: new Headers(init?.headers) })
    if (url.endsWith('/calendar') && error) return { ok: false, status: 500, json: async () => ({ error: { code: 'request_failed', message: 'boom' } }) }
    const data = url.endsWith('/calendar') ? calendar : url.endsWith('/prompts') ? { items: [
      { id: 'p1', kind: 'rpe', activity_id: 'a1', session_uid: null, status: 'open' },
      { id: 'p2', kind: 'delayed_symptom', activity_id: 'a1', session_uid: null, status: 'open' },
    ] } : url.endsWith('/activities/a1') ? { id: 'a1', local_date: '2026-11-10', distance_m: 6437.376, sport: 'running' }
      : url.endsWith('/coach/v2/daily') ? guidance : null
    return { ok: true, status: 200, json: async () => ({ schema_version: 'v1', data_revision: 1, mode: 'demo', data }) }
  }))
})
afterEach(() => { cleanup(); clients.forEach(c => c.clear()); clients.length = 0; vi.unstubAllGlobals() })
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); clients.push(client)
  return render(<QueryClientProvider client={client}><Home unit="mi" onCheckin={onCheckin} /></QueryClientProvider>)
}

describe('training home', () => {
  it('shows today and the strip', async () => {
    mount()
    await screen.findByRole('heading', { name: 'Wednesday, November 11' })
    const card = screen.getByTestId('today-card')
    expect(within(card).getByText('Easy run')).toBeInTheDocument()
    expect(within(card).getByText('30m')).toBeInTheDocument()
    expect(screen.getAllByTestId('strip-day')).toHaveLength(14)
    const longDay = document.querySelector('[data-date="2026-11-19"]') as HTMLElement
    expect(within(longDay).getByTestId('session-tag')).toHaveClass('certainty-provisional')
    const changed = document.querySelector('[data-date="2026-11-13"]') as HTMLElement
    expect(within(changed).getByText('Quality slot')).toBeInTheDocument()
    expect(within(changed).getByText('Changed')).toBeInTheDocument()
    expect(document.querySelector('[data-date="2026-11-11"]')).toHaveTextContent('Planned')
  })
  it('prompt actions open the right check-in', async () => {
    mount()
    await screen.findByText('Rate your run on Nov 10 · 4.0 mi')
    fireEvent.click(screen.getByRole('button', { name: 'Add RPE' }))
    expect(onCheckin).toHaveBeenCalledWith({ kind: 'post_run', prompt: expect.objectContaining({ id: 'p1' }), activityId: 'a1' })
    fireEvent.click(screen.getByRole('button', { name: 'Answer check' }))
    expect(onCheckin).toHaveBeenCalledWith({ kind: 'delayed_followup', prompt: expect.objectContaining({ id: 'p2' }), activityId: 'a1' })
    fireEvent.click(screen.getByRole('button', { name: 'Record check-in' }))
    expect(onCheckin).toHaveBeenCalledWith({ kind: 'exception', prompt: null, activityId: null })
    expect(requests.filter(r => r.url.endsWith('/activities/a1'))).toHaveLength(1)
  })
  it('dismiss posts and refetches prompts', async () => {
    mount()
    fireEvent.click((await screen.findAllByRole('button', { name: 'Dismiss' }))[0])
    await waitFor(() => expect(requests.filter(r => r.url.endsWith('/prompts'))).toHaveLength(2))
    const request = requests.find(r => r.method === 'POST')!
    expect(request.url).toBe('/api/v1/prompts/p1/dismiss')
    expect(request.headers.get('X-Local-Request')).toBe('1')
    expect(request.body).toEqual({})
  })
  it('shows empty guidance and block', async () => {
    mount()
    expect(await screen.findByText(/No guidance today/)).toBeInTheDocument()
    expect(await screen.findByText(/No active block/)).toBeInTheDocument()
  })
  it('shows guidance with coach review', async () => {
    guidance = { id: 'g1', created_at: '', input_hash: '', local_date: '2026-11-11', checkin_id: null,
      engine: 'local_rules.v2', decision: 'modify', session_uid: 's1', rationale: 'Shorten today',
      missing_inputs: ['gait_change'], coach_review_suggested: true, trigger_codes: [] }
    mount()
    expect(await screen.findByText('Modify')).toBeInTheDocument()
    expect(screen.getByText('Shorten today')).toBeInTheDocument()
    expect(screen.getByText(/Coach review suggested/)).toBeInTheDocument()
    expect(screen.getByText('Missing inputs: gait change')).toBeInTheDocument()
  })
  it('shows setup without a calendar', async () => {
    calendar = { ...calendar, head: 0, sessions: [] }
    mount()
    expect(await screen.findByText('No calendar yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open setup' })).toHaveAttribute('href', '#settings')
    expect(screen.queryByTestId('today-card')).not.toBeInTheDocument()
    expect(screen.queryByTestId('strip-day')).not.toBeInTheDocument()
  })
  it('shows plan-end banner and leaves future empty days empty', async () => {
    calendar.sessions = calendar.sessions.slice(0, 2)
    mount()
    expect(await screen.findByTestId('plan-end-banner')).toHaveTextContent('Plan ends on Nov 13 — run the weekly review')
    expect(document.querySelector('[data-date="2026-11-15"]')).toHaveTextContent('No session')
  })
  it('omits the plan-end banner for a longer plan', async () => {
    mount(); await screen.findByTestId('today-card')
    expect(screen.queryByTestId('plan-end-banner')).not.toBeInTheDocument()
  })
  it('shows a calendar error without hiding independent panels', async () => {
    error = true; mount()
    expect(await screen.findByText('Could not load this view')).toBeInTheDocument()
    expect(screen.getByText('boom')).toBeInTheDocument()
    expect(await screen.findByText(/No guidance today/)).toBeInTheDocument()
  })
  it('renders repeats interleaved and preserves imported prescription notes', async () => {
    calendar.sessions[0].structure = [{ type: 'repeat', count: 2, steps: [
      { type: 'work', duration_type: 'time', duration_value: 60, target: null },
      { type: 'recovery', duration_type: 'time', duration_value: 30, target: null },
    ] }]
    calendar.sessions.push(session('legacy', '2026-11-11', { recipe_id: null, slot: 2, legacy_unstructured: true, notes: 'Original prescribed easy progression' }))
    mount()
    const card = await screen.findByTestId('today-card')
    expect(within(card).getAllByRole('listitem').map(li => li.textContent)).toEqual([
      'Work 1:00 · effort', 'Recovery 0:30 · effort', 'Work 1:00 · effort', 'Recovery 0:30 · effort',
    ])
    expect(within(card).getByText('Original prescribed easy progression')).toBeInTheDocument()
    expect(within(card).getByText('Structured comparison unavailable')).toBeInTheDocument()
    expect(within(card).queryByText('Quality slot')).not.toBeInTheDocument()
  })
})
