import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Calendar } from '../src/pages/Calendar'
import type { CalendarView, SessionState } from '../src/api'

const base = {
  id: '', session_uid: '', revision: 1, calendar_version_number: 2, deleted: false,
  local_date: '', slot: 0, kind: 'run', recipe_id: 'REC001', custom: false,
  locked: false, legacy_unstructured: false, legacy_payload: null, placeholder: false,
  intent: 'Easy', certainty: 'committed', planned_duration_s: 1800,
  planned_distance_m: null, structure: null, strength_slot_id: null, notes: null,
  is_original: true, changed_by_version: 2,
} satisfies SessionState
const session = (uid: string, date: string, changes: Partial<SessionState> = {}): SessionState =>
  ({ ...base, id: uid + '-rev', session_uid: uid, local_date: date, ...changes })
const sessions: SessionState[] = [
  session('s1', '2026-11-12'),
  session('s2', '2026-11-19', { recipe_id: 'REC002', certainty: 'provisional', intent: 'Long' }),
  session('s3', '2026-11-09'),
  session('s4', '2026-11-08', { recipe_id: null, custom: true, planned_duration_s: null,
    structure: [{ type: 'repeat', count: 4, steps: [{
      type: 'work', duration_type: 'distance', duration_value: 800,
      target: { modality: 'speed', low: 3.8, high: 4, effort_cue: null },
    }] }] }),
]
const completion = {
  id: 'c4', input_version: 1, session_uid: 's4', activity_id: 'a9',
  strong_workout_id: null, manual_session_id: null, status: 'completed_as_planned',
  match_method: 'explicit', modification_reason: null, reason_note: null,
  version: 1, updated_at: '2026-11-11T12:00:00Z', local_date: '2026-11-08',
} as const
const view: CalendarView = {
  today: '2026-11-11', timezone: 'America/New_York', start: '2026-11-04',
  end: '2026-11-24', head: 2, version: 2, last_planned_date: '2026-11-19',
  sessions, completions: [completion], undo: {
    target_version: 1, eligible: true, protected_session_uids: ['s4'],
  },
}
const versions = [
  { id: 'v2', number: 2, parent_number: 1, kind: 'manual_edit', actor: 'user',
    reason: 'demo history', proposal_id: null, restored_from_number: null,
    block_version_id: null, created_at: '2026-11-11T12:00:00Z' },
  { id: 'v1', number: 1, parent_number: null, kind: 'bootstrap', actor: 'system',
    reason: null, proposal_id: null, restored_from_number: null,
    block_version_id: null, created_at: '2026-11-10T12:00:00Z' },
]
type Request = { url: string; method: string; body: unknown }
let requests: Request[] = []
let head = view
let nextWrite = { version: 3, kind: 'manual_edit', stale_proposals: [], preserved_session_uids: [] } as {
  version: number; kind: string; stale_proposals: string[]; preserved_session_uids: string[]
}
let writeError: number | null = null
const wrap = (data: unknown) => ({ schema_version: 'v1', data_revision: 2, mode: 'demo', data })
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><Calendar unit="mi"/></QueryClientProvider>)
}
const day = (date: string) => document.querySelector(`[data-testid="calendar-day"][data-date="${date}"]`) as HTMLElement
const row = (date: string) => within(day(date)).getAllByTestId('session-row')[0]
const writes = () => requests.filter(r => r.method !== 'GET')
beforeEach(() => {
  requests = []
  head = view
  nextWrite = { version: 3, kind: 'manual_edit', stale_proposals: [], preserved_session_uids: [] }
  writeError = null
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input), method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    requests.push({ url, method, body })
    if (writeError && method !== 'GET') return new Response(JSON.stringify({
      error: { code: writeError === 409 ? 'calendar_head_moved' : 'validation_error', message: 'Rejected' },
    }), { status: writeError })
    const data = url.includes('/calendar/versions') ? { items: versions }
      : url.includes('/calendar/diff') ? { changes: [] }
      : url.includes('/activities') ? { items: [{ id: 'a9', local_date: '2026-11-09', distance_m: 5000 }] }
      : url.includes('/calendar/completions') ? { ...completion, session_uid: 's3', status: 'skipped' }
      : url.includes('/calendar/edits') || url.includes('/calendar/rollback') ? nextWrite
      : url.includes('/calendar?version=1') ? { ...head, version: 1 }
      : head
    return new Response(JSON.stringify(wrap(data)), { status: method === 'GET' ? 200 : 201 })
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('Calendar', () => {
  it('renders days, markers, repeated steps and history', async () => {
    mount()
    expect(await screen.findByText('Version 2')).toBeInTheDocument()
    expect(within(row('2026-11-19')).getByText('Provisional')).toBeInTheDocument()
    expect(row('2026-11-19')).toHaveClass('certainty-provisional')
    expect(within(row('2026-11-09')).getByText('Not recorded')).toBeInTheDocument()
    expect(within(row('2026-11-09')).getByRole('button', { name: 'Record outcome' })).toBeInTheDocument()
    expect(within(row('2026-11-08')).getByRole('link', { name: 'Open run' })).toHaveAttribute('href', '#activity/a9')
    expect(within(row('2026-11-08')).getAllByText('Work 800 m · 6:42 /mi–7:04 /mi')).toHaveLength(4)
    expect(screen.getByText('v2 · Manual edit')).toBeInTheDocument()
    expect(screen.getByText('v1 · Setup')).toBeInTheDocument()
    expect(screen.getAllByTestId('calendar-day')).toHaveLength(21)
  })
  it('moves one session with an exact versioned edit', async () => {
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Move' }))
    fireEvent.change(screen.getByLabelText('New date'), { target: { value: '2026-11-13' } })
    fireEvent.change(screen.getByLabelText('Reason for change (optional)'), { target: { value: 'trip' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save move' }))
    await waitFor(() => expect(screen.getByText('Saved as version 3.')).toBeInTheDocument())
    expect(writes()[0]).toMatchObject({ url: '/api/v1/calendar/edits', method: 'POST',
      body: { expected_head: 2, reason: 'trip', edits: [{ op: 'move', session_uid: 's1', fields: { local_date: '2026-11-13' } }] } })
    await waitFor(() => expect(requests.filter(r => r.url === '/api/v1/calendar' && r.method === 'GET').length).toBeGreaterThanOrEqual(2))
  })
  it('edits changed fields only and omits empty reason', async () => {
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByLabelText('Intent'), { target: { value: 'Easy, flat' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save session' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0].body).toEqual({ expected_head: 2,
      edits: [{ op: 'modify', session_uid: 's1', fields: { intent: 'Easy, flat' } }] })
  })
  it('adds at the next slot with converted duration', async () => {
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(day('2026-11-14')).getByRole('button', { name: 'Add session' }))
    fireEvent.change(screen.getByLabelText('Intent'), { target: { value: 'Shakeout' } })
    fireEvent.change(screen.getByLabelText('Planned duration (minutes)'), { target: { value: '20' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save session' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0].body).toEqual({ expected_head: 2, edits: [{ op: 'add', fields: {
      local_date: '2026-11-14', slot: 0, kind: 'run', recipe_id: 'REC001', custom: false,
      intent: 'Shakeout', planned_duration_s: 1200, planned_distance_m: null,
      structure: null, strength_slot_id: null, notes: null,
    } }] })
  })
  it('confirms deletion before writing', async () => {
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-19')).getByRole('button', { name: 'Delete' }))
    expect(writes()).toHaveLength(0)
    fireEvent.click(within(row('2026-11-19')).getByRole('button', { name: 'Confirm delete' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0].body).toEqual({ expected_head: 2,
      edits: [{ op: 'delete', session_uid: 's2', fields: {} }] })
  })
  it('offers reload on head conflict and reports stale proposals', async () => {
    writeError = 409
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Delete' }))
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Confirm delete' }))
    expect(await screen.findByText(/The calendar changed since you loaded it/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reload calendar' }))
    await waitFor(() => expect(requests.filter(r => r.url === '/api/v1/calendar' && r.method === 'GET').length).toBeGreaterThanOrEqual(2))
  })
  it('shows stale coach proposal count', async () => {
    nextWrite = { ...nextWrite, stale_proposals: ['x'] }
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Delete' }))
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Confirm delete' }))
    expect(await screen.findByText('This edit made 1 pending coach proposal(s) stale.')).toBeInTheDocument()
  })
  it('restores only the advertised protected target', async () => {
    mount()
    await screen.findByText('v1 · Setup')
    expect(within(screen.getAllByTestId('version-row')[0]).queryByRole('button', { name: 'Restore' })).not.toBeInTheDocument()
    fireEvent.click(within(screen.getAllByTestId('version-row')[1]).getByRole('button', { name: 'Restore' }))
    expect(screen.getByText(/Completed, locked and historical sessions were preserved/)).toBeInTheDocument()
    expect(screen.getByText('Preserved: s4')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm restore' }))
    await waitFor(() => expect(screen.getByText('Restored version 1 as version 3.')).toBeInTheDocument())
    expect(writes()[0].url).toBe('/api/v1/calendar/rollback')
    expect(writes()[0].body).toEqual({ expected_head: 2, to_version: 1 })
  })
  it('views historical version read-only', async () => {
    mount()
    await screen.findByText('v1 · Setup')
    fireEvent.click(within(screen.getAllByTestId('version-row')[1]).getByRole('button', { name: 'View' }))
    expect(await screen.findByText(/Viewing version 1 \(read-only\)/)).toBeInTheDocument()
    expect(requests.some(r => r.url.includes('/calendar?version=1'))).toBe(true)
    expect(screen.queryByRole('button', { name: 'Move' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add session' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Record outcome' })).not.toBeInTheDocument()
  })
  it('records skipped outcome without inferred status fields', async () => {
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-09')).getByRole('button', { name: 'Record outcome' }))
    fireEvent.click(screen.getByRole('button', { name: 'Skipped' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0]).toMatchObject({ url: '/api/v1/calendar/completions/s3', method: 'PUT',
      body: { status: 'skipped' } })
  })
  it('links a nearby run with a server-derived match method and version guard', async () => {
    head = { ...view, completions: [...view.completions, {
      ...completion, id: 'c3', session_uid: 's3', activity_id: null,
      status: 'unknown', match_method: 'none', version: 4,
    }] }
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-09')).getByRole('button', { name: 'Record outcome' }))
    await screen.findByRole('option', { name: /Nov 9 · 3.1 mi/ })
    fireEvent.change(await screen.findByLabelText('Link a run'), { target: { value: 'a9' } })
    fireEvent.click(screen.getByRole('button', { name: 'Link run' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0].body).toEqual({ activity_id: 'a9', expected_version: 4 })
  })
  it('does not send unchanged edits', async () => {
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Edit' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save session' }))
    expect(screen.getByText('No changes to save.')).toBeInTheDocument()
    expect(writes()).toHaveLength(0)
  })
  it('does not offer restore when the server marks undo ineligible', async () => {
    head = { ...view, undo: { target_version: 1, eligible: false, protected_session_uids: [] } }
    mount()
    await screen.findByText('v1 · Setup')
    expect(screen.queryByRole('button', { name: 'Restore' })).not.toBeInTheDocument()
  })
  it('preserves exact metres during an unrelated edit and resolves a chosen placeholder recipe', async () => {
    head = { ...view, sessions: [session('s1', '2026-11-12', {
      planned_distance_m: 1610, recipe_id: null, placeholder: true,
    })] }
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByLabelText('Session'), { target: { value: 'REC002' } })
    fireEvent.change(screen.getByLabelText('Intent'), { target: { value: 'Long and easy' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save session' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0].body).toEqual({ expected_head: 2, edits: [{ op: 'modify', session_uid: 's1', fields: {
      recipe_id: 'REC002', placeholder: false, intent: 'Long and easy',
    } }] })
  })
  it('keeps unlinked unknown sessions editable and linked unknown sessions protected', async () => {
    head = { ...view, completions: [...view.completions,
      { ...completion, id: 'c1', session_uid: 's1', activity_id: null, status: 'unknown', match_method: 'none' },
      { ...completion, id: 'c2', session_uid: 's2', activity_id: 'a2', status: 'unknown' },
    ] }
    mount()
    await screen.findByText('Version 2')
    expect(within(row('2026-11-12')).getByRole('button', { name: 'Edit' })).toBeInTheDocument()
    expect(within(row('2026-11-19')).queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
  })
  it('shows mutation errors inside the open editor', async () => {
    writeError = 422
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByLabelText('Intent'), { target: { value: 'Changed' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save session' }))
    const dialog = screen.getByRole('dialog', { name: 'Edit session' })
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Rejected')
  })
  it('closes stale editor state before reloading a moved calendar head', async () => {
    writeError = 409
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByLabelText('Intent'), { target: { value: 'Old form edit' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save session' }))
    const dialog = screen.getByRole('dialog', { name: 'Edit session' })
    fireEvent.click(await within(dialog).findByRole('button', { name: 'Reload calendar' }))
    expect(screen.queryByRole('dialog', { name: 'Edit session' })).not.toBeInTheDocument()
    await waitFor(() => expect(requests.filter(r => r.url === '/api/v1/calendar' && r.method === 'GET').length).toBeGreaterThanOrEqual(2))
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Edit' }))
    expect(screen.getByLabelText('Intent')).toHaveValue('Easy')
  })
  it('shows imported prose and includes mobility in the editor', async () => {
    head = { ...view, sessions: [session('s1', '2026-11-12', { kind: 'mobility', intent: 'Easy mobility' }),
      session('s4', '2026-11-08', { recipe_id: null, legacy_unstructured: true,
        intent: 'Old easy prescription', notes: 'Keep this plan prose' })] }
    mount()
    await screen.findByText('Version 2')
    expect(within(row('2026-11-08')).getByText('Imported run')).toBeInTheDocument()
    expect(within(row('2026-11-08')).getByText('Old easy prescription')).toBeInTheDocument()
    expect(within(row('2026-11-08')).getByText('Keep this plan prose')).toBeInTheDocument()
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Edit' }))
    expect(screen.getByRole('option', { name: 'Mobility' })).toBeInTheDocument()
    expect(screen.getByLabelText('Type')).toHaveValue('mobility')
  })
  it('shows setup when no calendar exists', async () => {
    head = { ...view, head: 0, version: 0, undo: null, sessions: [], completions: [] }
    mount()
    expect(await screen.findByText('No calendar yet')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open setup' })).toHaveAttribute('href', '#settings')
    expect(screen.queryByText('Next 14 days')).not.toBeInTheDocument()
  })
})
