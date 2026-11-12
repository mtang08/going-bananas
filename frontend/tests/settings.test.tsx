import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { PlanningSettings } from '../src/pages/PlanningSettings'
import { qk, type Profile, type StrengthRoutine, type IntensityAnchor, type RaceEvent } from '../src/api'

let profile: Profile, routine: StrengthRoutine, head: number, anchors: IntensityAnchor[], events: RaceEvent[], conflict: string | null
let requests: { url: string; method: string; body: Record<string, unknown> | null }[]
const clients: QueryClient[] = []
beforeEach(() => {
  requests = []; head = 0; anchors = []; events = []; conflict = null
  profile = { planning_authority: 'calendar', version: 3, timezone: 'America/New_York', cycle_anchor: null, anchor_confirmed: false,
    strength_days_confirmed: true, strength_schedule_mode: 'weekly', scheduled_strength_days: [0, 4], strength_week_a_start: null,
    strength_week_a_days: [], strength_week_b_days: [], mobility_week_a_days: [], mobility_week_b_days: [], mobility_optional_days: [], facts: {}, preferences: {}, unknowns: [] }
  routine = { version: 0, suggested: true, schedule: { ...profile }, slots: [
    { id: 'x1', label: 'Full body A', default_weekday: 0, lower_body_cost: 'moderate', typical_duration_s: 3600, main_lower_body_lifts: ['Squat'], active: true, version: 0 },
    { id: 'x2', label: 'Full body B', default_weekday: 4, lower_body_cost: 'moderate', typical_duration_s: 3600, main_lower_body_lifts: ['Deadlift'], active: true, version: 0 },
  ] }
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input), method = init?.method ?? 'GET', body = init?.body ? JSON.parse(String(init.body)) : null
    requests.push({ url, method, body })
    if (conflict && method !== 'GET' && url.endsWith(conflict === 'calendar_exists' ? '/calendar/bootstrap' : '/profile')) return { ok: false, status: 409, json: async () => ({ error: { code: conflict, message: 'exists' } }) }
    const data = url.endsWith('/profile') ? profile : url.endsWith('/calendar') ? { today: '2026-11-11', head, version: head, sessions: [], completions: [] }
      : url.endsWith('/strength-routine') ? routine : url.endsWith('/anchors') ? { items: anchors } : url.endsWith('/events') ? { items: events }
      : url.endsWith('/calendar/bootstrap') ? { version: 1, kind: 'bootstrap', stale_proposals: [] } : { items: [], datasets: [], active_jobs: [] }
    return { ok: true, status: 200, json: async () => ({ schema_version: 'v1', mode: 'demo', data_revision: 1, data }) }
  }))
})
afterEach(() => { cleanup(); clients.forEach(c => c.clear()); clients.length = 0; vi.unstubAllGlobals() })
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); clients.push(client)
  render(<QueryClientProvider client={client}><PlanningSettings unit="mi" setUnit={vi.fn()} onCheckin={vi.fn()} /></QueryClientProvider>)
  return client
}
const input = (id: string, value: string) => fireEvent.change(document.getElementById(id)!, { target: { value } })
const writes = () => requests.filter(r => r.method !== 'GET')
async function setup() {
  await screen.findByText('Set up your plan'); input('setup-anchor', '2026-11-10'); fireEvent.click(document.getElementById('setup-anchor-confirm')!)
  fireEvent.click(screen.getByRole('button', { name: 'Create my 14-day calendar' }))
}

it('wizard saves profile, routine, then bootstraps', async () => {
  mount(); await screen.findByText('Set up your plan')
  expect(screen.getByText('Pre-filled from your Strong history. Check each slot.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Create my 14-day calendar' })).toBeDisabled()
  await setup(); await screen.findByText(/Calendar created \(version 1\)/)
  expect(writes().map(r => [r.method, r.url])).toEqual([
    ['PUT', '/api/v1/profile'], ['PUT', '/api/v1/strength-routine'], ['POST', '/api/v1/calendar/bootstrap'],
  ])
  expect(writes()[0].body).toMatchObject({ expected_version: 3, cycle_anchor: '2026-11-10', anchor_confirmed: true, strength_days_confirmed: true, scheduled_strength_days: [0, 4], timezone: 'America/New_York', preferences: {} })
  expect(writes()[1].body).toEqual({ expected_version: 0, slots: routine.slots.map(s => ({ label: s.label, default_weekday: s.default_weekday, lower_body_cost: s.lower_body_cost, typical_duration_s: s.typical_duration_s, main_lower_body_lifts: s.main_lower_body_lifts, active: s.active })) })
  expect(writes()[2].body).toEqual({ anchor_date: '2026-11-10', pattern: { quality: 1, long: 1 }, start_date: '2026-11-11' })
})

it('reports bootstrap conflict clearly', async () => {
  conflict = 'calendar_exists'; mount(); await setup()
  expect(await screen.findByText('A calendar already exists. Edit it on the Calendar page.')).toBeInTheDocument()
})

it('preserves alternating recurrence and changes only strength templates after setup', async () => {
  head = 4; profile = { ...profile, strength_schedule_mode: 'alternating', strength_week_a_start: '2026-11-02', strength_week_a_days: [0, 4], strength_week_b_days: [1, 5], mobility_week_a_days: [2], mobility_week_b_days: [3] }; routine.schedule = { ...profile }
  mount(); await screen.findByTestId('setup-done')
  expect(screen.getByText(/Calendar created. Current version 4./)).toBeInTheDocument()
  expect(screen.queryByTestId('setup-wizard')).not.toBeInTheDocument()
  expect(screen.getByText('Week A: Monday, Friday; Week B: Tuesday, Saturday')).toBeInTheDocument()
  input('slot-1-label', 'Full body B revised'); fireEvent.click(screen.getByRole('button', { name: 'Save strength routine' }))
  await screen.findByText('Strength routine saved.'); expect(writes()).toHaveLength(1)
  expect(writes()[0].url).toBe('/api/v1/strength-routine')
  expect(writes()[0].body).toMatchObject({ slots: [expect.anything(), expect.objectContaining({ label: 'Full body B revised' })] })
})

it('blocks empty slot labels and unconfirmed recurrence', async () => {
  mount(); await screen.findByText('Set up your plan'); input('slot-0-label', ''); await setup()
  expect(await screen.findByText('Each slot needs a label.')).toBeInTheDocument(); expect(writes()).toHaveLength(0)
})

it('creates active goals through the actual GoalCreate contract', async () => {
  mount(); await screen.findByLabelText('Goal'); input('goal-text', 'Sub-2 half if an event is confirmed'); input('goal-horizon', 'season'); input('goal-priority', '2')
  fireEvent.click(screen.getByRole('button', { name: 'Add goal' })); await screen.findByText('Goal saved.')
  expect(writes()[0]).toMatchObject({ method: 'POST', url: '/api/v1/goals', body: { text: 'Sub-2 half if an event is confirmed', horizon: 'season', priority: 2 } })
  expect(writes()[0].body).not.toHaveProperty('status')
})

it('saves the selected standard race distance in exact metres', async () => {
  mount(); await screen.findByLabelText('Event'); input('event-name', 'NYC Half'); input('event-date', '2027-03-15'); input('event-distance', '21097.5'); input('event-priority', 'target'); input('event-status', 'registered')
  fireEvent.click(screen.getByRole('button', { name: 'Add event' })); await screen.findByText('Event saved.')
  expect(writes()[0].body).toEqual({ name: 'NYC Half', event_date: '2027-03-15', distance_m: 21097.5, priority: 'target', status: 'registered', result_s: null })
})

it('preserves exact stored distance when editing other event fields', async () => {
  events = [{ id: 'e1', name: 'Half', event_date: '2027-03-15', distance_m: 21097.5, priority: 'target', status: 'registered', result_s: null, version: 3 }]
  mount(); fireEvent.click(await screen.findByRole('button', { name: 'Edit' })); input('event-name', 'Updated Half')
  fireEvent.click(screen.getByRole('button', { name: 'Save event' })); await screen.findByText('Event saved.')
  expect(writes()[0].body).toMatchObject({ distance_m: 21097.5, expected_version: 3, name: 'Updated Half' })
})

it('supersedes the current anchor with an explicit effective date and athlete-local noon', async () => {
  anchors = [{ id: 'a1', anchor_key: 'hr_threshold_lower-2026-10-01', kind: 'hr_threshold_lower', value_low: 160, value_high: null,
    unit: 'bpm', protocol: 'manual', confidence: 'moderate', status: 'active', calibrated_at: '2026-10-01T16:00:00Z', valid_from: '2026-10-01',
    review_after: '2026-11-01', source_activity_id: null, source_event_id: null, proposal_id: null, conditions: null, notes: null, supersedes_key: null, content_hash: 'hash' }]
  mount(); const row = await screen.findByTestId('anchor-row')
  expect(row).toHaveTextContent('Threshold lower (HR) · 160 bpm · Manual entry · moderate confidence · active'); expect(row).toHaveTextContent('Review due')
  input('anchor-kind', 'hr_threshold_lower'); input('anchor-value', '165'); fireEvent.click(screen.getByRole('button', { name: 'Save anchor' }))
  await screen.findByText(/Anchor saved/)
  expect(writes()[0].body).toMatchObject({ kind: 'hr_threshold_lower', value_low: 165, value_high: null, unit: 'bpm', protocol: 'manual', confidence: 'moderate', supersedes_key: anchors[0].anchor_key, conditions: null, notes: null, valid_from: '2026-11-11', calibrated_at: '2026-11-11T17:00:00.000Z' })
})

it('converts pace and validates HR entry', async () => {
  mount(); await screen.findByLabelText('Anchor'); input('anchor-kind', 'speed_aerobic_upper'); input('anchor-value', '8:00')
  fireEvent.click(screen.getByRole('button', { name: 'Save anchor' })); await screen.findByText(/Anchor saved/)
  expect(writes()[0].body?.value_low).toBeCloseTo(3.3528, 4); expect(writes()[0].body?.unit).toBe('mps')
  input('anchor-kind', 'hr_aerobic_upper'); input('anchor-value', '250'); fireEvent.click(screen.getByRole('button', { name: 'Save anchor' }))
  await screen.findByText('Enter a heart rate between 30 and 230 bpm.'); expect(writes()).toHaveLength(1)
})

it('saves review day without losing other profile preferences or recurrence', async () => {
  profile.preferences = { existing: 'kept' }; profile.mobility_week_a_days = [2]
  mount(); await screen.findByLabelText('Review day'); input('review-weekday', '0'); fireEvent.click(screen.getByRole('button', { name: 'Save review day' }))
  await screen.findByText('Review day saved.')
  expect(writes()[0].body).toMatchObject({ preferences: { existing: 'kept', weekly_review_weekday: 0 }, mobility_week_a_days: [2] })
})

it('keeps existing settings controls available', async () => {
  mount(); expect(await screen.findByLabelText('Display timezone')).toBeInTheDocument()
})

it('shows version conflicts without submitting further setup writes', async () => {
  conflict = 'version_conflict'; mount(); await setup(); await screen.findByText('Settings changed in another tab. Reload and try again.')
  await waitFor(() => expect(writes()).toHaveLength(1))
})

it('resets stale routine drafts when a newer saved version arrives', async () => {
  head = 4; const client = mount(); await screen.findByTestId('setup-done')
  input('slot-0-label', 'Unsaved stale label')
  routine = { ...routine, version: 2, slots: routine.slots.map((s, i) => i === 0 ? { ...s, label: 'Newly saved elsewhere' } : s) }
  await client.invalidateQueries({ queryKey: qk.strengthRoutine })
  await waitFor(() => expect(document.getElementById('slot-0-label')).toHaveValue('Newly saved elsewhere'))
  fireEvent.click(screen.getByRole('button', { name: 'Save strength routine' })); await screen.findByText('Strength routine saved.')
  expect(writes()[0].body).toMatchObject({ expected_version: 2, slots: [expect.objectContaining({ label: 'Newly saved elsewhere' }), expect.anything()] })
})

it('resets setup drafts when profile or routine versions change', async () => {
  const client = mount(); await screen.findByTestId('setup-wizard'); input('slot-0-label', 'Stale setup draft')
  profile = { ...profile, version: 4, cycle_anchor: '2026-11-09' }
  await client.invalidateQueries({ queryKey: qk.profile })
  await waitFor(() => expect(document.getElementById('slot-0-label')).toHaveValue('Full body A'))
  expect(document.getElementById('setup-anchor')).toHaveValue('2026-11-09')
  expect(writes()).toHaveLength(0)
})
