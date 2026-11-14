import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SyncCard } from '../src/components/SyncCard'
import { relativeTime } from '../src/components/shared'

let mode: 'demo' | 'real', jobStatus: string, datasets: unknown[]
let requests: { url: string; method: string; body: unknown; headers: Headers }[]
const clients: QueryClient[] = []
beforeEach(() => {
  mode = 'demo'
  jobStatus = 'succeeded'
  datasets = []
  requests = []
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
      const data = url.endsWith('/sync/status')
        ? { datasets, active_jobs: [] }
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
it('real-mode sync posts once, polls the job, and refreshes v2 data', async () => {
  mode = 'real'
  const client = mount()
  client.setQueryData(['v2', 'sentinel'], 1)
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
  expect(client.getQueryState(['v2', 'sentinel'])?.isInvalidated).toBe(true)
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
it('compact variant is one line without the dataset list', async () => {
  mount(true)
  expect(await screen.findByTestId('sync-compact')).toBeInTheDocument()
  expect(screen.queryByTestId('sync-card')).toBeNull()
  expect(screen.queryByText('No dataset has a completed local sync.')).toBeNull()
})
