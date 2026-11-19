import { EXCEPTION_PROMPT } from '../src/coachPrompts'
import { useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CheckinModalV2 } from '../src/pages/CheckinModalV2'
import { qk } from '../src/api/queryKeys'
import type { CheckinRequest } from '../src/api/types/checkins'

const rec = { operation: 'exception_review', reason: 'Open findings at caution or hold need an exception review', finding_ids: ['f1'], prompt: EXCEPTION_PROMPT }
let checkinExceptions: { new_finding_ids: string[]; review_recommended: (typeof rec)[] }
let requests: {
  url: string
  method: string
  body: Record<string, unknown> | null
  headers: Headers
}[]
let failPosts: number, completed: boolean
let failFindings = false
let errorStatus = 500
const close = vi.fn()
const clients: QueryClient[] = []
beforeEach(() => {
  checkinExceptions = { new_finding_ids: ['f1'], review_recommended: [rec] }
  requests = []
  failFindings = false
  failPosts = 0
  completed = false
  errorStatus = 500
  close.mockReset()
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
      if (method === 'GET' && url === '/api/v1/exceptions' && failFindings)
        return { ok: false, status: 500, json: async () => ({ error: { code: 'request_failed', message: 'Findings unavailable' } }) }
      if (method === 'POST' && failPosts-- > 0)
        return {
          ok: false,
          status: errorStatus,
          json: async () => ({
            error: {
              code: 'request_failed',
              message: errorStatus === 422 ? 'severity must be ≤ 10' : 'Server error',
            },
          }),
        }
      const completion = {
        session_uid: 's1',
        status: completed ? 'completed_as_planned' : 'completed_modified',
        version: 2,
        activity_id: 'a1',
      }
      const data = url.endsWith('/execution')
        ? { completion }
        : url.includes('/completions/')
          ? { ...completion, version: 3 }
          : method === 'POST'
            ? { id: 'checkin', exceptions: checkinExceptions }
            : url.includes('/exceptions') ? { findings: [{ id: 'f1', severity: 'caution', category: 'accumulated_fatigue', status: 'open', summary: 'Fatigue 7 today.' }, { id: 'f9', severity: 'observe', category: 'accumulated_fatigue', status: 'open', summary: 'Older finding.' }] } : {}
      return {
        ok: true,
        status: method === 'POST' ? 201 : 200,
        json: async () => ({ schema_version: 'v1', mode: 'demo', data_revision: 1, data }),
      }
    }),
  )
})
afterEach(() => {
  cleanup()
  clients.forEach((c) => c.clear())
  clients.length = 0
  vi.unstubAllGlobals()
})
function mount(request?: CheckinRequest) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  clients.push(client)
  render(
    <QueryClientProvider client={client}>
      <CheckinModalV2 request={request} close={close} />
    </QueryClientProvider>,
  )
  return client
}
const postRun = (): CheckinRequest => ({
  kind: 'post_run',
  activityId: 'a1',
  prompt: {
    id: 'p1',
    kind: 'rpe',
    activity_id: 'a1',
    session_uid: null,
    opens_at: '2026-11-10T13:00:00Z',
    closes_at: null,
    status: 'open',
  },
})
const change = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
const posts = () => requests.filter((r) => r.method === 'POST')

it('exception check-in shows new findings and the coach prompt', async () => {
  const client = mount()
  expect(screen.getByRole('dialog', { name: 'Record check-in' })).toBeInTheDocument()
  change('Fatigue (0–10)', '7')
  change('Illness', 'none')
  change('Gait change?', 'no')
  fireEvent.click(screen.getByRole('button', { name: 'No' }))
  fireEvent.click(screen.getByRole('button', { name: 'Heat' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save check-in' }))
  expect(await screen.findByText('Check-in saved')).toBeInTheDocument()
  expect(posts()).toHaveLength(1)
  expect(posts()[0].url).toBe('/api/v1/v2/checkins')
  expect(posts()[0].headers.get('X-Local-Request')).toBe('1')
  expect(posts()[0].body).toMatchObject({
    kind: 'exception',
    fatigue: 7,
    illness: 'none',
    gait_change: 'no',
    context_tags: ['heat'],
    symptoms: [],
    activity_id: null,
    prompt_id: null,
    note: null,
  })
  expect(posts()[0].body?.idempotency_key).toBeTruthy()
  expect(await screen.findByText('Fatigue 7 today.')).toBeInTheDocument()
  expect(screen.getByText('Caution')).toBeInTheDocument()
  expect(screen.getByText(rec.reason)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Copy prompt' })).toBeInTheDocument()
  expect(screen.queryByText('Older finding.')).toBeNull()
  expect(screen.queryByText('Modify')).toBeNull()
  expect(screen.queryByText(/Coach review suggested/)).toBeNull()
  expect(client.getQueryState(qk.exceptions)).toBeDefined()
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  expect(close).toHaveBeenCalledTimes(1)
})

it('pain rows preserve site side severity and timing', async () => {
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Yes' }))
  change('Where?', 'posterior tibial tendon')
  change('Severity (0–10)', '3')
  change('When did it start?', 'next_morning')
  fireEvent.click(screen.getByRole('button', { name: 'Add another site' }))
  expect(document.getElementById('symptom-1-site')).toBeInTheDocument()
  fireEvent.click(screen.getAllByRole('button', { name: 'Remove' })[1])
  fireEvent.click(screen.getByRole('button', { name: 'Save check-in' }))
  await screen.findByText('Check-in saved')
  expect(posts()[0].body?.symptoms).toEqual([
    { site: 'posterior tibial tendon', side: 'left', severity: 3, timing: 'next_morning' },
  ])
})

it('validates required report and pain details', async () => {
  mount()
  fireEvent.click(screen.getByRole('button', { name: 'Save check-in' }))
  expect(await screen.findByText('Report at least one item.')).toBeInTheDocument()
  expect(posts()).toHaveLength(0)
  fireEvent.click(screen.getByRole('button', { name: 'Yes' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save check-in' }))
  expect(await screen.findByText('Enter where it hurts.')).toBeInTheDocument()
  expect(posts()).toHaveLength(0)
  change('Where?', 'ankle')
  change('Severity (0–10)', '11')
  fireEvent.click(screen.getByRole('button', { name: 'Save check-in' }))
  expect(await screen.findByText('Severity must be between 0 and 10.')).toBeInTheDocument()
  expect(posts()).toHaveLength(0)
})

it('retry reuses the entire frozen request including observed time and key', async () => {
  failPosts = 1
  mount()
  change('Fatigue (0–10)', '7')
  fireEvent.click(screen.getByRole('button', { name: 'Save check-in' }))
  await screen.findByText('Server error')
  fireEvent.click(screen.getByRole('button', { name: 'Save check-in' }))
  await screen.findByText('Check-in saved')
  expect(posts()).toHaveLength(2)
  expect(posts()[1].body).toEqual(posts()[0].body)
})

it('editing a failed request creates a new key and body', async () => {
  failPosts = 1
  mount()
  change('Fatigue (0–10)', '7')
  fireEvent.click(screen.getByRole('button', { name: 'Save check-in' }))
  await screen.findByText('Server error')
  change('Fatigue (0–10)', '8')
  fireEvent.click(screen.getByRole('button', { name: 'Save check-in' }))
  await screen.findByText('Check-in saved')
  expect(posts()[1].body?.idempotency_key).not.toBe(posts()[0].body?.idempotency_key)
  expect(posts()[1].body?.fatigue).toBe(8)
})

it('post-run RPE saves before reason and check-in without inventing completion status', async () => {
  mount(postRun())
  await screen.findByLabelText('What changed the session? (optional)')
  expect(
    screen.getByText('How hard was the entire session, 0 = rest and 10 = maximal?'),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '6' }))
  change('What changed the session? (optional)', 'fatigue')
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(close).toHaveBeenCalledTimes(1))
  const writes = requests.filter((r) => r.method !== 'GET')
  expect(writes.map((r) => [r.method, r.url])).toEqual([
    ['PUT', '/api/v1/activities/a1/rpe'],
    ['PUT', '/api/v1/calendar/completions/s1'],
    ['POST', '/api/v1/v2/checkins'],
  ])
  expect(writes[0].body).toEqual({ rpe: 6 })
  expect(writes[1].body).toEqual({
    expected_version: 2,
    activity_id: 'a1',
    modification_reason: 'fatigue',
    reason_note: null,
  })
  expect(writes[2].body).toMatchObject({
    kind: 'post_run',
    activity_id: 'a1',
    prompt_id: 'p1',
    symptoms: [],
    context_tags: [],
  })
})

it('post-run retry skips already successful writes', async () => {
  failPosts = 1
  mount(postRun())
  await screen.findByLabelText('What changed the session? (optional)')
  fireEvent.click(screen.getByRole('button', { name: '6' }))
  change('What changed the session? (optional)', 'fatigue')
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await screen.findByText('Server error')
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(close).toHaveBeenCalledTimes(1))
  expect(requests.filter((r) => r.method === 'PUT')).toHaveLength(2)
  expect(posts()).toHaveLength(2)
  expect(posts()[1].body).toEqual(posts()[0].body)
})

it('post-run without prompt or note only saves RPE', async () => {
  completed = true
  mount({ ...postRun(), prompt: null })
  await waitFor(() => expect(screen.queryByText('Loading session…')).not.toBeInTheDocument())
  expect(screen.queryByLabelText('What changed the session? (optional)')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '7' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(close).toHaveBeenCalledTimes(1))
  expect(posts()).toHaveLength(0)
  expect(requests.filter((r) => r.method === 'PUT').map((r) => r.body)).toEqual([{ rpe: 7 }])
})

it('delayed follow-up requires pain and gait then links the correct prompt', async () => {
  const request = postRun()
  request.kind = 'delayed_followup'
  request.prompt = { ...request.prompt!, id: 'p2', kind: 'delayed_symptom' }
  mount(request)
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await screen.findByText('Answer the pain question.')
  fireEvent.click(screen.getByRole('button', { name: 'No' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await screen.findByText('Answer the gait question.')
  expect(posts()).toHaveLength(0)
  change('Gait change?', 'no')
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(close).toHaveBeenCalledTimes(1))
  expect(posts()[0].body).toMatchObject({
    kind: 'delayed_followup',
    gait_change: 'no',
    symptoms: [],
    activity_id: 'a1',
    prompt_id: 'p2',
  })
})

it('shows server validation messages', async () => {
  failPosts = 1
  errorStatus = 422
  mount()
  change('Fatigue (0–10)', '7')
  fireEvent.click(screen.getByRole('button', { name: 'Save check-in' }))
  expect(await screen.findByText('severity must be ≤ 10')).toBeInTheDocument()
})

it('supports Escape and keeps keyboard focus inside the check-in', () => {
  mount()
  const dialog = screen.getByRole('dialog')
  const first = screen.getByLabelText('Fatigue (0–10)')
  const last = screen.getByRole('button', { name: 'Close' })
  expect(first).toHaveFocus()
  fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })
  expect(last).toHaveFocus()
  fireEvent.keyDown(last, { key: 'Tab' })
  expect(first).toHaveFocus()
  fireEvent.keyDown(dialog, { key: 'Escape' })
  expect(close).toHaveBeenCalledTimes(1)
})

it.each([
  ['current check-in', CheckinModalV2],
])('%s restores focus to its opener after Escape', async (_name, Checkin) => {
  function Harness() {
    const [open, setOpen] = useState(false)
    return (
      <>
        <button onClick={() => setOpen(true)}>Open check-in</button>
        {open && <Checkin close={() => setOpen(false)} />}
      </>
    )
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  )
  const opener = screen.getByRole('button', { name: 'Open check-in' })
  opener.focus()
  fireEvent.click(opener)
  const dialog = screen.getByRole('dialog', { name: 'Record check-in' })
  expect(dialog.contains(document.activeElement)).toBe(true)
  fireEvent.keyDown(dialog, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  await waitFor(() => expect(opener).toHaveFocus())
  expect(posts()).toHaveLength(0)
})

it('exception check-in without findings is logged for Sunday', async () => {
  checkinExceptions = { new_finding_ids: [], review_recommended: [] }
  mount()
  change('Fatigue (0–10)', '7')
  change('Illness', 'none')
  change('Gait change?', 'no')
  fireEvent.click(screen.getByRole('button', { name: 'No' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save check-in' }))
  expect(await screen.findByText('Logged for your Sunday review')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Copy prompt' })).toBeNull()
  expect(requests.some(r => r.method === 'GET' && r.url === '/api/v1/exceptions')).toBe(false)
})

it('retries findings after a saved check-in without saving again', async () => {
  failFindings = true
  mount()
  change('Fatigue (0–10)', '7')
  fireEvent.click(screen.getByRole('button', { name: 'Save check-in' }))
  expect(await screen.findByText(/Check-in saved, but findings could not load/)).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Check-in saved' })).toBeInTheDocument()
  expect(screen.getByText(rec.reason)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Copy prompt' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Save check-in' })).toBeNull()
  expect(close).not.toHaveBeenCalled()
  expect(posts()).toHaveLength(1)
  const saved = posts()[0].body
  failFindings = false
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  expect(await screen.findByText('Fatigue 7 today.')).toBeInTheDocument()
  expect(screen.queryByText(/Check-in saved, but findings could not load/)).toBeNull()
  expect(requests.filter(r => r.method === 'GET' && r.url === '/api/v1/exceptions')).toHaveLength(2)
  expect(posts()).toHaveLength(1)
  expect(posts()[0].body).toEqual(saved)
  expect(saved?.idempotency_key).toBeTruthy()
  expect(screen.getByText(rec.reason)).toBeInTheDocument()
})
