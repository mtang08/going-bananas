import { qk } from '../src/api/queryKeys'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SyncCard } from '../src/components/SyncCard'
import { relativeTime } from '../src/components/shared'
import type { TreadmillReview } from '../src/api/types/sync'

let activeJobs: { id: string; dataset: string; status: string }[]
let mode: 'demo' | 'real', jobStatus: string, datasets: unknown[]
let requests: { url: string; method: string; body: unknown; headers: Headers }[]
let treadmillRun: TreadmillReview | null
let confirmError: boolean
const clients: QueryClient[] = []
beforeEach(() => {
  mode = 'demo'
  jobStatus = 'complete'
  datasets = []
  activeJobs = []
  requests = []
  treadmillRun = null
  confirmError = false
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input),
        method = init?.method ?? 'GET'
      requests.push({
        url,
        method,
        body: init?.body ? JSON.parse(String(init.body)) : null,
        headers: new Headers(init?.headers),
      })
      if (url.endsWith('/sync/treadmill-review/run-1')) {
        if (method === 'POST' && confirmError) {
          return {
            ok: false,
            status: 409,
            json: async () => ({
              error: { code: 'treadmill_review_reload_required', message: 'Reload this run.' },
            }),
          } as Response
        }
        const data = method === 'POST' ? { activity_id: 'run-1' } : treadmillRun
        if (method === 'POST') treadmillRun = null
        return {
          ok: true,
          status: 200,
          json: async () => ({ schema_version: 'v1', mode, data }),
        } as Response
      }
      const data = url.endsWith('/sync/status')
        ? {
            datasets,
            active_jobs: activeJobs,
            pending_treadmill_runs: treadmillRun
              ? [{ id: treadmillRun.id, local_date: treadmillRun.local_date }]
              : [],
          }
        : url.includes('/sync/jobs/')
          ? { id: 'job-1', dataset: 'activities', status: jobStatus }
          : url.endsWith('/sync') && method === 'POST'
            ? { jobs: [{ id: 'job-1', dataset: 'activities', status: 'queued' }] }
            : null
      return {
        ok: true,
        status: 200,
        json: async () => ({ schema_version: 'v1', mode, data_revision: 1, data }),
      } as Response
    }),
  )
})
afterEach(() => {
  cleanup()
  clients.forEach((c) => c.clear())
  clients.length = 0
  vi.unstubAllGlobals()
})
function mount(compact = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  clients.push(client)
  render(
    <QueryClientProvider client={client}>
      <SyncCard compact={compact} />
    </QueryClientProvider>,
  )
  return client
}

it('relativeTime formats minutes, hours and days', () => {
  const now = new Date('2026-11-13T12:00:00Z')
  expect(relativeTime('2026-11-13T11:55:00Z', now)).toBe('5 min ago')
  expect(relativeTime('2026-11-13T09:00:00Z', now)).toBe('3 h ago')
  expect(relativeTime('2026-11-12T10:00:00Z', now)).toBe('1 day ago')
  expect(relativeTime('bad')).toBe('unknown')
})
it('shows the latest successful sync and hides Sync now outside real mode', async () => {
  datasets = [
    {
      dataset: 'activities',
      status: 'succeeded',
      last_success_at: new Date(Date.now() - 3 * 3600_000).toISOString(),
    },
    {
      dataset: 'sleep',
      status: 'succeeded',
      last_success_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    },
  ]
  mount()
  expect(await screen.findByText('Last sync 5 min ago')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Sync now' })).toBeNull()
})
it('real-mode sync posts once, polls the job, and refreshes plan data', async () => {
  mode = 'real'
  const client = mount()
  client.setQueryData(qk.calendar, 1)
  client.setQueryData(qk.goals, 1)
  fireEvent.click(await screen.findByRole('button', { name: 'Sync now' }))
  expect(
    await screen.findByText('Sync finished. Training data has been refreshed.'),
  ).toBeInTheDocument()
  const posts = requests.filter((r) => r.method === 'POST')
  expect(posts).toHaveLength(1)
  expect(posts[0].url.endsWith('/sync')).toBe(true)
  expect(posts[0].body).toEqual({})
  expect(posts[0].headers.get('X-Local-Request')).toBe('1')
  expect(requests.some((r) => r.method === 'GET' && r.url.includes('/sync/jobs/job-1'))).toBe(true)
  expect(client.getQueryState(qk.calendar)?.isInvalidated).toBe(true)
  expect(client.getQueryState(qk.goals)?.isInvalidated).toBe(false)
})
it('checks aggregate status while a job runs and reads its result once after it finishes', async () => {
  mode = 'real'
  const client = mount()
  const sync = await screen.findByRole('button', { name: 'Sync now' })
  activeJobs = [{ id: 'job-1', dataset: 'activities', status: 'running' }]
  fireEvent.click(sync)
  expect(await screen.findByText('activities: running')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Sync in progress' })).toBeDisabled()
  const lookups = () => requests.filter((r) => r.url.includes('/sync/jobs/'))
  expect(lookups()).toHaveLength(0)

  activeJobs = []
  await client.refetchQueries({ queryKey: qk.syncBatch(['job-1']), exact: true })
  expect(await screen.findByText('Sync finished. Training data has been refreshed.')).toBeVisible()
  expect(lookups()).toHaveLength(1)
  expect(requests.filter((r) => r.method === 'POST')).toHaveLength(1)
  expect(screen.getByRole('button', { name: 'Sync now' })).toBeEnabled()
})

it('reports a failed job', async () => {
  mode = 'real'
  jobStatus = 'failed'
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Sync now' }))
  expect(
    await screen.findByText('One or more datasets failed. Check the dataset status and retry.'),
  ).toBeInTheDocument()
})
it('stops tracking when a dataset finishes with partial data', async () => {
  mode = 'real'
  jobStatus = 'partial'
  const client = mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Sync now' }))
  expect(
    await screen.findByText('Sync finished with incomplete data. Check the dataset status.'),
  ).toBeInTheDocument()
  expect(client.getQueryData(qk.syncPending)).toEqual([])
  expect(screen.getByRole('button', { name: 'Sync now' })).toBeEnabled()
})
it('compact variant is one line without the dataset list', async () => {
  mount(true)
  expect(await screen.findByTestId('sync-compact')).toBeInTheDocument()
  expect(screen.queryByTestId('sync-card')).toBeNull()
  expect(screen.queryByText('No dataset has a completed local sync.')).toBeNull()
})

function stagedTreadmillRun(): TreadmillReview {
  return {
    id: 'run-1',
    local_date: '2026-11-20',
    preview_token: 'preview',
    title: 'Treadmill intervals',
    distance_m: 7000,
    timer_s: 2400,
    intervals: [
      { lap_index: 1, timer_s: 180, intensity: 'active', recorded_pace_seconds_per_mile: 470 },
      { lap_index: 2, timer_s: 90, intensity: 'recovery', recorded_pace_seconds_per_mile: null },
    ],
  }
}

it('keeps recorded paces for untouched laps and imports the edited laps in one request', async () => {
  mode = 'real'
  treadmillRun = stagedTreadmillRun()
  const client = mount(true)
  client.setQueryData(qk.calendar, 1)
  fireEvent.click(await screen.findByRole('button', { name: /Review treadmill run.*Nov 20/ }))
  expect(await screen.findByText('Garmin pace 7:50 /mi')).toBeVisible()
  expect(screen.getByText('Garmin pace unavailable')).toBeVisible()
  const input = screen.getByRole('textbox', { name: 'Lap 2 corrected pace per mi' })
  const save = screen.getByRole('button', { name: 'Confirm and import' })
  fireEvent.change(input, { target: { value: '7:72' } })
  expect(save).toBeDisabled()
  fireEvent.change(input, { target: { value: '7:42' } })
  fireEvent.click(save)

  expect(await screen.findByText('Treadmill run imported.')).toBeVisible()
  expect(requests.filter(({ method }) => method === 'POST').map(({ body }) => body)).toEqual([
    { preview_token: 'preview', paces: [{ lap_index: 1, pace_seconds_per_mile: 462 }] },
  ])
  expect(screen.queryByRole('button', { name: /Review treadmill run.*Nov 20/ })).toBeNull()
  expect(client.getQueryState(qk.calendar)?.isInvalidated).toBe(true)
})

it('reloads an expired preview and clears edits tied to its laps', async () => {
  mode = 'real'
  treadmillRun = stagedTreadmillRun()
  confirmError = true
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /Review treadmill run.*Nov 20/ }))
  const input = await screen.findByRole('textbox', { name: 'Lap 2 corrected pace per mi' })
  fireEvent.change(input, { target: { value: '7:42' } })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm and import' }))
  const reload = await screen.findByRole('button', { name: 'Reload run' })
  expect(screen.getByRole('button', { name: 'Confirm and import' })).toBeDisabled()
  treadmillRun.preview_token = 'fresh'
  confirmError = false
  fireEvent.click(reload)
  await screen.findByRole('button', { name: 'Confirm and import' })
  expect(input).toHaveValue('')
  fireEvent.click(screen.getByRole('button', { name: 'Confirm and import' }))
  expect(await screen.findByText('Treadmill run imported.')).toBeVisible()
  expect(requests.filter(({ method }) => method === 'POST').at(-1)?.body).toEqual({
    preview_token: 'fresh',
    paces: [],
  })
})
