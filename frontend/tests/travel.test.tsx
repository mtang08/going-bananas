import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type {
  CalendarEvent,
  EventCategory,
  GcalStatus,
  ManualTripInput,
  Trip,
  TripPatch,
  TripStatus,
} from '../src/api/types/travel'
import { addDays } from '../src/lib/format'
import { Travel } from '../src/pages/settings/Travel'

const HOME = 'America/New_York'
const WEST = 'America/Los_Angeles'
const CONNECT_ERROR = 'Google Calendar access expired or was revoked. Run calendar-connect again.'
const CONFLICT = 'This trip changed since it loaded. The list was refreshed; try again.'
const counters = { created: 0, updated: 0, flagged: 0, deleted: 0 }
const clients: QueryClient[] = []
let mode: 'demo' | 'real'
let status: GcalStatus
let syncError: { status: number; code: string; message: string } | null
let tripConflict: boolean
let trips: Trip[]
let events: CalendarEvent[]
let requests: { url: string; method: string; body: unknown }[]

const trip = (id: string, status: TripStatus, start: string, extra: Partial<Trip> = {}): Trip => ({
  id,
  status,
  start_date: start,
  end_date: addDays(start, 4),
  destination_label: `City ${id}`,
  destination_tz: WEST,
  source: 'detected',
  confidence: 'high',
  edited: false,
  review_reason: status === 'needs_review' ? 'source_changed' : null,
  detected: {},
  running_access: null,
  gym_access: null,
  day_availability: [],
  travel_days: [],
  legs: [],
  version: 2,
  ...extra,
})
const calEvent = (id: string, extra: Partial<CalendarEvent> = {}): CalendarEvent => ({
  id,
  event_type: 'fromGmail',
  summary: `Event ${id}`,
  all_day: false,
  start_at: '2099-12-03T13:05:00+00:00',
  end_at: '2099-12-03T19:30:00+00:00',
  start_date: null,
  end_date: null,
  start_tz: HOME,
  end_tz: WEST,
  local_date: '2099-12-03',
  busy: true,
  response_status: null,
  category: 'flight',
  category_source: 'auto',
  auto_category: 'flight',
  flight_code: 'ZZ 101',
  destination_label: 'Synthetic City',
  location_codes: ['JFK'],
  removed: false,
  trip_id: null,
  version: 1,
  ...extra,
})
const ok = (data: unknown, status = 200) =>
  new Response(JSON.stringify({ schema_version: 'v1', mode, data_revision: 1, data }), { status })
const problem = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ error: { code, message } }), { status })

beforeEach(() => {
  mode = 'demo'
  status = {
    connected: false,
    window: { days_back: 30, days_ahead: 180 },
    last_sync: null,
    last_success_at: null,
  }
  syncError = null
  tripConflict = false
  trips = []
  events = []
  requests = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      const body: unknown = init?.body ? JSON.parse(String(init.body)) : null
      requests.push({ url, method, body })
      if (url.endsWith('/google-calendar/status')) return ok(status)
      if (url.endsWith('/google-calendar/sync') && method === 'POST') {
        if (syncError) return problem(syncError.status, syncError.code, syncError.message)
        return ok({
          sync: {
            started_at: 'x',
            finished_at: 'x',
            window: { start: '2026-10-23', end: '2027-05-21' },
            counters: { fetched: 9, created: 3, changed: 1, unchanged: 5, removed: 0, restored: 0 },
          },
          trips: { ...counters, created: 1 },
        })
      }
      if (method === 'PATCH' && url.includes('/google-calendar/events/')) {
        const { category } = body as { category: EventCategory | null }
        const idx = events.findIndex((item) => url.endsWith(`/${item.id}`))
        const prior = events[idx]
        const event: CalendarEvent = {
          ...prior,
          category: category ?? prior.auto_category,
          category_source: category ? 'athlete' : 'auto',
          version: prior.version + 1,
        }
        events[idx] = event
        return ok({ event, trips: { ...counters, updated: 1 } })
      }
      if (url.includes('/google-calendar/events')) return ok({ items: events })
      if (method === 'PATCH' && url.includes('/trips/')) {
        if (tripConflict)
          return problem(409, 'version_conflict', 'Trip changed; reload before editing')
        const idx = trips.findIndex((item) => url.endsWith(`/${item.id}`))
        const patch = body as TripPatch
        const prior = trips[idx]
        const updated = { ...prior, ...patch, version: prior.version + 1 }
        trips[idx] = updated
        return ok(updated)
      }
      if (method === 'POST' && url.endsWith('/trips')) {
        const fields = body as ManualTripInput
        const created = trip('new', 'confirmed', fields.start_date, {
          ...fields,
          source: 'manual',
          confidence: null,
        })
        trips.push(created)
        return ok(created, 201)
      }
      if (url.includes('/trips')) return ok({ items: trips })
      return ok(null)
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
      <Travel homeTimezone={HOME} />
    </QueryClientProvider>,
  )
  fireEvent.click(screen.getByText('Travel and Google Calendar'))
}
const writes = () => requests.filter(({ method }) => method === 'POST' || method === 'PATCH')
const tripReads = () =>
  requests.filter(({ method, url }) => method === 'GET' && url.includes('/trips')).length
const change = (id: string, value: string) =>
  fireEvent.change(document.getElementById(id)!, { target: { value } })
const row = async (name: string) => {
  const rows = await screen.findAllByTestId('trip-row')
  const match = rows.find((item) => within(item).queryByText(name))
  if (!match) throw new Error(`Missing trip row for ${name}`)
  return within(match)
}
const openEvents = async () => fireEvent.click(await screen.findByText('Calendar events'))
const addTrip = async () => fireEvent.click(await screen.findByTestId('add-trip-button'))
const submitTrip = (name: string) =>
  fireEvent.click(within(screen.getByTestId('trip-form')).getByRole('button', { name }))

it('hides Sync calendar outside real mode', async () => {
  mount()
  expect(await screen.findByText('Not connected — see the setup runbook.')).toBeVisible()
  expect(screen.queryByTestId('gcal-sync-button')).not.toBeInTheDocument()
  expect(screen.getByText('Calendar sync runs in real mode only.')).toBeVisible()
  expect(screen.getByText(/America\/New_York/, { selector: '.notice' })).toBeVisible()
})

it('syncs in real mode and shows the inline result', async () => {
  mode = 'real'
  status = {
    ...status,
    connected: true,
    last_success_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
  }
  mount()
  expect(await screen.findByText('Last calendar sync 2 h ago')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Sync calendar' }))
  expect(
    await screen.findByText('Synced: 3 new, 1 changed, 0 removed. 1 trip to review.'),
  ).toBeVisible()
  expect(writes()).toEqual([{ method: 'POST', url: '/api/v1/google-calendar/sync', body: {} }])
  expect(
    requests.filter(({ url }) => url.endsWith('/google-calendar/status')).length,
  ).toBeGreaterThanOrEqual(2)
})

it('shows the server message when sync fails', async () => {
  mode = 'real'
  status.connected = true
  syncError = { status: 409, code: 'gcal_reauth_required', message: CONNECT_ERROR }
  mount()
  fireEvent.click(await screen.findByTestId('gcal-sync-button'))
  expect(await screen.findByRole('alert')).toHaveTextContent(CONNECT_ERROR)
})

it('reports a failed last attempt', async () => {
  status.connected = true
  status.last_sync = {
    started_at: 'x',
    finished_at: 'x',
    status: 'failed',
    error_code: 'gcal_remote_error',
    counters: {},
  }
  mount()
  expect(await screen.findByText('The last calendar sync attempt failed.')).toBeVisible()
  expect(screen.queryByText('gcal_remote_error')).not.toBeInTheDocument()
})

it('lists trips to review first and hides dismissed trips', async () => {
  trips = [
    trip('up', 'confirmed', '2099-01-10'),
    trip('old', 'confirmed', '2001-01-10'),
    trip('pend', 'pending', '2099-02-01'),
    trip('chg', 'needs_review', '2099-03-01'),
    trip('gone', 'dismissed', '2099-04-01'),
  ]
  mount()
  const rows = await screen.findAllByTestId('trip-row')
  expect(rows.map((item) => item.dataset.status)).toEqual([
    'pending',
    'needs_review',
    'confirmed',
    'confirmed',
  ])
  expect(rows[2]).toHaveTextContent('City up')
  expect(screen.queryByText('City gone')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Show dismissed' }))
  expect(screen.getAllByTestId('trip-row').at(-1)).toHaveAttribute('data-status', 'dismissed')
})

it('confirms a pending trip with its version', async () => {
  trips = [trip('pend', 'pending', '2099-02-01')]
  mount()
  const button = (await row('City pend')).getByRole('button', { name: 'Confirm' })
  const before = tripReads()
  fireEvent.click(button)
  await waitFor(() => expect(tripReads()).toBeGreaterThan(before))
  expect(writes()).toEqual([
    {
      method: 'PATCH',
      url: '/api/v1/trips/pend',
      body: { expected_version: 2, status: 'confirmed' },
    },
  ])
})

it.each([
  ['Use calendar version', { accept_detected: true, status: 'confirmed' }],
  ['Keep mine', { status: 'confirmed' }],
])('chooses %s for a changed trip', async (action, fields) => {
  trips = [
    trip('chg', 'needs_review', '2099-03-01', {
      version: 4,
      detected: {
        start_date: '2099-03-02',
        end_date: '2099-03-06',
        destination_label: 'Synthetic City',
        destination_tz: WEST,
        confidence: 'high',
        stops: [],
      },
    }),
  ]
  mount()
  const changed = await row('City chg')
  expect(changed.getByText('Calendar changed: now Mar 2–Mar 6 · Synthetic City')).toBeVisible()
  fireEvent.click(changed.getByRole('button', { name: action }))
  await waitFor(() => expect(writes().at(-1)?.body).toEqual({ expected_version: 4, ...fields }))
})

it('restores detected trips to pending and manual trips to confirmed', async () => {
  trips = [
    trip('detected', 'dismissed', '2099-02-01'),
    trip('manual', 'dismissed', '2099-02-02', { source: 'manual', confidence: null }),
  ]
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Show dismissed' }))
  fireEvent.click((await row('City detected')).getByRole('button', { name: 'Restore' }))
  await waitFor(() =>
    expect(screen.getAllByTestId('trip-row')[0]).toHaveAttribute('data-status', 'pending'),
  )
  fireEvent.click((await row('City manual')).getByRole('button', { name: 'Restore' }))
  await waitFor(() =>
    expect(writes().map(({ body }) => body)).toEqual([
      { expected_version: 2, status: 'pending' },
      { expected_version: 2, status: 'confirmed' },
    ]),
  )
})

it('labels manual trips and shows local leg times', async () => {
  trips = [
    trip('manual', 'confirmed', '2099-12-03', { source: 'manual', confidence: null }),
    trip('detected', 'pending', '2099-12-03', {
      legs: [
        {
          event_id: 'e1',
          seq: 0,
          summary: 'Flight',
          flight_code: 'ZZ 101',
          depart_at: '2099-12-03T13:05:00+00:00',
          arrive_at: '2099-12-03T19:30:00+00:00',
          depart_tz: HOME,
          arrive_tz: WEST,
          depart_local: '2099-12-03T08:05:00-05:00',
          arrive_local: '2099-12-03T11:30:00-08:00',
          removed: false,
        },
      ],
    }),
  ]
  mount()
  const manual = await row('City manual')
  expect(manual.getByText('Added by you')).toBeVisible()
  expect(manual.queryByText(/Confidence/)).not.toBeInTheDocument()
  const detected = await row('City detected')
  expect(detected.getByText('Confidence: high')).toBeVisible()
  expect(
    detected.getByText(
      'Departs Dec 3 08:05 (America/New_York) → arrives Dec 3 11:30 (America/Los_Angeles) · ZZ 101',
    ),
  ).toBeVisible()
})

it('refreshes and explains a version conflict', async () => {
  trips = [trip('pend', 'pending', '2099-02-01')]
  tripConflict = true
  mount()
  const dismiss = (await row('City pend')).getByRole('button', { name: 'Dismiss' })
  const before = tripReads()
  fireEvent.click(dismiss)
  expect(await screen.findByRole('alert')).toHaveTextContent(CONFLICT)
  expect(tripReads()).toBeGreaterThan(before)
})

it('lists travel events by day with busy, removed, and trip badges', async () => {
  events = [
    calEvent('e1', { trip_id: 't1' }),
    calEvent('e2', {
      all_day: true,
      start_at: null,
      end_at: null,
      start_date: '2099-12-04',
      end_date: '2099-12-06',
      local_date: '2099-12-04',
      busy: false,
      category: 'lodging',
      auto_category: 'lodging',
      removed: true,
      flight_code: null,
      destination_label: null,
    }),
  ]
  mount()
  await openEvents()
  const [timed, allDay] = await screen.findAllByTestId('gcal-event-row')
  expect(
    requests.some(
      ({ url }) => url === '/api/v1/google-calendar/events?category=travel&include_removed=true',
    ),
  ).toBe(true)
  expect(screen.getByRole('heading', { name: 'Thu, Dec 3' })).toBeVisible()
  expect(screen.getByRole('heading', { name: 'Fri, Dec 4' })).toBeVisible()
  expect(timed).toHaveTextContent('8:05 AM · Event e1')
  expect(within(timed).getByText('Busy')).toBeVisible()
  expect(within(timed).getByText('Trip leg · Synthetic City')).toBeVisible()
  expect(allDay).toHaveTextContent('All day')
  expect(within(allDay).getByText('Free')).toBeVisible()
  expect(within(allDay).getByText('Removed')).toBeVisible()
  expect(within(allDay).getByRole('combobox')).toBeDisabled()
})

it('refetches with the chosen filter', async () => {
  mount()
  await openEvents()
  change('gcal-filter', 'all')
  await waitFor(() =>
    expect(
      requests.some(({ url }) => url === '/api/v1/google-calendar/events?include_removed=true'),
    ).toBe(true),
  )
  change('gcal-filter', 'work')
  await waitFor(() =>
    expect(
      requests.some(
        ({ url }) => url === '/api/v1/google-calendar/events?category=work&include_removed=true',
      ),
    ).toBe(true),
  )
})

it('sets and clears an athlete category', async () => {
  events = [calEvent('e1')]
  mount()
  await openEvents()
  const select = await screen.findByLabelText('Category for Event e1')
  expect(select).toHaveValue('')
  expect(within(select).getAllByRole('option')[0]).toHaveTextContent('Automatic (Flight)')
  const before = tripReads()
  fireEvent.change(select, { target: { value: 'work' } })
  expect(
    await screen.findByText('Category saved. Trips changed; check the trip list.'),
  ).toBeVisible()
  expect(writes().at(-1)).toEqual({
    method: 'PATCH',
    url: '/api/v1/google-calendar/events/e1',
    body: { expected_version: 1, category: 'work' },
  })
  expect(tripReads()).toBeGreaterThan(before)
  await waitFor(() => expect(select).toHaveValue('work'))
  fireEvent.change(select, { target: { value: '' } })
  await waitFor(() =>
    expect(writes().at(-1)?.body).toEqual({ expected_version: 2, category: null }),
  )
})

it('adds a manual trip with availability and omits unknown days', async () => {
  mount()
  await addTrip()
  expect(screen.getByLabelText('Destination timezone')).toHaveValue(HOME)
  change('trip-start', '2099-05-01')
  change('trip-end', '2099-05-03')
  change('trip-destination', 'Family visit')
  change('trip-gym', 'none')
  expect(
    screen.getAllByTestId('day-availability-select').map((select) => select.dataset.date),
  ).toEqual(['2099-05-01', '2099-05-02', '2099-05-03'])
  change('trip-day-2099-05-02', 'unavailable')
  submitTrip('Add trip')
  expect(await screen.findByText('Trip saved.')).toBeVisible()
  expect(writes().at(-1)).toEqual({
    method: 'POST',
    url: '/api/v1/trips',
    body: {
      start_date: '2099-05-01',
      end_date: '2099-05-03',
      destination_label: 'Family visit',
      destination_tz: HOME,
      running_access: null,
      gym_access: 'none',
      day_availability: [{ date: '2099-05-02', availability: 'unavailable' }],
    },
  })
})

it('saving an edit confirms the trip and drops availability outside the new range', async () => {
  trips = [
    trip('pend', 'pending', '2099-02-01', {
      day_availability: [
        { date: '2099-02-02', availability: 'reduced' },
        { date: '2099-02-05', availability: 'unavailable' },
      ],
    }),
  ]
  mount()
  fireEvent.click((await row('City pend')).getByRole('button', { name: 'Edit' }))
  expect(screen.getByLabelText('Start date')).toHaveValue('2099-02-01')
  change('trip-end', '2099-02-03')
  submitTrip('Save and confirm')
  await waitFor(() =>
    expect(writes().at(-1)).toMatchObject({
      method: 'PATCH',
      url: '/api/v1/trips/pend',
      body: {
        expected_version: 2,
        status: 'confirmed',
        end_date: '2099-02-03',
        destination_label: 'City pend',
        destination_tz: WEST,
        day_availability: [{ date: '2099-02-02', availability: 'reduced' }],
      },
    }),
  )
})

it('rejects an end before the start without a request', async () => {
  mount()
  await addTrip()
  change('trip-start', '2099-05-03')
  change('trip-end', '2099-05-01')
  submitTrip('Add trip')
  expect(screen.getByRole('alert')).toHaveTextContent(
    'End date must be on or after the start date.',
  )
  expect(writes()).toHaveLength(0)
})

it('shows the first 21 days of a long trip and keeps later choices', async () => {
  trips = [
    trip('long', 'confirmed', '2099-06-01', {
      end_date: '2099-06-30',
      day_availability: [{ date: '2099-06-25', availability: 'reduced' }],
    }),
  ]
  mount()
  fireEvent.click((await row('City long')).getByRole('button', { name: 'Edit' }))
  expect(screen.getAllByTestId('day-availability-select')).toHaveLength(21)
  expect(
    screen.getByText('Showing the first 21 days. Saved choices for later days are kept.'),
  ).toBeVisible()
  change('trip-day-2099-06-02', 'normal')
  submitTrip('Save and confirm')
  await waitFor(() =>
    expect(writes().at(-1)?.body).toMatchObject({
      day_availability: [
        { date: '2099-06-02', availability: 'normal' },
        { date: '2099-06-25', availability: 'reduced' },
      ],
    }),
  )
})

it('a detected trip may be open-ended', async () => {
  trips = [
    trip('open', 'pending', '2099-07-01', {
      end_date: null,
      day_availability: [{ date: '2099-07-20', availability: 'reduced' }],
    }),
  ]
  mount()
  fireEvent.click((await row('City open')).getByRole('button', { name: 'Edit' }))
  expect(screen.getByLabelText('End date (leave empty if unknown)')).toBeVisible()
  submitTrip('Save and confirm')
  await waitFor(() =>
    expect(writes().at(-1)?.body).toMatchObject({
      end_date: null,
      day_availability: [{ date: '2099-07-20', availability: 'reduced' }],
    }),
  )
})
