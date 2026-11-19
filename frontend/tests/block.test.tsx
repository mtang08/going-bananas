import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Block } from '../src/pages/Block'
import { fmtDuration } from '../src/lib/format'
import type { BlockVersion, BenchmarkStatus } from '../src/api/types/blocks'
const BM = {
  kind: 'time_trial' as const,
  event_id: null,
  protocol: '5 km solo time trial, flat loop',
  distance_m: 5000,
  planned_date: '2026-12-10',
  progress_if: 'Faster than 21:40',
  consolidate_if: 'Within 20 s of 21:40',
}
const status = (over: Partial<BenchmarkStatus> = {}): BenchmarkStatus => ({
  status: 'pending',
  match_method: null,
  activity_id: null,
  event_id: null,
  local_date: null,
  distance_m: null,
  result_s: null,
  rpe: null,
  scheduled_date: null,
  evidence_at: null,
  ...over,
})
let calls: { url: string; method: string; body: unknown; headers: Headers }[] = []
let runsError = false
let block: BlockVersion | null
const clients: QueryClient[] = []
beforeEach(() => {
  calls = []
  runsError = false
  block = {
    id: 'v1',
    block_uid: 'b1',
    version: 1,
    status: 'active',
    objective: 'Build consistency',
    rationale: 'Keep the week repeatable',
    maintained_qualities: ['Easy endurance'],
    non_goals: ['Peak racing'],
    eligible_recipe_ids: ['REC001'],
    progression_dimension: 'duration',
    constraints: [{ kind: 'schedule', text: 'Keep strength days' }],
    start_date: '2026-11-01',
    review_date: '2026-12-13',
    completion_indicators: ['Tolerated weeks'],
    early_review_triggers: ['Symptoms increase'],
    objective_status: 'unresolved',
    created_at: '2026-11-01T12:00:00Z',
    proposal_id: 'p1',
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input),
        method = init?.method ?? 'GET'
      calls.push({
        url,
        method,
        body: init?.body ? JSON.parse(String(init.body)) : null,
        headers: new Headers(init?.headers),
      })
      if (url.includes('/activities') && runsError)
        return {
          ok: false,
          status: 500,
          json: async () => ({ error: { code: 'failed', message: 'Runs unavailable' } }),
        }
      const data = url.includes('/activities')
        ? {
            items: [
              {
                id: 'a2',
                local_date: '2026-11-10',
                distance_m: 5000,
                sport: 'running',
                start_at: '2026-11-10T12:00:00Z',
              },
              {
                id: 'c1',
                local_date: '2026-11-09',
                distance_m: 20000,
                sport: 'cycling',
                start_at: '2026-11-09T12:00:00Z',
              },
              {
                id: 'a1',
                local_date: '2026-11-08',
                distance_m: 5010,
                sport: 'treadmill_running',
                start_at: '2026-11-08T12:00:00Z',
              },
            ],
          }
        : method === 'PUT'
          ? { benchmark: null, benchmark_status: null }
          : url.endsWith('/calendar')
            ? { today: '2026-11-12' }
            : url.endsWith('/history')
              ? { items: block ? [block] : [] }
              : block
      return {
        ok: true,
        json: async () => ({ schema_version: 'v1', mode: 'demo', data_revision: 1, data }),
      }
    }),
  )
})
afterEach(() => {
  cleanup()
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.unstubAllGlobals()
})
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  render(
    <QueryClientProvider client={client}>
      <Block />
    </QueryClientProvider>,
  )
}
it('shows no active block without offering automatic changes', async () => {
  block = null
  mount()
  await screen.findByText('No active training block')
  expect(screen.queryByRole('button', { name: /Create/ })).not.toBeInTheDocument()
})
it('shows objective, athlete-local week, constraints and lineage', async () => {
  mount()
  await screen.findByText('11 days elapsed')
  expect(screen.getByRole('heading', { name: 'Build consistency' })).toBeInTheDocument()
  expect(screen.getByText('Keep strength days')).toBeInTheDocument()
  expect(await screen.findByRole('link', { name: 'View reviewed proposal' })).toHaveAttribute(
    'href',
    '#proposal/p1',
  )
  expect(screen.getByText('Symptoms increase')).toBeInTheDocument()
})

it('shows an overdue review without claiming objective completion', async () => {
  block!.review_date = '2026-11-10'
  mount()
  await screen.findByText('Review overdue · 2 days')
  expect(
    screen.getByText('Review criteria; achievement has not been verified here.'),
  ).toBeInTheDocument()
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
})
it('links the empty state to the review guide', async () => {
  block = null
  mount()
  expect(await screen.findByRole('link', { name: 'How to review with the coach' })).toHaveAttribute(
    'href',
    '#guide',
  )
})

it('labels review due today without a completion percentage', async () => {
  block!.review_date = '2026-11-12'
  mount()
  await screen.findByText('Review due today')
  expect(screen.getByRole('list', { name: 'Block elapsed time' })).toBeInTheDocument()
})

it('shows a missing benchmark', async () => {
  mount()
  expect(await screen.findByTestId('block-benchmark')).toHaveTextContent(
    'Status: Not set. The next block review sets the ending benchmark.',
  )
  expect(screen.queryByLabelText('Choose activity')).toBeNull()
})
it('shows a pending benchmark and lists runs in the window', async () => {
  block!.benchmark = BM
  block!.benchmark_status = status()
  mount()
  expect(await screen.findByTestId('benchmark-status')).toHaveTextContent('Pending · Dec 10')
  await waitFor(() =>
    expect(
      within(screen.getByLabelText('Choose activity'))
        .getAllByRole('option')
        .map((o) => o.textContent),
    ).toEqual(['Choose a run', 'Nov 10 · 3.1 mi', 'Nov 8 · 3.1 mi']),
  )
  const url = calls.find((c) => c.url.includes('/activities'))!.url
  expect(url).toContain('start_date=2026-12-03')
  expect(url).toContain('end_date=2026-12-20')
  expect(url).not.toContain('sport=')
})
it('choosing a run sets the manual match', async () => {
  block!.benchmark = BM
  block!.benchmark_status = status()
  mount()
  await screen.findByRole('option', { name: 'Nov 10 · 3.1 mi' })
  fireEvent.change(screen.getByLabelText('Choose activity'), { target: { value: 'a2' } })
  await waitFor(() => expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(1))
  const put = calls.find((c) => c.method === 'PUT')!
  expect(put.url).toBe('/api/v1/blocks/b1/benchmark-activity')
  expect(put.body).toEqual({ activity_id: 'a2' })
  expect(put.headers.get('X-Local-Request')).toBe('1')
  await waitFor(() =>
    expect(calls.filter((c) => c.url.endsWith('/blocks/active')).length).toBeGreaterThan(1),
  )
})
it('shows the chosen match and clears it', async () => {
  block!.benchmark = BM
  block!.benchmark_status = status({
    status: 'completed',
    match_method: 'manual',
    activity_id: 'a2',
    local_date: '2026-11-10',
    distance_m: 5000,
    result_s: 1290,
    rpe: 8,
  })
  mount()
  expect(await screen.findByTestId('benchmark-status')).toHaveTextContent('Completed Nov 10')
  const match = screen.getByTestId('benchmark-match')
  for (const text of ['Chosen by you', fmtDuration(1290), '8/10'])
    expect(match).toHaveTextContent(text)
  await screen.findByRole('option', { name: 'Nov 10 · 3.1 mi' })
  expect(screen.getByLabelText('Choose activity')).toHaveValue('a2')
  fireEvent.click(screen.getByRole('button', { name: 'Use automatic match' }))
  await waitFor(() =>
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ activity_id: null }),
  )
  cleanup()
  block!.benchmark_status = { ...block!.benchmark_status!, match_method: 'auto' }
  mount()
  expect(await screen.findByTestId('benchmark-match')).toHaveTextContent('Matched automatically')
  expect(screen.queryByRole('button', { name: 'Use automatic match' })).toBeNull()
})
it('shows activity loading failure and retries without changing the match', async () => {
  block!.benchmark = BM
  block!.benchmark_status = status()
  runsError = true
  mount()
  expect(await screen.findByText('Runs unavailable')).toBeInTheDocument()
  runsError = false
  fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
  expect(await screen.findByRole('option', { name: 'Nov 8 · 3.1 mi' })).toBeInTheDocument()
  expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(0)
})
