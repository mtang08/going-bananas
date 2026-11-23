import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Block } from '../src/pages/Block'
import { fmtDuration } from '../src/lib/format'
import type { ActiveBlock, BenchmarkStatus } from '../src/api/types/blocks'
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
let block: ActiveBlock | null
let history: ActiveBlock[] | null
const clients: QueryClient[] = []
beforeEach(() => {
  calls = []
  runsError = false
  history = null
  block = {
    id: 'v1',
    block_uid: 'b1',
    version: 1,
    status: 'active',
    objective: 'Build consistency',
    why: [],
    maintained_qualities: ['Easy endurance'],
    non_goals: ['Peak racing'],
    eligible_recipe_ids: ['REC001'],
    progression_dimension: 'duration',
    constraints: [{ kind: 'schedule', text: 'Keep strength days' }],
    start_date: '2026-11-01',
    review_date: '2026-12-13',
    indicators: [
      {
        source: 'key_sessions',
        label: 'Tolerated weeks',
        progress_when: '7 of 8 sessions or more',
      },
    ],
    early_review_triggers: ['Symptoms increase'],
    objective_status: 'unresolved',
    created_at: '2026-11-01T12:00:00Z',
    proposal_id: 'p1',
    legacy_text: null,
    sources: [],
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
              ? { items: history ?? (block ? [block] : []) }
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

it('shows a block without a benchmark', async () => {
  mount()
  expect(await screen.findByTestId('block-benchmark')).toHaveTextContent(
    "No benchmark in this block. Its review judges the block's review criteria instead.",
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

it('shows indicators as a table with source labels', async () => {
  block!.indicators = [
    {
      source: 'quality_progression',
      label: 'Tempo reps at the same RPE',
      progress_when: 'pace 2% faster at RPE 7 or lower',
    },
    { source: 'rpe_vs_intent', label: 'Easy days stay easy', progress_when: 'RPE 4 or lower' },
  ]
  mount()
  expect(await screen.findByRole('heading', { name: 'Review this block by' })).toBeVisible()
  expect(screen.getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual([
    'Indicator',
    'Progress when',
    'Source',
  ])
  expect(
    screen.getByRole('row', {
      name: /Tempo reps at the same RPE.*pace 2% faster.*Workout progression/,
    }),
  ).toBeVisible()
  expect(screen.getByRole('row', { name: /Easy days stay easy.*Effort vs plan/ })).toBeVisible()
})

it('shows the review-early line and maintains chips', async () => {
  block!.early_review_triggers = ['Calf 3/10 twice', '2 missed key sessions']
  mount()
  expect((await screen.findByText('Review early if:')).closest('p')).toHaveTextContent(
    'Review early if: Calf 3/10 twice · 2 missed key sessions',
  )
  expect(screen.getByText('Maintains:')).toBeVisible()
  expect(screen.getByText('Easy endurance')).toBeVisible()
})

it('keeps why, sources, constraints and eligible sessions in disclosures', async () => {
  block!.why = [
    { kind: 'observation', text: 'Tempo held two weeks running' },
    { kind: 'priority', text: 'City 10K is the goal race' },
  ]
  block!.sources = [
    { kind: 'policy', title: 'Progress one variable at a time', papers: ['Paper A (2020)'] },
  ]
  mount()
  const summaries = await Promise.all(
    ['Why this block', 'Constraints and out of scope', 'Eligible sessions'].map((text) =>
      screen.findByText(text),
    ),
  )
  for (const summary of summaries) {
    expect(summary.tagName).toBe('SUMMARY')
    expect(summary.closest('details')).not.toHaveAttribute('open')
    fireEvent.click(summary)
  }
  expect(screen.getByText('Observed')).toBeVisible()
  expect(screen.getByText('Your priority')).toBeVisible()
  expect(screen.getByText('Tempo held two weeks running')).toBeVisible()
  expect(screen.getByText('City 10K is the goal race')).toBeVisible()
  fireEvent.click(screen.getByText('Sources (1)'))
  expect(screen.getByText('Progress one variable at a time')).toHaveAttribute(
    'title',
    'Paper A (2020)',
  )
  expect(screen.getByText('Easy run')).toBeVisible()
  expect(screen.getByText('Keep strength days')).toBeVisible()
  expect(screen.getByText('Peak racing')).toBeVisible()
})

it('shows only Earlier format for a migrated block without structured criteria', async () => {
  block = {
    ...block!,
    why: [],
    indicators: [],
    early_review_triggers: [],
    maintained_qualities: [],
    non_goals: [],
    constraints: [],
    eligible_recipe_ids: [],
    sources: [],
    legacy_text: 'Keep the week repeatable\n\nReview goals:\n- Tolerated weeks',
  }
  mount()
  const direction = within(
    (await screen.findByRole('heading', { name: 'Build consistency' })).closest(
      '.block-direction',
    )!,
  )
  expect(direction.getByText('Earlier format').closest('details')).not.toHaveAttribute('open')
  expect(direction.getByText('Keep the week repeatable')).not.toBeVisible()
  for (const label of [
    'Review this block by',
    'Why this block',
    'Review early if:',
    'Maintains:',
    'Eligible sessions',
    'Constraints and out of scope',
  ]) {
    expect(direction.queryByText(label)).not.toBeInTheDocument()
  }
})

it('lists block history one line per version with why on expand', async () => {
  history = [
    block!,
    {
      ...block!,
      id: 'v0',
      version: 0,
      status: 'replaced',
      objective: 'Earlier base',
      why: [{ kind: 'inference', text: 'Base first' }],
      legacy_text: null,
    },
  ]
  mount()
  fireEvent.click(await screen.findByText('Block history'))
  const current = await screen.findByText('Version 1 · active · Build consistency')
  const earlier = screen.getByText('Version 0 · replaced · Earlier base')
  for (const summary of [current, earlier]) {
    expect(summary.tagName).toBe('SUMMARY')
    expect(summary.closest('details')).not.toHaveAttribute('open')
  }
  fireEvent.click(earlier)
  expect(screen.getByText('Inference')).toBeVisible()
  expect(screen.getByText('Base first')).toBeVisible()
})
