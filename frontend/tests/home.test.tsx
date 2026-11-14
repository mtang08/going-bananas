import type { ExceptionsView, Finding, Patch, Severity } from '../src/api/types/exceptions'
import { EXCEPTION_PROMPT } from '../src/coachPrompts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Home } from '../src/pages/Home'
import type { ProposalSummary } from '../src/api/types/coach'
import type { CalendarView, SessionState } from '../src/api'

const finding = (id: string, severity: Severity, summary: string, version = 1): Finding => ({ id, rule_code: 'FATIGUE_PERSISTING', category: 'accumulated_fatigue', severity, status: 'open', entity_key: `fatigue:${id}`, summary, evidence: [], evidence_at: '2026-11-11T12:00:00Z', first_seen_at: '2026-11-11T12:00:00Z', last_seen_at: '2026-11-11T12:00:00Z', patch_id: null, version, is_new_since_last_review: true })
const pa1: Patch = { id: 'pa1', proposal_id: 'p9', calendar_version_number: 2, category: 'accumulated_fatigue', severity: 'caution', ladder_level: 'next_days', window_start: '2026-11-11', window_end: '2026-11-13', reassess_on: '2026-11-11', monitor: ['Morning fatigue'], return_criteria: ['Fatigue below 6'], escalate_criteria: ['Fatigue rising'], unchanged: [], status: 'open', resolved_at: null, resolved_by: null, resolution_note: null, created_at: '2026-11-10T12:00:00Z', version: 1, session_uids: [], reassess_due: true }
const rec = { operation: 'exception_review' as const, reason: 'Open findings at caution or hold need an exception review', finding_ids: ['f1'], prompt: EXCEPTION_PROMPT }

const session = (id: string, day: string, overrides: Partial<SessionState> = {}): SessionState => ({
  id, session_uid: id, local_date: day, slot: 1, kind: 'run', recipe_id: 'REC001', custom: false,
  intent: 'Comfortable effort', placeholder: false, locked: false, planned_duration_s: 1800,
  planned_distance_m: null, structure: null, strength_slot_id: null, notes: null, certainty: 'committed',
  legacy_unstructured: false, legacy_payload: null, revision: 1, calendar_version_number: 2,
  deleted: false, is_original: true, changed_by_version: 2, ...overrides,
})
const baseSessions = () => [session('s1', '2026-11-11'), session('s2', '2026-11-13', { recipe_id: null, placeholder: true, is_original: false }),
  session('s3', '2026-11-19', { recipe_id: 'REC002', certainty: 'provisional' })]
let proposalItems: ProposalSummary[]
let promptItems: unknown[]
let calendar: CalendarView
let exceptionsData: ExceptionsView
let error = false
let requests: { url: string; method: string; body: unknown; headers: Headers }[]
const onCheckin = vi.fn()
const clients: QueryClient[] = []
beforeEach(() => {
  exceptionsData = { rule_version: 'exceptions.v1', findings: [], patches: [], review_recommended: [], counts: { observe: 0, caution: 0, hold: 0, escalate: 0 } }
  proposalItems = []
  promptItems = [
      { id: 'p1', kind: 'rpe', activity_id: 'a1', session_uid: null, status: 'open' },
      { id: 'p2', kind: 'delayed_symptom', activity_id: 'a1', session_uid: null, status: 'open' },
    ]
  requests = []; error = false; onCheckin.mockReset()
  calendar = { today: '2026-11-11', timezone: 'America/New_York', start: '2026-11-04', end: '2026-11-24',
    head: 2, version: 2, undo: null, last_planned_date: null, sessions: baseSessions(), completions: [] }
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input), method = init?.method ?? 'GET'
    requests.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null, headers: new Headers(init?.headers) })
    if (url.endsWith('/calendar') && error) return { ok: false, status: 500, json: async () => ({ error: { code: 'request_failed', message: 'boom' } }) }
    const data = url.endsWith('/sync/status') ? { datasets: [], active_jobs: [] }
      : url.includes('/coach/proposals') ? { items: proposalItems }
      : url.endsWith('/calendar') ? calendar : url.endsWith('/prompts') ? { items: promptItems } : url.endsWith('/activities/a1') ? { id: 'a1', local_date: '2026-11-10', distance_m: 6437.376, sport: 'running' }
      : url.includes('/exceptions') || url.includes('/exception-patches') ? exceptionsData : null
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
  it('shows empty block', async () => {
    mount()
    const blockLine = await screen.findByTestId('block-line')
    expect(blockLine).toHaveTextContent('No active training block. Training block')
    expect(within(blockLine).getByRole('link', { name: 'Training block' })).toHaveAttribute('href', '#block')
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
    expect(await screen.findByTestId('block-line')).toBeInTheDocument()
  })
  it('compacts repeats and preserves structured and imported prescription notes', async () => {
    calendar.sessions[0].notes = 'Stop if form deteriorates'
    calendar.sessions[0].structure = [{ type: 'repeat', count: 2, steps: [
      { type: 'work', duration_type: 'time', duration_value: 60, target: null },
      { type: 'recovery', duration_type: 'time', duration_value: 30, target: null },
    ] }]
    calendar.sessions.push(session('legacy', '2026-11-11', { recipe_id: null, slot: 2, legacy_unstructured: true, notes: 'Original prescribed easy progression' }))
    mount()
    const card = await screen.findByTestId('today-card')
    expect(within(card).getByText('2 ×')).toBeVisible()
    expect(within(card).getByText('2 ×').closest('details')).toBeNull()
    expect(within(card).getByText('Stop if form deteriorates').closest('details')).not.toHaveAttribute('open')
    expect(within(card).queryByText('Session details')).not.toBeInTheDocument()
    fireEvent.click(within(card).getByText('Session notes'))
    expect(within(card).getByText('Stop if form deteriorates')).toBeVisible()
    expect(within(card).getByText('Original prescribed easy progression')).toBeVisible()
    expect(within(card).getByText('Work 1:00 · effort')).toBeInTheDocument()
    expect(within(card).getByText('Recovery after every rep, including the final rep.')).toBeInTheDocument()
    expect(within(card).getByText('Stop if form deteriorates')).toBeInTheDocument()
    expect(within(card).getByText('Original prescribed easy progression')).toBeInTheDocument()
    expect(within(card).getByText('Structured comparison unavailable')).toBeInTheDocument()
    expect(within(card).queryByText('Quality slot')).not.toBeInTheDocument()
  })
  it('lists open proposals in Needs attention without deciding', async () => {
    proposalItems = [{ id: 'p1', status: 'stale', operation: 'review_rolling_plan', submitted_at: new Date(Date.now() - 2 * 3600_000).toISOString(), change_count: 3, summary: 'Keep tomorrow easy' } as ProposalSummary]
    mount(); await screen.findByText('Weekly review')
    const row = document.querySelector('[data-kind="proposal"]')!
    for (const text of ['Stale — ask the coach to refresh', 'Weekly review', '2 h ago', '3 changes']) expect(row).toHaveTextContent(text)
    expect(within(row as HTMLElement).getByRole('link', { name: 'Review' })).toHaveAttribute('href', '#proposal/p1')
    expect(row.compareDocumentPosition(screen.getByRole('heading', { name: "Today's plan" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(requests.every(r => r.method === 'GET')).toBe(true)
  })
  it('orders Home sections', async () => {
    mount(); await screen.findByTestId('today-card')
    const sections = ['Needs attention', "Today's plan", 'This week'].map(name => screen.getByRole('heading', { name }))
    for (let i = 0; i < sections.length - 1; i++) expect(sections[i].compareDocumentPosition(sections[i + 1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByTestId('home-status').compareDocumentPosition(sections[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
  it('hides Needs attention when nothing needs it', async () => {
    promptItems = []; mount(); await screen.findByTestId('today-card')
    expect(screen.queryByTestId('needs-attention')).toBeNull()
  })
  it('has no page-level check-in button', async () => {
    mount(); await screen.findByTestId('today-card')
    expect(screen.queryByRole('button', { name: 'Record check-in' })).toBeNull()
  })

  it('orders exception rows inside Needs attention', async () => {
    proposalItems = [{ id: 'p1', status: 'stale', operation: 'review_rolling_plan', submitted_at: new Date(Date.now() - 2 * 3600_000).toISOString(), change_count: 3, summary: 'Keep tomorrow easy' } as ProposalSummary]
    exceptionsData = { ...exceptionsData, review_recommended: [rec], findings: [finding('f1', 'caution', 'Fatigue 8 on two days.'), finding('f2', 'observe', 'Easy run felt RPE 7.')], patches: [pa1] }
    mount(); await screen.findByText('Fatigue 8 on two days.')
    const rows = screen.getAllByTestId('attention-row')
    expect(rows.map(row => row.getAttribute('data-kind'))).toEqual(['proposal','recommendation','finding','patch'])
    expect(rows[3].compareDocumentPosition(screen.getAllByTestId('prompt-item')[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    for (const text of ['Caution', 'Fatigue and recovery', 'Fatigue 8 on two days.']) expect(rows[2]).toHaveTextContent(text)
    expect(screen.getByTestId('needs-attention')).not.toHaveTextContent('Easy run felt RPE 7.')
    expect(rows[3]).toHaveTextContent('Reassess due · Nov 11–Nov 13')
  })
  it('copies the coach prompt', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    try {
      exceptionsData = { ...exceptionsData, review_recommended: [rec] }; mount()
      await screen.findByText(rec.reason)
      const row = document.querySelector('[data-kind="recommendation"]') as HTMLElement
      fireEvent.click(within(row).getByRole('button', { name: 'Copy prompt' }))
      await waitFor(() => expect(writeText).toHaveBeenCalledWith(EXCEPTION_PROMPT))
    } finally {
      if (original) Object.defineProperty(navigator, 'clipboard', original)
      else Reflect.deleteProperty(navigator, 'clipboard')
    }
  })
  it('dismiss sends expected_version and refetches findings', async () => {
    exceptionsData.findings = [finding('f1', 'caution', 'Fatigue 8 on two days.', 3)]
    mount(); await screen.findByText('Fatigue 8 on two days.')
    fireEvent.click(within(document.querySelector('[data-kind="finding"]') as HTMLElement).getByRole('button', { name: 'Dismiss' }))
    await waitFor(() => expect(requests.filter(r => r.method === 'GET' && r.url === '/api/v1/exceptions')).toHaveLength(2))
    const posts = requests.filter(r => r.method === 'POST')
    expect(posts).toHaveLength(1); expect(posts[0].url).toBe('/api/v1/exceptions/f1/dismiss')
    expect(posts[0].body).toEqual({ expected_version: 3, note: null })
    expect(posts[0].headers.get('X-Local-Request')).toBe('1')
  })
  it('resolves or escalates a due patch', async () => {
    exceptionsData.patches = [pa1]; mount()
    const resolved = await screen.findByRole('button', { name: 'Mark resolved' })
    fireEvent.click(resolved)
    await waitFor(() => expect(requests.filter(r => r.method === 'POST')).toHaveLength(1))
    await waitFor(() => expect(resolved).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Still not right' }))
    await waitFor(() => expect(requests.filter(r => r.method === 'POST')).toHaveLength(2))
    const posts = requests.filter(r => r.method === 'POST')
    for (const [i, status] of ['resolved', 'escalated'].entries()) {
      expect(posts[i].url).toBe('/api/v1/exception-patches/pa1/resolve')
      expect(posts[i].body).toEqual({ expected_version: 1, status, note: null })
    }
  })

})
