import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App, parseHash } from '../src/App'

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  BarChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  LineChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Bar: () => null,
  Line: () => null,
  CartesianGrid: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
}))

let responseMode: 'demo' | 'real' = 'demo'
let importItems: unknown[] = []
const wrap = (data: unknown) => ({
  schema_version: 'v1',
  data_revision: 3,
  mode: responseMode,
  data,
})
const profile = {
  planning_authority: 'calendar' as 'legacy' | 'calendar',
  version: 1,
  timezone: 'America/New_York',
  cycle_anchor: '2026-11-02',
  anchor_confirmed: true,
  strength_days_confirmed: true,
  scheduled_strength_days: [0, 4],
  strength_schedule_mode: 'weekly',
  strength_week_a_start: null,
  strength_week_a_days: [],
  strength_week_b_days: [],
  mobility_week_a_days: [],
  mobility_week_b_days: [],
  mobility_optional_days: [],
  facts: {},
  preferences: {},
  unknowns: [],
}
const calendarView = {
  today: '2026-11-15',
  timezone: 'America/New_York',
  start: '2026-11-08',
  end: '2026-11-28',
  version: 1,
  head: 1,
  undo: null,
  last_planned_date: '2026-11-28',
  sessions: [],
  completions: [],
}
const weeklyProjection = {
  week_start: '2026-11-09',
  week_end: '2026-11-15',
  today: '2026-11-15',
  timezone: 'America/New_York',
  calendar_version: 1,
  actual_distance_m: 5000,
  remaining_distance_m: 0,
  projected_distance_m: 5000,
  actual_runs: 1,
  remaining_runs: 0,
  estimated_runs: 0,
  missing_actual_runs: 0,
  missing_planned_runs: 0,
  unrecorded_past_runs: 0,
  pace_sample_count: 1,
  pace_mps: 3,
  plan_available: true,
  plan_through: '2026-11-28',
  activity_coverage_complete: true,
}
const execution = {
  activity: {
    id: 'run-1',
    start_at: '2026-11-14T12:00:00Z',
    end_at: '2026-11-14T12:30:00Z',
    local_date: '2026-11-14',
    sport: 'running',
    distance_m: 5000,
    timer_s: 1800,
    elapsed_s: 1800,
    fit_status: 'not_fetched',
  },
  planned: null,
  completion: null,
  laps: [],
  watch_steps: [],
  planned_actual: null,
  aerobic: null,
  intervals: null,
  intensity: null,
  rpe: { effective: null, source: null, manual: null, garmin_fit: null, srpe_load_au: null },
  symptoms: [],
}
const summary = {
  as_of: '2026-11-15',
  timezone: 'America/New_York',
  metric_version: 'analytics.v1',
  window: { start_date: '2026-10-19', end_date: '2026-11-15' },
  current_week: { distance_m: 11265.408, run_count: 2, missing_distance_count: 0 },
  rolling_7: { distance_m: 11265.408, run_count: 2, missing_distance_count: 0 },
  rolling_14: { distance_m: 16093.44, run_count: 4, missing_distance_count: 0 },
  selected: {
    distance_m: 16093.44,
    run_count: 4,
    missing_distance_count: 0,
    longest_elapsed_s: 700,
    strength_count: 2,
    strength_duration_s: 3600,
    strength_unknown_duration_count: 1,
    low_impact_count: 0,
    low_impact_duration_s: 0,
    workout_distribution: { easy: 1, quality: 0, long: 1, other: 0, unknown: 2 },
  },
  weekly: [
    {
      start_date: '2026-11-09',
      end_date: '2026-11-15',
      distance_m: 11265.408,
      run_count: 2,
      missing_distance_count: 0,
      strength_count: 1,
    },
  ],
  recent_runs: [],
  coverage: [{ dataset: 'activities', status: 'partial', reason: 'import in progress' }],
}
const recovery = {
  timezone: 'America/New_York',
  series: { sleep: [], hrv: [], resting_hr: [] },
  trailing_7: {
    sleep: { mean: null, n: 0, days: 7 },
    hrv: { mean: null, n: 0, days: 7 },
    resting_hr: { mean: null, n: 0, days: 7 },
  },
  coverage: [],
}

const proposalId = '11111111-1111-4111-8111-111111111111'
const emptyProposal = {
  id: proposalId,
  operation: 'review_rolling_plan',
  status: 'pending',
  summary: 'Keep this plan',
  rationale: 'Continue',
  confidence: { decision: 'moderate', evidence: 'moderate', data: 'moderate' },
  head: 1,
  is_current: true,
  revision: 1,
  revisions: [],
  changes: [],
  anchor_changes: [],
  block_change: null,
  evidence_ids: [],
  policy_ids: [],
  recipe_ids: [],
  validation_errors: [],
}
let requests: { url: string; method: string; body: unknown; headers: Headers }[] = []
let profileRecord = { ...profile }
let activityItems: unknown[] = []
let readyStatus = 200
let profileStatus = 200
beforeEach(() => {
  requests = []
  profileRecord = { ...profile }
  activityItems = []
  readyStatus = 200
  profileStatus = 200
  responseMode = 'demo'
  importItems = []
  window.location.hash = ''
  localStorage.clear()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input),
        method = init?.method || 'GET'
      requests.push({
        url,
        method,
        body: init?.body ? JSON.parse(String(init.body)) : null,
        headers: new Headers(init?.headers),
      })
      if (url.includes('/health/ready') && readyStatus !== 200)
        return {
          ok: false,
          status: 503,
          json: async () => wrap({ status: 'unavailable', database: false }),
        } as Response
      if (url.includes('/profile') && method === 'GET' && profileStatus !== 200)
        return {
          ok: false,
          status: 500,
          json: async () => ({ error: { code: 'internal_error', message: 'boom' } }),
        } as Response
      if (url.endsWith('/calendar/weekly-projection'))
        return { ok: true, status: 200, json: async () => wrap(weeklyProjection) } as Response
      if (url.includes('/profile') && method === 'PUT')
        profileRecord = {
          ...profileRecord,
          ...JSON.parse(String(init?.body)),
          version: profileRecord.version + 1,
        }
      const data = url.includes(`/coach/proposals/${proposalId}`)
        ? emptyProposal
        : url.includes('/calendar/versions')
          ? { items: [] }
          : url.endsWith('/calendar')
            ? calendarView
            : url.includes('/prompts')
              ? { items: [] }
              : url.includes('/blocks/active')
                ? null
                : url.includes('/strength-routine')
                  ? { version: 0, slots: [], schedule: profileRecord }
                  : url.includes('/exceptions')
                    ? null
                    : url.includes('/execution')
                      ? execution
                      : url.includes('/sync/jobs/')
                        ? { id: 'job-1', dataset: 'activities', status: 'succeeded' }
                        : url.includes('/sync') && method === 'POST'
                          ? { jobs: [{ id: 'job-1', dataset: 'activities', status: 'queued' }] }
                          : url.includes('/sync/status')
                            ? { datasets: [], active_jobs: [] }
                            : url.includes('/weekly-summary')
                              ? {
                                  week_start: '2026-11-09',
                                  week_end: '2026-11-15',
                                  summary: summary.selected,
                                  checkins: [],
                                  questions: [],
                                  coverage: [],
                                }
                              : url.includes('/summary')
                                ? url.includes('as_of=2020-12-31')
                                  ? {
                                      ...summary,
                                      window: { start_date: '2020-01-02', end_date: '2020-12-31' },
                                    }
                                  : summary
                                : url.includes('/recovery')
                                  ? recovery
                                  : url.includes('/profile')
                                    ? profileRecord
                                    : url.includes('/health/ready')
                                      ? { status: 'ok', database: true }
                                      : url.includes('/checkins') && method === 'POST'
                                        ? { id: 'checkin-1' }
                                        : url.includes('/activities/')
                                          ? activityItems[0]
                                          : url.includes('/activities')
                                            ? {
                                                items: activityItems,
                                                next_cursor: null,
                                                timezone: 'America/New_York',
                                                coverage: [],
                                              }
                                            : url.includes('/imports')
                                              ? { items: importItems }
                                              : { items: [] }
      return { ok: true, status: 200, json: async () => wrap(data) } as Response
    }),
  )
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
function mount(client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

describe('authority shell', () => {
  it('opens keyboard-accessible mobile navigation and restores focus on Escape', async () => {
    mount()
    const opener = screen.getByRole('button', { name: 'Open menu' })
    opener.focus()
    fireEvent.click(opener)
    const dialog = screen.getByRole('dialog', { name: 'Navigation' })
    expect(
      within(dialog).getByRole('navigation', { name: 'Primary navigation' }),
    ).toBeInTheDocument()
    fireEvent.keyDown(dialog, { key: 'Escape' })
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: 'Navigation' })).not.toBeInTheDocument(),
    )
    await waitFor(() => expect(opener).toHaveFocus())
  })

  it('parses current routes and sends removed pages home', () => {
    for (const page of ['calendar', 'trends', 'block', 'settings', 'guide'])
      expect(parseHash(`#${page}`)).toEqual({ page, id: null })
    expect(parseHash('#activity/run%20one')).toEqual({ page: 'activity', id: 'run one' })
    expect(parseHash('#activity/%ZZ')).toEqual({ page: 'home', id: null })
    expect(parseHash('#activity/%2F')).toEqual({ page: 'home', id: null })
    expect(parseHash(`#proposal/${proposalId}`)).toEqual({ page: 'proposal', id: proposalId })
    for (const hash of ['#proposal/%ZZ', '#proposal/no-id', `#proposal/${proposalId}/extra`])
      expect(parseHash(hash)).toEqual({ page: 'home', id: null })
    for (const hash of ['#history', '#strength', '#coach', '#overview', '#cycle', '#unknown', ''])
      expect(parseHash(hash)).toEqual({ page: 'home', id: null })
  })
  it('opens calendar Home, follows navigation hashes, and uses the v2 check-in', async () => {
    mount()
    expect(await screen.findByTestId('today-card')).toBeInTheDocument()
    expect(screen.getAllByTestId('strip-day')).toHaveLength(14)
    expect(screen.queryByRole('button', { name: 'Cycle' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Calendar' }))
    expect(window.location.hash).toBe('#calendar')
    expect(await screen.findByRole('heading', { name: 'Calendar.' })).toBeInTheDocument()
    window.location.hash = '#unknown'
    fireEvent(window, new Event('hashchange'))
    expect(await screen.findByTestId('today-card')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button', { name: 'Record check-in' })[0])
    expect(screen.getByRole('dialog', { name: 'Record check-in' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Something to report?' })).toBeInTheDocument()
  })
  it('routes an activity deep link and keeps existing settings controls', async () => {
    profileRecord = { ...profile, planning_authority: 'calendar' }
    window.location.hash = '#activity/run-1'
    mount()
    expect(await screen.findByRole('heading', { name: /Run ·/ })).toBeInTheDocument()
    expect(requests.some((x) => x.url.includes('/activities/run-1/execution'))).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }))
    expect(await screen.findByRole('heading', { name: 'Settings', level: 1 })).toBeInTheDocument()
    expect(await screen.findByLabelText('Display timezone')).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  })
  it('opens a saved proposal without applying it and navigates to the block', async () => {
    window.location.hash = `#proposal/${proposalId}`
    mount()
    expect(await screen.findByText('Keep this plan')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Accept (no changes)' })).toBeInTheDocument()
    expect(requests.some((request) => request.method === 'POST')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Training block' }))
    expect(
      await screen.findByRole('heading', { name: 'No active training block' }),
    ).toBeInTheDocument()
    expect(window.location.hash).toBe('#block')
  })
  it('shows only the five lean navigation items and a Guide link', async () => {
    mount()
    await screen.findByTestId('today-card')
    const primary = screen.getByRole('navigation', { name: 'Primary navigation' })
    expect(
      within(primary)
        .getAllByRole('button')
        .map((button) => button.textContent),
    ).toEqual(['Home', 'Calendar', 'Trends', 'Training block', 'Settings'])
    expect(screen.getByRole('link', { name: 'Guide' })).toHaveAttribute('href', '#guide')
    for (const name of ['History', 'Strength', 'Coaching history'])
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
  })
  it('shows the database banner when readiness fails', async () => {
    readyStatus = 503
    mount()
    expect(
      await screen.findByText('Database unavailable — start it with make db-start'),
    ).toBeInTheDocument()
  })
  it('shows profile load errors instead of loading forever', async () => {
    profileStatus = 500
    mount()
    expect(
      await screen.findByText(/Could not load the training workspace: boom/),
    ).toBeInTheDocument()
    expect(screen.queryByText('Loading training workspace…')).not.toBeInTheDocument()
  })
  it('asks for the cutover in a legacy workspace', async () => {
    profileRecord = { ...profile, planning_authority: 'legacy' }
    mount()
    expect(await screen.findByTestId('cutover-required')).toBeInTheDocument()
    expect(screen.queryByTestId('today-card')).not.toBeInTheDocument()
    expect(requests.some((request) => request.url.endsWith('/calendar'))).toBe(false)
  })
})
