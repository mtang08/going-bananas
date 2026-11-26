import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { PlanningSettings } from '../src/pages/PlanningSettings'
import { qk } from '../src/api/queryKeys'
import type { Profile } from '../src/api/types/profile'
import type { StrengthRoutine, RaceEvent } from '../src/api/types/blocks'
import type { IntensityAnchor } from '../src/api/types/anchors'
import type { LoginStartup } from '../src/api/types/loginStartup'

let profile: Profile,
  routine: StrengthRoutine,
  head: number,
  anchors: IntensityAnchor[],
  events: RaceEvent[],
  conflict: string | null
let orderConflict: boolean
const startupUrl = '/api/v1/settings/login-startup'
let startup: LoginStartup
let startupWriteError: string | null
let startupWriteWait: Promise<void> | null
let requests: { url: string; method: string; body: Record<string, unknown> | null }[]
const clients: QueryClient[] = []
beforeEach(() => {
  requests = []
  orderConflict = false
  startup = {
    status: 'unsupported',
    enabled: null,
    message: 'Login startup is available in real mode on macOS.',
  }
  startupWriteError = null
  startupWriteWait = null
  head = 0
  anchors = []
  events = []
  conflict = null
  profile = {
    version: 3,
    timezone: 'America/New_York',
    cycle_anchor: null,
    anchor_confirmed: false,
    strength_days_confirmed: true,
    strength_schedule_mode: 'weekly',
    scheduled_strength_days: [0, 4],
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
  routine = {
    version: 0,
    suggested: true,
    schedule: { ...profile },
    slots: [
      {
        id: 'x1',
        label: 'Full body A',
        default_weekday: 0,
        lower_body_cost: 'moderate',
        typical_duration_s: 3600,
        main_lower_body_lifts: ['Squat'],
        active: true,
        version: 0,
      },
      {
        id: 'x2',
        label: 'Full body B',
        default_weekday: 4,
        lower_body_cost: 'moderate',
        typical_duration_s: 3600,
        main_lower_body_lifts: ['Deadlift'],
        active: true,
        version: 0,
      },
    ],
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input),
        method = init?.method ?? 'GET',
        body = init?.body ? JSON.parse(String(init.body)) : null
      requests.push({ url, method, body })
      if (url === startupUrl) {
        if (method === 'PUT') {
          await startupWriteWait
          if (startupWriteError) {
            return {
              ok: false,
              status: 500,
              json: async () => ({
                error: { code: 'login_startup_update_failed', message: startupWriteError },
              }),
            }
          }
          startup = {
            status: body.enabled ? 'enabled' : 'disabled',
            enabled: body.enabled,
            message: null,
          }
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({
            schema_version: 'v1',
            mode: 'demo',
            data_revision: 1,
            data: startup,
          }),
        }
      }
      if (
        conflict &&
        method !== 'GET' &&
        url.endsWith(conflict === 'calendar_exists' ? '/calendar/bootstrap' : '/profile')
      )
        return {
          ok: false,
          status: 409,
          json: async () => ({ error: { code: conflict, message: 'exists' } }),
        }
      if (method === 'PUT' && url.endsWith('/events/order')) {
        if (orderConflict) {
          return {
            ok: false,
            status: 409,
            json: async () => ({
              error: {
                code: 'event_order_stale',
                message: 'Events changed; reload before reordering',
              },
            }),
          }
        }
        const ids = body.items.map((item: { id: string }) => item.id) as string[]
        events = events.map((event) => {
          const index = ids.indexOf(event.id)
          return index === -1 ? event : { ...event, rank: index + 1 }
        })
      }
      const data = url.endsWith('/profile')
        ? profile
        : url.endsWith('/calendar')
          ? { today: '2026-11-11', head, version: head, sessions: [], completions: [] }
          : url.endsWith('/strength-routine')
            ? routine
            : url.endsWith('/anchors')
              ? { items: anchors }
              : url.endsWith('/events') || url.endsWith('/events/order')
                ? { items: events }
                : url.endsWith('/calendar/bootstrap')
                  ? { version: 1, kind: 'bootstrap', stale_proposals: [] }
                  : { items: [], datasets: [], active_jobs: [] }
      return {
        ok: true,
        status: 200,
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
function mount(setUnit = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  clients.push(client)
  render(
    <QueryClientProvider client={client}>
      <PlanningSettings unit="mi" setUnit={setUnit} />
    </QueryClientProvider>,
  )
  return client
}
const input = (id: string, value: string) =>
  fireEvent.change(document.getElementById(id)!, { target: { value } })
const writes = () => requests.filter((r) => r.method !== 'GET')
const startupCard = () =>
  within(screen.getByRole('region', { name: 'Start Going Bananas when I log in' }))
const startupSwitch = () =>
  startupCard().getByRole('switch', { name: 'Start Going Bananas when I log in' })
async function setup() {
  await screen.findByText('Set up your plan')
  input('setup-anchor', '2026-11-10')
  fireEvent.click(document.getElementById('setup-anchor-confirm')!)
  fireEvent.click(screen.getByRole('button', { name: 'Create my 14-day calendar' }))
}

it('reads startup on open and toggles both ways without any training writes', async () => {
  startup = { status: 'disabled', enabled: false, message: null }
  let complete: () => void = () => {}
  startupWriteWait = new Promise<void>((resolve) => {
    complete = resolve
  })
  mount()
  await startupCard().findByRole('switch')
  expect(startupSwitch()).not.toBeChecked()
  expect(writes()).toEqual([])

  fireEvent.click(startupSwitch())
  expect(await startupCard().findByText('Turning on startup…')).toBeVisible()
  expect(startupSwitch()).not.toBeChecked()
  expect(startupSwitch()).toHaveAttribute('aria-disabled', 'true')
  complete()
  await waitFor(() => expect(startupSwitch()).toBeChecked())

  fireEvent.click(startupSwitch())
  await waitFor(() => expect(startupSwitch()).not.toBeChecked())
  expect(writes()).toEqual([
    { url: startupUrl, method: 'PUT', body: { enabled: true } },
    { url: startupUrl, method: 'PUT', body: { enabled: false } },
  ])
})

it('keeps the effective startup status after a failed write and can retry', async () => {
  startup = { status: 'enabled', enabled: true, message: null }
  startupWriteError = 'macOS did not update the login setting.'
  mount()
  fireEvent.click(await startupCard().findByRole('switch'))
  expect(await startupCard().findByRole('alert')).toHaveTextContent(startupWriteError)
  expect(startupSwitch()).toBeChecked()
  expect(await screen.findByLabelText('Review day')).toBeInTheDocument()

  startupWriteError = null
  fireEvent.click(startupSwitch())
  await waitFor(() => expect(startupSwitch()).not.toBeChecked())
  expect(writes()).toEqual([
    { url: startupUrl, method: 'PUT', body: { enabled: false } },
    { url: startupUrl, method: 'PUT', body: { enabled: false } },
  ])
})

it('explains unavailable login startup in demo or test mode without offering a write', async () => {
  mount()
  expect(
    await startupCard().findByText('Login startup is available in real mode on macOS.'),
  ).toBeVisible()
  expect(startupCard().queryByRole('switch')).not.toBeInTheDocument()
  expect(writes()).toEqual([])
})

it('can refresh startup status independently after a host-side availability problem', async () => {
  startup = {
    status: 'other_checkout',
    enabled: null,
    message: 'Another checkout manages startup.',
  }
  mount()
  expect(await startupCard().findByText('Another checkout manages startup.')).toBeVisible()
  expect(startupCard().queryByRole('switch')).not.toBeInTheDocument()
  startup = { status: 'disabled', enabled: false, message: null }
  fireEvent.click(startupCard().getByRole('button', { name: 'Refresh startup status' }))
  expect(await startupCard().findByRole('switch')).not.toBeChecked()
  expect(writes()).toEqual([])
})

it('wizard saves profile, routine, then bootstraps', async () => {
  mount()
  await screen.findByText('Set up your plan')
  expect(
    screen.getByText('Pre-filled from your Strong history. Check each slot.'),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Create my 14-day calendar' })).toBeDisabled()
  await setup()
  await screen.findByText(/Calendar created \(version 1\)/)
  expect(writes().map((r) => [r.method, r.url])).toEqual([
    ['PUT', '/api/v1/profile'],
    ['PUT', '/api/v1/strength-routine'],
    ['POST', '/api/v1/calendar/bootstrap'],
  ])
  expect(writes()[0].body).toMatchObject({
    expected_version: 3,
    cycle_anchor: '2026-11-10',
    anchor_confirmed: true,
    strength_days_confirmed: true,
    scheduled_strength_days: [0, 4],
    timezone: 'America/New_York',
    preferences: {},
  })
  expect(writes()[1].body).toEqual({
    expected_version: 0,
    slots: routine.slots.map((s) => ({
      label: s.label,
      default_weekday: s.default_weekday,
      lower_body_cost: s.lower_body_cost,
      typical_duration_s: s.typical_duration_s,
      main_lower_body_lifts: s.main_lower_body_lifts,
      active: s.active,
    })),
  })
  expect(writes()[2].body).toEqual({
    anchor_date: '2026-11-10',
    pattern: { quality: 1, long: 1 },
    start_date: '2026-11-11',
  })
})

it('reports bootstrap conflict clearly', async () => {
  conflict = 'calendar_exists'
  mount()
  await setup()
  expect(
    await screen.findByText('A calendar already exists. Edit it on the Calendar page.'),
  ).toBeInTheDocument()
})

it('preserves alternating recurrence and changes only strength templates after setup', async () => {
  head = 4
  profile = {
    ...profile,
    strength_schedule_mode: 'alternating',
    strength_week_a_start: '2026-11-02',
    strength_week_a_days: [0, 4],
    strength_week_b_days: [1, 5],
    mobility_week_a_days: [2],
    mobility_week_b_days: [3],
  }
  routine.schedule = { ...profile }
  mount()
  await screen.findByRole('heading', { name: 'Strength routine' })
  expect(screen.queryByTestId('setup-wizard')).not.toBeInTheDocument()
  expect(screen.getByText('Week A: Monday, Friday; Week B: Tuesday, Saturday')).toBeInTheDocument()
  input('slot-1-label', 'Full body B revised')
  fireEvent.click(screen.getByRole('button', { name: 'Save strength routine' }))
  await screen.findByText('Strength routine saved.')
  expect(writes()).toHaveLength(1)
  expect(writes()[0].url).toBe('/api/v1/strength-routine')
  expect(writes()[0].body).toMatchObject({
    slots: [expect.anything(), expect.objectContaining({ label: 'Full body B revised' })],
  })
})

it('blocks empty slot labels and unconfirmed recurrence', async () => {
  mount()
  await screen.findByText('Set up your plan')
  input('slot-0-label', '')
  await setup()
  expect(await screen.findByText('Each slot needs a label.')).toBeInTheDocument()
  expect(writes()).toHaveLength(0)
})

it('creates active goals through the actual GoalCreate contract', async () => {
  mount()
  await screen.findByLabelText('Goal')
  input('goal-text', 'Sub-2 half if an event is confirmed')
  input('goal-horizon', 'season')
  input('goal-priority', '2')
  fireEvent.click(screen.getByRole('button', { name: 'Add goal' }))
  await screen.findByText('Goal saved.')
  expect(writes()[0]).toMatchObject({
    method: 'POST',
    url: '/api/v1/goals',
    body: { text: 'Sub-2 half if an event is confirmed', horizon: 'season', priority: 2 },
  })
  expect(writes()[0].body).not.toHaveProperty('status')
})

it('saves the selected standard race distance in whole metres', async () => {
  mount()
  await screen.findByLabelText('Event')
  input('event-name', 'NYC Half')
  input('event-date', '2027-03-15')
  input('event-distance', '21098')
  input('event-purpose', 'pr')
  input('event-goal-time', '1:45:00')
  input('event-status', 'registered')
  fireEvent.click(screen.getByRole('button', { name: 'Add event' }))
  await screen.findByText('Event saved.')
  expect(writes()[0].body).toEqual({
    name: 'NYC Half',
    event_date: '2027-03-15',
    distance_m: 21098,
    purpose: 'pr',
    goal_time_s: 6300,
    status: 'registered',
    result_s: null,
  })
})

it('preserves stored distance and goal time when editing other event fields', async () => {
  events = [
    {
      id: 'e1',
      name: 'Half',
      event_date: '2027-03-15',
      distance_m: 21098,
      purpose: 'pr',
      goal_time_s: 6300,
      rank: 1,
      status: 'registered',
      result_s: null,
      version: 3,
    },
  ]
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Edit' }))
  expect(screen.getByLabelText('Distance')).toHaveValue('21098')
  input('event-name', 'Updated Half')
  fireEvent.click(screen.getByRole('button', { name: 'Save event' }))
  await screen.findByText('Event saved.')
  expect(writes()[0].body).toMatchObject({
    distance_m: 21098,
    goal_time_s: 6300,
    purpose: 'pr',
    expected_version: 3,
    name: 'Updated Half',
  })
})

it('supersedes the current anchor with an explicit effective date and athlete-local noon', async () => {
  anchors = [
    {
      id: 'a1',
      anchor_key: 'hr_threshold_lower-2026-10-01',
      kind: 'hr_threshold_lower',
      value_low: 160,
      value_high: null,
      unit: 'bpm',
      protocol: 'manual',
      confidence: 'moderate',
      status: 'active',
      calibrated_at: '2026-10-01T16:00:00Z',
      valid_from: '2026-10-01',
      review_after: '2026-11-01',
      source_activity_id: null,
      source_event_id: null,
      proposal_id: null,
      conditions: null,
      notes: null,
      supersedes_key: null,
      content_hash: 'hash',
    },
  ]
  mount()
  const row = await screen.findByTestId('anchor-row')
  expect(row).toHaveTextContent(
    'Threshold lower (HR) · 160 bpm · Manual entry · moderate confidence · active',
  )
  expect(row).toHaveTextContent('Review due')
  input('anchor-kind', 'hr_threshold_lower')
  input('anchor-value', '165')
  fireEvent.click(screen.getByRole('button', { name: 'Save anchor' }))
  await screen.findByText(/Anchor saved/)
  expect(writes()[0].body).toMatchObject({
    kind: 'hr_threshold_lower',
    value_low: 165,
    value_high: null,
    unit: 'bpm',
    protocol: 'manual',
    confidence: 'moderate',
    supersedes_key: anchors[0].anchor_key,
    conditions: null,
    notes: null,
    valid_from: '2026-11-11',
    calibrated_at: '2026-11-11T17:00:00.000Z',
  })
})

it('converts pace and validates HR entry', async () => {
  mount()
  await screen.findByLabelText('Anchor')
  input('anchor-kind', 'speed_aerobic_upper')
  input('anchor-value', '8:00')
  fireEvent.click(screen.getByRole('button', { name: 'Save anchor' }))
  await screen.findByText(/Anchor saved/)
  expect(writes()[0].body?.value_low).toBeCloseTo(3.3528, 4)
  expect(writes()[0].body?.unit).toBe('mps')
  input('anchor-kind', 'hr_aerobic_upper')
  input('anchor-value', '250')
  fireEvent.click(screen.getByRole('button', { name: 'Save anchor' }))
  await screen.findByText('Enter a heart rate between 30 and 230 bpm.')
  expect(writes()).toHaveLength(1)
})

it('saves review day without losing other profile preferences or recurrence', async () => {
  profile.preferences = { existing: 'kept' }
  profile.mobility_week_a_days = [2]
  mount()
  await screen.findByLabelText('Review day')
  input('review-weekday', '0')
  fireEvent.click(screen.getByRole('button', { name: 'Save review day' }))
  await screen.findByText('Review day saved.')
  expect(writes()[0].body).toMatchObject({
    preferences: { existing: 'kept', weekly_review_weekday: 0 },
    mobility_week_a_days: [2],
  })
})

it('saves the display timezone without changing other profile fields', async () => {
  mount()
  await screen.findByLabelText('Display timezone')
  input('timezone', 'America/Chicago')
  fireEvent.click(screen.getByRole('button', { name: 'Save timezone' }))
  await screen.findByText('Timezone saved.')
  expect(writes().map((r) => [r.method, r.url])).toEqual([['PUT', '/api/v1/profile']])
  expect(writes()[0].body).toMatchObject({
    expected_version: 3,
    timezone: 'America/Chicago',
    strength_days_confirmed: true,
    scheduled_strength_days: [0, 4],
  })
})

it('shows version conflicts without submitting further setup writes', async () => {
  conflict = 'version_conflict'
  mount()
  await setup()
  await screen.findByText('Settings changed in another tab. Reload and try again.')
  await waitFor(() => expect(writes()).toHaveLength(1))
})

it('resets stale routine drafts when a newer saved version arrives', async () => {
  head = 4
  const client = mount()
  await screen.findByRole('heading', { name: 'Strength routine' })
  input('slot-0-label', 'Unsaved stale label')
  routine = {
    ...routine,
    version: 2,
    slots: routine.slots.map((s, i) => (i === 0 ? { ...s, label: 'Newly saved elsewhere' } : s)),
  }
  await client.invalidateQueries({ queryKey: qk.strengthRoutine })
  await waitFor(() =>
    expect(document.getElementById('slot-0-label')).toHaveValue('Newly saved elsewhere'),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Save strength routine' }))
  await screen.findByText('Strength routine saved.')
  expect(writes()[0].body).toMatchObject({
    expected_version: 2,
    slots: [expect.objectContaining({ label: 'Newly saved elsewhere' }), expect.anything()],
  })
})

it('resets setup drafts when profile or routine versions change', async () => {
  const client = mount()
  await screen.findByTestId('setup-wizard')
  input('slot-0-label', 'Stale setup draft')
  profile = { ...profile, version: 4, cycle_anchor: '2026-11-09' }
  await client.invalidateQueries({ queryKey: qk.profile })
  await waitFor(() => expect(document.getElementById('slot-0-label')).toHaveValue('Full body A'))
  expect(document.getElementById('setup-anchor')).toHaveValue('2026-11-09')
  expect(writes()).toHaveLength(0)
})

it('renders one Settings page without legacy sections', async () => {
  head = 4
  mount()
  await screen.findByRole('heading', { name: 'Strength routine' })
  const h1 = screen.getAllByRole('heading', { level: 1 })
  expect(h1).toHaveLength(1)
  expect(h1[0]).toHaveTextContent('Settings')
  expect(screen.getByRole('link', { name: 'User guide' })).toHaveAttribute('href', '#guide')
  expect(screen.getByTestId('sync-card')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Record check-in/ })).toBeNull()
  expect(screen.queryByText('Historical imports')).toBeNull()
  expect(screen.queryByText('Resolution queue')).toBeNull()
  expect(screen.queryByText('Import & backup')).toBeNull()
  expect(screen.getByTestId('anchors-disclosure')).not.toHaveAttribute('open')
  const schedule = screen.getByTestId('strength-schedule')
  expect(schedule).not.toHaveAttribute('open')
  expect(schedule.querySelector('summary')).toHaveTextContent(
    'Strength schedule (weekly or alternating)',
  )
  const routineCard = screen.getByRole('heading', { name: 'Strength routine' }).parentElement!
  expect(routineCard.nextElementSibling).toBe(schedule)
  expect(
    routineCard.compareDocumentPosition(schedule) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy()
})

it('switches display units', async () => {
  const setUnit = vi.fn()
  mount(setUnit)
  fireEvent.click(await screen.findByRole('button', { name: 'Kilometers' }))
  expect(setUnit).toHaveBeenCalledWith('km')
})

it('saves a confirmed Week A/B pattern from the strength schedule editor', async () => {
  head = 4
  mount()
  await screen.findByRole('heading', { name: 'Strength routine' })
  input('schedule-mode', 'alternating')
  input('week-a-start', '2026-11-09')
  const weeks = document.querySelectorAll('.schedule-week')
  const check = (week: Element, label: string, day: string) => {
    const picker = within(week as HTMLElement).getByText(label).parentElement!
    fireEvent.click(within(picker).getByLabelText(day))
  }
  check(weeks[0], 'Full-body strength · two days', 'Mon')
  check(weeks[0], 'Full-body strength · two days', 'Fri')
  check(weeks[0], 'Required gym mobility', 'Wed')
  check(weeks[1], 'Full-body strength · two days', 'Tue')
  check(weeks[1], 'Full-body strength · two days', 'Sat')
  check(weeks[1], 'Required gym mobility', 'Thu')
  fireEvent.click(
    within(screen.getByText('Optional mobility · both weeks').parentElement!).getByLabelText('Sun'),
  )
  fireEvent.click(screen.getByLabelText('I confirm this repeating strength and mobility pattern'))
  fireEvent.click(screen.getByRole('button', { name: 'Save strength schedule' }))
  await screen.findByText('Strength schedule saved as a new profile version.')
  expect(writes().map((r) => [r.method, r.url])).toEqual([['PUT', '/api/v1/profile']])
  expect(writes()[0].body).toMatchObject({
    strength_schedule_mode: 'alternating',
    strength_week_a_start: '2026-11-09',
    strength_week_a_days: [0, 4],
    strength_week_b_days: [1, 5],
    mobility_week_a_days: [2],
    mobility_week_b_days: [3],
    mobility_optional_days: [6],
    strength_days_confirmed: true,
    timezone: 'America/New_York',
    expected_version: 3,
  })
})

it('blocks an unconfirmable schedule', async () => {
  head = 4
  mount()
  await screen.findByRole('heading', { name: 'Strength routine' })
  input('schedule-mode', 'alternating')
  fireEvent.click(screen.getByLabelText('I confirm this repeating strength and mobility pattern'))
  expect(
    await screen.findByText(
      /Choose exactly two full-body strength days per week and a valid Week A Monday/,
    ),
  ).toHaveAttribute('role', 'alert')
  expect(screen.getByRole('button', { name: 'Save strength schedule' })).toBeDisabled()
})

it('opens the strength schedule editor from the schedule link', async () => {
  Element.prototype.scrollIntoView = vi.fn()
  mount()
  fireEvent.click(await screen.findByText('Edit confirmed strength schedule'))
  expect(screen.getByTestId('strength-schedule')).toHaveAttribute('open')
})

it('rejects a malformed goal time without saving', async () => {
  mount()
  await screen.findByLabelText('Event')
  input('event-name', 'NYC Half')
  input('event-date', '2027-03-15')
  input('event-goal-time', 'fast')
  fireEvent.click(screen.getByRole('button', { name: 'Add event' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Enter the goal time as h:mm:ss or m:ss.',
  )
  expect(writes()).toHaveLength(0)
})

it('offers only whole-metre standard distances', async () => {
  mount()
  await screen.findByLabelText('Event')
  const distance = screen.getByLabelText<HTMLSelectElement>('Distance')
  expect(Array.from(distance.options, (option) => option.value)).toEqual([
    '',
    '1609',
    '5000',
    '8000',
    '10000',
    '15000',
    '16093',
    '21098',
    '42195',
  ])
})

const rankedEvent = (
  id: string,
  name: string,
  rank: number | null,
  extra: Partial<RaceEvent> = {},
): RaceEvent => ({
  id,
  name,
  event_date: `2027-0${rank ?? 1}-15`,
  distance_m: 10000,
  purpose: 'pr',
  goal_time_s: null,
  rank,
  status: 'planned',
  result_s: null,
  version: rank ?? 1,
  ...extra,
})

const rankedEvents = () => [
  rankedEvent('e2', 'Ten K', 2),
  rankedEvent('e1', 'Half', 1),
  rankedEvent('e3', 'Five K', 3),
  rankedEvent('e4', 'Old', null, { status: 'completed', result_s: 2700, goal_time_s: 2800 }),
]
const moveButton = (name: string) => screen.getByRole('button', { name })

it('lists upcoming events by rank with the goal race first', async () => {
  events = rankedEvents()
  mount()
  const rows = await screen.findAllByTestId('event-row')
  expect(rows[0]).toHaveTextContent('Goal race Half')
  expect(rows[1]).toHaveTextContent('Ten K')
  expect(rows[2]).toHaveTextContent('Five K')
  expect(screen.getAllByText('Goal race', { exact: true })).toHaveLength(1)
  expect(moveButton('Move Half up')).toBeDisabled()
  expect(moveButton('Move Half down')).toBeEnabled()
  expect(moveButton('Move Five K down')).toBeDisabled()
  expect(screen.getByTestId('event-row-past')).toHaveTextContent('goal 46:40 · result 45:00')
  expect(screen.queryByRole('button', { name: 'Move Old up' })).toBeNull()
})

it('reorders the events with their versions and restores focus after reload', async () => {
  events = rankedEvents()
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Move Half down' }))
  expect(await screen.findByText('Half moved to rank 2')).toBeInTheDocument()
  expect(writes()[0]).toEqual({
    method: 'PUT',
    url: '/api/v1/events/order',
    body: {
      items: [
        { id: 'e2', expected_version: 2 },
        { id: 'e1', expected_version: 1 },
        { id: 'e3', expected_version: 3 },
      ],
    },
  })
  await waitFor(() => expect(moveButton('Move Half down')).toHaveFocus())
  expect(screen.getAllByTestId('event-row').map((row) => row.dataset.eventId)).toEqual([
    'e2',
    'e1',
    'e3',
  ])
})

it.each([
  ['Move Half down', 'Move Half up'],
  ['Move Ten K up', 'Move Ten K down'],
])('restores focus when %s becomes disabled', async (original, fallback) => {
  events = rankedEvents().slice(0, 2)
  mount()
  fireEvent.click(await screen.findByRole('button', { name: original }))
  await waitFor(() => expect(moveButton(fallback)).toHaveFocus())
  expect(moveButton(original)).toBeDisabled()
})

it('shows a stale order error and reloads the events', async () => {
  events = rankedEvents()
  orderConflict = true
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Move Half down' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Events changed; reload before reordering',
  )
  expect(
    requests.filter(({ method, url }) => method === 'GET' && url.endsWith('/events')).length,
  ).toBeGreaterThanOrEqual(2)
})

it('saves confirmed running limits in meters and seconds without treating review as the end', async () => {
  profile.facts = { clinician_restriction: 'Keep runs easy.', other_fact: true }
  mount()
  await screen.findByLabelText('Maximum distance per run')
  input('run-limit-unit', 'mi')
  input('run-limit-distance', '3')
  input('run-limit-minutes', '22.5')
  input('run-limit-review', '2026-11-14')
  input('run-limit-source', 'Physiotherapist')
  input('run-limit-wording', 'Three miles or 22.5 minutes.')
  fireEvent.click(screen.getByRole('button', { name: 'Save running limits' }))
  await waitFor(() => expect(writes()).toHaveLength(1))
  expect(writes()[0].body?.facts).toMatchObject({
    clinician_restriction: 'Keep runs easy.',
    other_fact: true,
    running_restriction: {
      starts_on: '2026-11-11',
      review_on: '2026-11-14',
      ends_on: null,
      max_distance_m: 4828,
      max_duration_s: 1350,
      source: 'Physiotherapist',
      wording: 'Three miles or 22.5 minutes.',
    },
  })
})

it('shows a due review without clearing the restriction or the previous instruction', async () => {
  profile.facts = {
    clinician_restriction: 'Keep runs easy.',
    running_restriction: {
      starts_on: '2026-11-01',
      review_on: '2026-11-10',
      ends_on: null,
      no_quality: true,
      source: 'Athlete',
    },
  }
  mount()
  await screen.findByText(
    'Review is due. Confirm updated limits or clear them once the restriction ends.',
  )
  expect(screen.getByLabelText('No quality sessions')).toBeChecked()
  fireEvent.click(screen.getByRole('button', { name: 'Clear dated running limits' }))
  await waitFor(() =>
    expect(writes()[0].body?.facts).toEqual({ clinician_restriction: 'Keep runs easy.' }),
  )
})
