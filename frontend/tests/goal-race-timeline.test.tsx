import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { ActiveBlock, EventBlock, RaceEvent, TargetEvent } from '../src/api/types/blocks'
import { GoalRaceTimeline } from '../src/components/GoalRaceTimeline'

const half: TargetEvent = {
  id: 'e1',
  name: 'NYC Half',
  event_date: '2027-03-14',
  distance_m: 21098,
  purpose: 'pr',
  goal_time_s: 6300,
  rank: 1,
}
const block: ActiveBlock = {
  id: 'v1',
  block_uid: 'b1',
  version: 1,
  status: 'active',
  objective: 'Threshold durability',
  why: [],
  maintained_qualities: [],
  non_goals: [],
  eligible_recipe_ids: [],
  progression_dimension: 'duration',
  constraints: [],
  start_date: '2026-11-23',
  review_date: '2026-12-20',
  indicators: [],
  early_review_triggers: [],
  objective_status: 'unresolved',
  created_at: '2026-11-19T12:00:00Z',
  proposal_id: 'p1',
  legacy_text: null,
  sources: [],
  benchmark: null,
  target_event_id: half.id,
  benchmark_status: {
    status: 'not_set',
    match_method: null,
    activity_id: null,
    event_id: null,
    local_date: null,
    distance_m: null,
    result_s: null,
    rpe: null,
    scheduled_date: null,
    evidence_at: null,
  },
  build_outline: [
    { emphasis: 'threshold durability', weeks: 4 },
    { emphasis: 'half-marathon-specific endurance', weeks: 5 },
    { emphasis: 'sharpening, taper, race', weeks: 4 },
  ],
  target_event_status: 'current',
  target_event: half,
}
const blocks: EventBlock[] = [
  {
    block_uid: 'b0',
    version: 2,
    status: 'completed',
    objective: 'Aerobic base',
    start_date: '2026-10-26',
    review_date: '2026-11-22',
    benchmark: null,
    build_outline: [],
  },
  { ...block, benchmark: null, build_outline: block.build_outline ?? [] },
]
const events: RaceEvent[] = [
  { ...half, status: 'planned', result_s: null, version: 1 },
  {
    ...half,
    id: 'e2',
    name: 'Turkey Trot 10K',
    event_date: '2027-01-30',
    distance_m: 10000,
    goal_time_s: 2700,
    rank: 2,
    status: 'planned',
    result_s: null,
    version: 1,
  },
  {
    ...half,
    id: 'e3',
    name: 'Old 5K',
    event_date: '2026-10-25',
    distance_m: 5000,
    rank: null,
    status: 'completed',
    result_s: 1500,
    version: 1,
  },
]

const clients: QueryClient[] = []
function mount(update: Partial<ActiveBlock> = {}, today = '2026-11-19', relatedBlocks = blocks) {
  const fetcher = vi.fn(async (input: string) => ({
    ok: true,
    json: async () => ({
      schema_version: 'v1',
      mode: 'demo',
      data_revision: 1,
      data: { items: input.endsWith('/blocks') ? relatedBlocks : events },
    }),
  }))
  vi.stubGlobal('fetch', fetcher)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  render(
    <QueryClientProvider client={client}>
      <GoalRaceTimeline block={{ ...block, ...update }} today={today} unit="mi" />
    </QueryClientProvider>,
  )
  return fetcher
}

afterEach(() => {
  cleanup()
  clients.forEach((client) => client.clear())
  clients.length = 0
  vi.unstubAllGlobals()
})

it('lists blocks, outline steps, events, and race day in order', async () => {
  mount()
  await screen.findByText(/Turkey Trot 10K/)
  await screen.findByText(/Aerobic base/)
  const rows = screen.getAllByTestId('timeline-row')
  expect(rows.map((row) => row.dataset.kind)).toEqual([
    'earlier',
    'current',
    'outline',
    'outline',
    'event',
    'outline',
    'race',
  ])
  expect(rows.map((row) => row.textContent)).toEqual([
    'Oct 26–Nov 22 · Aerobic base · Done',
    'Nov 23–Dec 20 · Threshold durability · Current block',
    '≈Dec 21–Jan 17 · threshold durability · provisional',
    '≈Jan 18–Feb 21 · half-marathon-specific endurance · provisional',
    'Jan 30 · Turkey Trot 10K · Race it (PR attempt) · goal 45:00',
    '≈Feb 22–Mar 21 · sharpening, taper, race · provisional',
    'Mar 14 · NYC Half · Race day',
  ])
  expect(screen.queryByText(/Old 5K/)).toBeNull()
  expect(screen.getByText('Direction only; set at each block review')).toBeInTheDocument()
})

it('shows the goal race header with weeks away', () => {
  mount()
  expect(screen.getByRole('heading')).toHaveTextContent(
    'NYC Half · Mar 14, 2027 · 13.1 mi · Race it (PR attempt) · goal 1:45:00 · 16 weeks away',
  )
})

it('counts days inside two weeks', () => {
  mount({}, '2027-03-05')
  expect(screen.getByRole('heading')).toHaveTextContent(/9 days away$/)
})

it('explains a changed target', () => {
  mount({ target_event_status: 'changed' })
  expect(screen.getByRole('status')).toHaveTextContent(
    'Your goal race changed. The next Sunday review will run a block review.',
  )
})

it('explains an unset target without requesting past blocks', async () => {
  const fetcher = mount({ target_event_status: 'unset', target_event: null })
  expect(screen.getByRole('status')).toHaveTextContent(
    'This block was planned before you ranked events. The next Sunday review sets its goal race.',
  )
  expect(screen.getByRole('heading')).toHaveTextContent('No goal race for this block')
  await screen.findByText(/Turkey Trot 10K/)
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/v1/events'])
})

it('points to Settings when there are no events', () => {
  mount({ target_event_status: 'none', target_event: null })
  expect(screen.getByRole('status')).toHaveTextContent(
    'No upcoming events. Add one in Settings → Events.',
  )
  expect(screen.getByRole('link', { name: 'Settings → Events' })).toHaveAttribute(
    'href',
    '#settings',
  )
})

it('keeps prior phases of the same block and skips the exact current version', async () => {
  const current = { ...blocks[1], version: 5 }
  mount({ version: current.version }, '2026-11-19', [
    { ...blocks[0], block_uid: current.block_uid, version: 1 },
    { ...blocks[0], block_uid: current.block_uid, version: 3, objective: 'Durability' },
    current,
  ])
  await screen.findByText(/Aerobic base · Done/)
  expect(
    screen
      .getAllByTestId('timeline-row')
      .slice(0, 3)
      .map((row) => row.textContent),
  ).toEqual([
    'Oct 26–Nov 22 · Aerobic base · Done',
    'Oct 26–Nov 22 · Durability · Done',
    'Nov 23–Dec 20 · Threshold durability · Current block',
  ])
  expect(screen.queryByText(/Threshold durability · Done/)).toBeNull()
})

it.each(['', 'unavailable'])(
  'omits the countdown for calendar date %j and a missing status',
  (today) => {
    mount({ target_event_status: undefined }, today)
    expect(screen.getByRole('heading')).toHaveTextContent(/goal 1:45:00$/)
    expect(screen.queryByRole('status')).toBeNull()
  },
)
