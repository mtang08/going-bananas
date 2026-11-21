import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Calendar } from '../src/pages/Calendar'
import { weeklyWorkoutText } from '../src/components/weeklyWorkoutExport'
import type { CalendarVersion, CalendarView, SessionState } from '../src/api/types/calendar'
import { addDays } from '../src/lib/format'

const base = {
  id: '',
  session_uid: '',
  revision: 1,
  calendar_version_number: 2,
  deleted: false,
  local_date: '',
  slot: 0,
  kind: 'run',
  recipe_id: 'REC001',
  custom: false,
  locked: false,
  legacy_unstructured: false,
  legacy_payload: null,
  placeholder: false,
  intent: 'Easy',
  certainty: 'committed',
  planned_duration_s: 1800,
  planned_distance_m: null,
  structure: null,
  strength_slot_id: null,
  notes: null,
  is_original: true,
  changed_by_version: 2,
  exception_patch: null,
} satisfies SessionState
const session = (uid: string, date: string, changes: Partial<SessionState> = {}): SessionState => ({
  ...base,
  id: uid + '-rev',
  session_uid: uid,
  local_date: date,
  ...changes,
})
const sessions: SessionState[] = [
  session('s1', '2026-11-12'),
  session('s2', '2026-11-15', { recipe_id: 'REC002', certainty: 'provisional', intent: 'Long' }),
  session('s3', '2026-11-09'),
  session('s4', '2026-11-10', {
    recipe_id: null,
    custom: true,
    planned_duration_s: null,
    structure: [
      {
        type: 'repeat',
        count: 4,
        steps: [
          {
            type: 'work',
            duration_type: 'distance',
            duration_value: 800,
            target: { modality: 'speed', low: 3.8, high: 4, effort_cue: null },
          },
        ],
      },
    ],
  }),
]
const completion = {
  id: 'c4',
  input_version: 1,
  session_uid: 's4',
  activity_id: 'a9',
  strong_workout_id: null,
  manual_session_id: null,
  status: 'completed_as_planned',
  match_method: 'explicit',
  modification_reason: null,
  reason_note: null,
  version: 1,
  updated_at: '2026-11-11T12:00:00Z',
  local_date: '2026-11-10',
} as const
const view: CalendarView = {
  today: '2026-11-11',
  timezone: 'America/New_York',
  start: '2026-11-09',
  end: '2026-11-15',
  head: 2,
  version: 2,
  last_planned_date: '2026-11-19',
  sessions,
  completions: [completion],
  recorded_runs: [],
  undo: {
    target_version: 1,
    eligible: true,
    protected_session_uids: ['s4'],
  },
}
const versions: CalendarVersion[] = [
  {
    id: 'v2',
    number: 2,
    parent_number: 1,
    kind: 'manual_edit',
    actor: 'user',
    reason: 'demo history',
    proposal_id: null,
    restored_from_number: null,
    block_version_id: null,
    created_at: '2026-11-11T12:00:00Z',
  },
  {
    id: 'v1',
    number: 1,
    parent_number: null,
    kind: 'bootstrap',
    actor: 'system',
    reason: null,
    proposal_id: null,
    restored_from_number: null,
    block_version_id: null,
    created_at: '2026-11-10T12:00:00Z',
  },
]
type Request = { url: string; method: string; body: unknown }
let requests: Request[] = []
let head = view
let nextWrite = {
  version: 3,
  kind: 'manual_edit',
  stale_proposals: [],
  preserved_session_uids: [],
} as {
  version: number
  kind: string
  stale_proposals: string[]
  preserved_session_uids: string[]
}
let writeError: number | null = null
const wrap = (data: unknown) => ({ schema_version: 'v1', data_revision: 2, mode: 'demo', data })
function mount(weekStart?: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 }, mutations: { retry: false } },
  })
  return render(<Calendar unit="mi" weekStart={weekStart} />, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
}
const day = (date: string) =>
  document.querySelector(`[data-testid="calendar-day"][data-date="${date}"]`) as HTMLElement
const row = (date: string) => {
  const element = within(day(date)).getAllByTestId('session-row')[0]
  const details = element.querySelector('details')
  if (details && !details.open) fireEvent.click(within(element).getByText('Session details'))
  return element
}
const writes = () => requests.filter((r) => r.method !== 'GET')
beforeEach(() => {
  requests = []
  head = view
  nextWrite = { version: 3, kind: 'manual_edit', stale_proposals: [], preserved_session_uids: [] }
  writeError = null
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = String(input),
        method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : null
      requests.push({ url, method, body })
      if (writeError && method !== 'GET')
        return new Response(
          JSON.stringify({
            error: {
              code: writeError === 409 ? 'calendar_head_moved' : 'validation_error',
              message: 'Rejected',
            },
          }),
          { status: writeError },
        )
      if (url.includes('/calendar/week')) {
        const params = new URLSearchParams(url.split('?')[1])
        const start = params.get('start') ?? view.start
        const end = addDays(start, 6)
        const inWeek = ({ local_date }: { local_date: string | null }) =>
          local_date !== null && local_date >= start && local_date <= end
        const week = {
          ...head,
          start,
          end,
          version: params.has('version') ? Number(params.get('version')) : head.version,
          sessions: head.sessions.filter(inWeek),
          completions: head.completions.filter(inWeek),
          recorded_runs: head.recorded_runs.filter(inWeek),
        }
        return new Response(JSON.stringify(wrap(week)), { status: 200 })
      }
      const data = url.includes('/calendar/versions')
        ? { items: versions }
        : url.includes('/calendar/diff')
          ? { changes: [] }
          : url.includes('/activities')
            ? {
                items: [
                  { id: 'a9', local_date: '2026-11-09', distance_m: 5000, sport: 'running' },
                  {
                    id: 'a10',
                    local_date: '2026-11-09',
                    distance_m: 8000,
                    sport: 'treadmill_running',
                  },
                  { id: 'a11', local_date: '2026-11-09', distance_m: 20000, sport: 'cycling' },
                  {
                    id: 'a12',
                    local_date: '2026-11-09',
                    distance_m: 10000,
                    sport: 'trail_running',
                  },
                ],
              }
            : url.includes('/calendar/completions')
              ? { ...completion, session_uid: 's3', status: 'skipped' }
              : url.includes('/calendar/edits') || url.includes('/calendar/rollback')
                ? nextWrite
                : head
      return new Response(JSON.stringify(wrap(data)), { status: method === 'GET' ? 200 : 201 })
    }),
  )
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('week navigation', () => {
  beforeEach(() => {
    window.location.hash = ''
  })

  it('shows the current week with arrows and no This week button', async () => {
    mount()
    expect(await screen.findByRole('heading', { name: 'Nov 9–Nov 15 This week' })).toBeVisible()
    expect(screen.getAllByTestId('calendar-day').map((day) => day.dataset.date)).toEqual([
      '2026-11-09',
      '2026-11-10',
      '2026-11-11',
      '2026-11-12',
      '2026-11-13',
      '2026-11-14',
      '2026-11-15',
    ])
    expect(screen.getByRole('button', { name: 'Previous week' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Next week' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'This week' })).not.toBeInTheDocument()
  })

  it('moves one week through the hash', async () => {
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Next week' }))
    expect(window.location.hash).toBe('#calendar/2026-11-16')
    fireEvent.click(screen.getByRole('button', { name: 'Previous week' }))
    expect(window.location.hash).toBe('#calendar/2026-11-02')
  })

  it('fetches only the shown week and reuses the current week cache', async () => {
    const requestedWeeks = () =>
      requests.map((r) => r.url).filter((url) => url.includes('/calendar/week'))
    const { rerender } = mount()
    await screen.findByRole('heading', { name: /This week/ })
    expect(requestedWeeks()).toEqual(['/api/v1/calendar/week'])

    const previous = screen.getByRole('button', { name: 'Previous week' })
    previous.focus()
    rerender(<Calendar unit="mi" weekStart="2026-11-06" />)
    expect(screen.getByRole('button', { name: 'Previous week' })).toBe(previous)
    expect(previous).toHaveFocus()
    expect(screen.queryAllByTestId('calendar-day')).toHaveLength(0)
    await screen.findAllByTestId('calendar-day')
    expect(requestedWeeks()).toEqual([
      '/api/v1/calendar/week',
      '/api/v1/calendar/week?start=2026-11-02',
    ])
    expect(screen.getAllByTestId('calendar-day').map((day) => day.dataset.date)).toEqual([
      '2026-11-02',
      '2026-11-03',
      '2026-11-04',
      '2026-11-05',
      '2026-11-06',
      '2026-11-07',
      '2026-11-08',
    ])
    fireEvent.click(screen.getByRole('button', { name: 'This week' }))
    expect(window.location.hash).toBe('#calendar')
    rerender(<Calendar unit="mi" weekStart={null} />)
    expect(await screen.findByRole('heading', { name: /This week/ })).toBeVisible()
    expect(requestedWeeks()).toHaveLength(2)
  })

  it.each([
    { weekStart: '2026-11-23', lastPlannedDate: '2026-12-02', canAdvance: true },
    { weekStart: '2026-11-30', lastPlannedDate: '2026-12-02', canAdvance: false },
    { weekStart: '2026-11-09', lastPlannedDate: '2026-11-15', canAdvance: true },
    { weekStart: '2026-11-16', lastPlannedDate: '2026-11-15', canAdvance: false },
  ])(
    'sets Next week availability at $weekStart when the plan ends $lastPlannedDate',
    async ({ weekStart, lastPlannedDate, canAdvance }) => {
      head = { ...view, last_planned_date: lastPlannedDate }
      mount(weekStart)
      const next = await screen.findByRole('button', { name: 'Next week' })
      if (canAdvance) expect(next).toBeEnabled()
      else expect(next).toBeDisabled()
    },
  )

  it('allows unlimited history', async () => {
    mount('2026-01-05')
    expect(await screen.findByRole('button', { name: 'Previous week' })).toBeEnabled()
    const days = screen.getAllByTestId('calendar-day')
    expect(days).toHaveLength(7)
    for (const day of days) expect(within(day).getByText('No session')).toBeVisible()
  })

  it('applies a viewed version to the shown week', async () => {
    mount('2026-11-16')
    fireEvent.click(await screen.findByText('Plan versions'))
    const version = (await screen.findByText('v1 · Setup')).closest('.version-row') as HTMLElement
    fireEvent.click(within(version).getByRole('button', { name: 'View' }))
    expect(await screen.findByText(/Viewing version 1 \(read-only\)/)).toBeVisible()
    expect(requests.some((r) => r.url === '/api/v1/calendar/week?start=2026-11-16&version=1')).toBe(
      true,
    )
  })
})

describe('Calendar', () => {
  it('downloads the chosen Monday–Sunday week with workout details', async () => {
    const create = vi.fn((blob: Blob) => {
      void blob
      return 'blob:weekly-workouts'
    })
    const revoke = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL: create, revokeObjectURL: revoke })
    const clicked: HTMLAnchorElement[] = []
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push(this)
    })
    const { rerender } = mount()
    await screen.findByText('Version 2')
    fireEvent.click(screen.getByRole('button', { name: 'Download week' }))
    expect(create).toHaveBeenCalledOnce()
    const link = clicked[0]
    expect(link.download).toBe('workouts-2026-11-09.txt')
    expect(revoke).toHaveBeenCalledWith('blob:weekly-workouts')
    const blob = create.mock.calls[0][0] as Blob
    expect(blob.type).toBe('text/plain;charset=utf-8')
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result))
      reader.readAsText(blob)
    })
    expect(text).toContain('Workouts: 2026-11-09 to 2026-11-15')
    expect(text).toContain('2026-11-09')
    expect(text).toContain('Easy')
    expect(text).not.toContain('2026-11-16')
    rerender(<Calendar unit="mi" weekStart="2026-11-16" />)
    const download = screen.getByRole('button', { name: 'Download week' })
    await waitFor(() => expect(download).toBeEnabled())
    fireEvent.click(download)
    expect(clicked[1].download).toBe('workouts-2026-11-16.txt')
    click.mockRestore()
  })

  it('exports structured prescriptions, notes, and empty days', () => {
    const planned = {
      ...sessions[0],
      local_date: '2026-11-09',
      notes: 'Stay relaxed',
      structure: [
        {
          type: 'repeat' as const,
          count: 2,
          steps: [
            {
              type: 'work' as const,
              duration_type: 'time' as const,
              duration_value: 300,
              target: { modality: 'effort' as const, low: null, high: null, effort_cue: 'steady' },
            },
          ],
        },
      ],
    }
    const text = weeklyWorkoutText(
      [planned, { ...planned, session_uid: 'deleted', deleted: true }],
      '2026-11-09',
      'mi',
    )
    expect(text).toContain('2 ×\n      Work 5:00 · steady')
    expect(text).toContain('Notes: Stay relaxed')
    expect(text).toContain('No planned session')
    expect(text.match(/Notes: Stay relaxed/g)).toHaveLength(1)
  })

  it('links coach versions to their proposal', async () => {
    const original = versions[0]
    try {
      versions[0] = { ...versions[0], proposal_id: 'p9' }
      mount()
      await screen.findByText('Version 2')
      fireEvent.click(screen.getByText('Plan versions'))
      expect(await screen.findByRole('link', { name: 'Open proposal' })).toHaveAttribute(
        'href',
        '#proposal/p9',
      )
      expect(screen.getAllByRole('link', { name: 'Open proposal' })).toHaveLength(1)
    } finally {
      versions[0] = original
    }
  })

  it('shows a run from before plan setup without labeling it missed or extra', async () => {
    head = {
      ...view,
      recorded_runs: [
        { activity_id: 'early-run', local_date: '2026-11-05', distance_m: 6740, timer_s: 2400 },
      ],
    }
    mount('2026-11-02')
    await screen.findByText('Version 2')
    const thursday = within(day('2026-11-05'))
    expect(thursday.getByText('Recorded run')).toBeInTheDocument()
    expect(thursday.getByText(/4.2 mi/)).toBeInTheDocument()
    expect(thursday.getByRole('link', { name: 'Open run' })).toHaveAttribute(
      'href',
      '#activity/early-run',
    )
    expect(thursday.queryByText('No session')).not.toBeInTheDocument()
    expect(thursday.queryByText(/Extra run|Missed|Not recorded/)).not.toBeInTheDocument()
    expect(writes()).toHaveLength(0)
  })

  it('reveals the full compact prescription and edit controls on demand', async () => {
    mount()
    await screen.findByText('Version 2')
    const planned = within(day('2026-11-12')).getByTestId('session-row')
    expect(planned.querySelector('details')).not.toHaveAttribute('open')
    fireEvent.click(within(planned).getByText('Session details'))
    const summary = within(planned).getByText('Session details')
    fireEvent.keyDown(planned.querySelector('details')!, { key: 'Escape' })
    expect(planned.querySelector('details')).not.toHaveAttribute('open')
    expect(summary).toHaveFocus()
    fireEvent.click(summary)
    fireEvent.click(within(planned).getByRole('button', { name: 'Close details' }))
    expect(planned.querySelector('details')).not.toHaveAttribute('open')
    expect(summary).toHaveFocus()
    fireEvent.click(summary)
    fireEvent.click(within(planned).getByRole('button', { name: 'Edit' }))
    expect(screen.getByRole('dialog', { name: 'Edit session' })).toBeInTheDocument()
    expect(screen.getByText('Plan versions').closest('details')).not.toHaveAttribute('open')
  })

  it('closes editors and outcome dialogs with Escape and restores focus', async () => {
    mount()
    await screen.findByText('Version 2')
    const edit = within(row('2026-11-12')).getByRole('button', { name: 'Edit' })
    edit.focus()
    fireEvent.click(edit)
    const editor = screen.getByRole('dialog', { name: 'Edit session' })
    expect(editor.contains(document.activeElement)).toBe(true)
    fireEvent.keyDown(editor, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(edit).toHaveFocus())
    const outcome = within(row('2026-11-09')).getByRole('button', { name: 'Record outcome' })
    outcome.focus()
    fireEvent.click(outcome)
    const outcomeDialog = screen.getByRole('dialog', { name: 'Record outcome' })
    expect(outcomeDialog.contains(document.activeElement)).toBe(true)
    fireEvent.keyDown(outcomeDialog, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(outcome).toHaveFocus())
    expect(writes()).toHaveLength(0)
  })

  it('renders days, markers, repeated steps and history', async () => {
    mount()
    expect(await screen.findByText('Version 2')).toBeInTheDocument()
    expect(within(row('2026-11-15')).getByText('Provisional')).toBeInTheDocument()
    expect(row('2026-11-15')).toHaveClass('certainty-provisional')
    expect(within(row('2026-11-09')).getByText('Not recorded')).toBeInTheDocument()
    expect(
      within(row('2026-11-09')).getByRole('button', { name: 'Record outcome' }),
    ).toBeInTheDocument()
    expect(within(row('2026-11-10')).getByRole('link', { name: 'Open run' })).toHaveAttribute(
      'href',
      '#activity/a9',
    )
    expect(
      within(row('2026-11-10')).getByText('Work 800 m · 6:42 /mi–7:04 /mi'),
    ).toBeInTheDocument()
    expect(within(row('2026-11-10')).getByText('4 ×')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Plan versions'))
    expect(screen.getByText('v2 · Manual edit')).toBeInTheDocument()
    expect(screen.getByText('v1 · Setup')).toBeInTheDocument()
    expect(screen.getAllByTestId('calendar-day')).toHaveLength(7)
  })
  it('moves one session with an exact versioned edit', async () => {
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Move' }))
    fireEvent.change(screen.getByLabelText('New date'), { target: { value: '2026-11-13' } })
    fireEvent.change(screen.getByLabelText('Reason for change (optional)'), {
      target: { value: 'trip' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save move' }))
    await waitFor(() => expect(screen.getByText('Saved as version 3.')).toBeInTheDocument())
    expect(writes()[0]).toMatchObject({
      url: '/api/v1/calendar/edits',
      method: 'POST',
      body: {
        expected_head: 2,
        reason: 'trip',
        edits: [{ op: 'move', session_uid: 's1', fields: { local_date: '2026-11-13' } }],
      },
    })
    await waitFor(() =>
      expect(
        requests.filter((r) => r.url === '/api/v1/calendar/week' && r.method === 'GET').length,
      ).toBeGreaterThanOrEqual(2),
    )
  })
  describe('move window', () => {
    async function openMove(lastPlannedDate: string | null) {
      head = { ...view, last_planned_date: lastPlannedDate }
      mount()
      await screen.findByText('Version 2')
      fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Move' }))
      return screen.getByLabelText('New date')
    }

    it.each([
      ['allows a move to the last planned date', '2026-12-11', '2026-12-11'],
      ['keeps the 14-day minimum for a short plan', '2026-11-16', '2026-11-24'],
    ])('%s', async (_name, planEnd, max) => {
      const input = await openMove(planEnd)
      expect(input).toHaveAttribute('max', max)
      fireEvent.change(input, { target: { value: max } })
      fireEvent.click(screen.getByRole('button', { name: 'Save move' }))
      await waitFor(() => expect(writes()).toHaveLength(1))
      expect(writes()[0].body).toMatchObject({
        edits: [{ op: 'move', session_uid: 's1', fields: { local_date: max } }],
      })
    })

    it.each([
      [
        'rejects a move one day past the last planned date',
        '2026-12-11',
        '2026-12-11',
        '2026-12-12',
        'Dec 11',
      ],
      ['caps the window at 42 days', '2026-12-31', '2026-12-23', '2026-12-24', 'Dec 23'],
    ])('%s', async (_name, planEnd, max, value, date) => {
      const input = await openMove(planEnd)
      expect(input).toHaveAttribute('max', max)
      fireEvent.change(input, { target: { value } })
      fireEvent.click(screen.getByRole('button', { name: 'Save move' }))
      expect(screen.getByRole('alert')).toHaveTextContent(`Pick a date between today and ${date}.`)
      expect(writes()).toHaveLength(0)
    })

    it('uses the 14-day window when there is no last planned date', async () => {
      expect(await openMove(null)).toHaveAttribute('max', '2026-11-24')
    })
  })

  it('edits changed fields only and omits empty reason', async () => {
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByLabelText('Intent'), { target: { value: 'Easy, flat' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save session' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0].body).toEqual({
      expected_head: 2,
      edits: [{ op: 'modify', session_uid: 's1', fields: { intent: 'Easy, flat' } }],
    })
  })
  it('adds at the next slot with converted duration', async () => {
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(day('2026-11-14')).getByRole('button', { name: 'Add session' }))
    fireEvent.change(screen.getByLabelText('Intent'), { target: { value: 'Shakeout' } })
    fireEvent.change(screen.getByLabelText('Planned duration (minutes)'), {
      target: { value: '20' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save session' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0].body).toEqual({
      expected_head: 2,
      edits: [
        {
          op: 'add',
          fields: {
            local_date: '2026-11-14',
            slot: 0,
            kind: 'run',
            recipe_id: 'REC001',
            custom: false,
            intent: 'Shakeout',
            planned_duration_s: 1200,
            planned_distance_m: null,
            structure: null,
            strength_slot_id: null,
            notes: null,
          },
        },
      ],
    })
  })
  it('confirms deletion before writing', async () => {
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-15')).getByRole('button', { name: 'Delete' }))
    expect(writes()).toHaveLength(0)
    fireEvent.click(within(row('2026-11-15')).getByRole('button', { name: 'Confirm delete' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0].body).toEqual({
      expected_head: 2,
      edits: [{ op: 'delete', session_uid: 's2', fields: {} }],
    })
  })
  it('offers reload on head conflict and reports stale proposals', async () => {
    writeError = 409
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Delete' }))
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Confirm delete' }))
    expect(await screen.findByText(/The calendar changed since you loaded it/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reload calendar' }))
    await waitFor(() =>
      expect(
        requests.filter((r) => r.url === '/api/v1/calendar/week' && r.method === 'GET').length,
      ).toBeGreaterThanOrEqual(2),
    )
  })
  it('shows stale coach proposal count', async () => {
    nextWrite = { ...nextWrite, stale_proposals: ['x'] }
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Delete' }))
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Confirm delete' }))
    expect(
      await screen.findByText('This edit made 1 pending coach proposal(s) stale.'),
    ).toBeInTheDocument()
  })
  it('restores only the advertised protected target', async () => {
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(screen.getByText('Plan versions'))
    expect(
      within(screen.getAllByTestId('version-row')[0]).queryByRole('button', { name: 'Restore' }),
    ).not.toBeInTheDocument()
    fireEvent.click(
      within(screen.getAllByTestId('version-row')[1]).getByRole('button', { name: 'Restore' }),
    )
    expect(
      screen.getByText(/Completed, locked and historical sessions were preserved/),
    ).toBeInTheDocument()
    expect(screen.getByText('Preserved: s4')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm restore' }))
    await waitFor(() =>
      expect(screen.getByText('Restored version 1 as version 3.')).toBeInTheDocument(),
    )
    expect(writes()[0].url).toBe('/api/v1/calendar/rollback')
    expect(writes()[0].body).toEqual({ expected_head: 2, to_version: 1 })
  })
  it('views historical version read-only', async () => {
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(screen.getByText('Plan versions'))
    fireEvent.click(
      within(screen.getAllByTestId('version-row')[1]).getByRole('button', { name: 'View' }),
    )
    expect(await screen.findByText(/Viewing version 1 \(read-only\)/)).toBeInTheDocument()
    expect(
      requests.some((r) => r.url.includes('/calendar/week') && r.url.includes('version=1')),
    ).toBe(true)
    expect(screen.queryByRole('button', { name: 'Move' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add session' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Record outcome' })).not.toBeInTheDocument()
  })
  it('marks a past workout complete without attaching a recording', async () => {
    mount()
    await screen.findByText('Version 2')
    expect(within(row('2026-11-15')).queryByRole('button', { name: 'Mark complete' })).toBeNull()
    fireEvent.click(within(row('2026-11-09')).getByRole('button', { name: 'Mark complete' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0]).toMatchObject({
      url: '/api/v1/calendar/completions/s3',
      body: { status: 'completed_as_planned', expected_version: 0 },
    })
  })
  it('records skipped outcome without inferred status fields', async () => {
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-09')).getByRole('button', { name: 'Record outcome' }))
    fireEvent.click(screen.getByRole('button', { name: 'Skipped' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0]).toMatchObject({
      url: '/api/v1/calendar/completions/s3',
      method: 'PUT',
      body: { status: 'skipped' },
    })
  })
  it('links a nearby run with a server-derived match method and version guard', async () => {
    head = {
      ...view,
      completions: [
        ...view.completions,
        {
          ...completion,
          id: 'c3',
          session_uid: 's3',
          local_date: '2026-11-09',
          activity_id: null,
          status: 'unknown',
          match_method: 'none',
          version: 4,
        },
      ],
    }
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-09')).getByRole('button', { name: 'Record outcome' }))
    await screen.findByRole('option', { name: /Nov 9 · 3.1 mi/ })
    fireEvent.change(await screen.findByLabelText('Link a run'), { target: { value: 'a9' } })
    fireEvent.click(screen.getByRole('button', { name: 'Link run' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0].body).toEqual({ activity_id: 'a9', expected_version: 4 })
  })
  it('offers treadmill and trail runs and hides other sports when linking', async () => {
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-09')).getByRole('button', { name: 'Record outcome' }))
    expect(await screen.findByRole('option', { name: 'Nov 9 · 3.1 mi' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Nov 9 · 5.0 mi' })).toHaveValue('a10')
    expect(screen.getByRole('option', { name: 'Nov 9 · 6.2 mi' })).toHaveValue('a12')
    expect(screen.queryByRole('option', { name: /12.4 mi/ })).not.toBeInTheDocument()
    const request = requests.find((r) => r.method === 'GET' && r.url.includes('/activities'))
    expect(request?.url).toEqual(
      '/api/v1/activities?start_date=2026-11-08&end_date=2026-11-10&limit=50',
    )
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
    await screen.findByText('Version 2')
    fireEvent.click(screen.getByText('Plan versions'))
    expect(screen.queryByRole('button', { name: 'Restore' })).not.toBeInTheDocument()
  })
  it('preserves exact metres during an unrelated edit and resolves a chosen placeholder recipe', async () => {
    head = {
      ...view,
      sessions: [
        session('s1', '2026-11-12', {
          planned_distance_m: 1610,
          recipe_id: null,
          placeholder: true,
        }),
      ],
    }
    mount()
    await screen.findByText('Version 2')
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Edit' }))
    fireEvent.change(screen.getByLabelText('Session'), { target: { value: 'REC002' } })
    fireEvent.change(screen.getByLabelText('Intent'), { target: { value: 'Long and easy' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save session' }))
    await waitFor(() => expect(writes()).toHaveLength(1))
    expect(writes()[0].body).toEqual({
      expected_head: 2,
      edits: [
        {
          op: 'modify',
          session_uid: 's1',
          fields: {
            recipe_id: 'REC002',
            placeholder: false,
            intent: 'Long and easy',
          },
        },
      ],
    })
  })
  it('keeps unlinked unknown sessions editable and linked unknown sessions protected', async () => {
    head = {
      ...view,
      completions: [
        ...view.completions,
        {
          ...completion,
          id: 'c1',
          session_uid: 's1',
          local_date: '2026-11-12',
          activity_id: null,
          status: 'unknown',
          match_method: 'none',
        },
        {
          ...completion,
          id: 'c2',
          session_uid: 's2',
          local_date: '2026-11-15',
          activity_id: 'a2',
          status: 'unknown',
        },
      ],
    }
    mount()
    await screen.findByText('Version 2')
    expect(within(row('2026-11-12')).getByRole('button', { name: 'Edit' })).toBeInTheDocument()
    expect(
      within(row('2026-11-15')).queryByRole('button', { name: 'Edit' }),
    ).not.toBeInTheDocument()
  })
  it('offers outcome recording only for the unlinked unknown past session', async () => {
    head = {
      ...view,
      completions: [
        {
          ...completion,
          id: 'c3',
          session_uid: 's3',
          local_date: '2026-11-09',
          activity_id: 'a1',
          status: 'unknown',
        },
        { ...completion, id: 'c4', activity_id: null, status: 'unknown', match_method: 'none' },
      ],
    }
    mount()
    await screen.findByText('Version 2')
    const linked = within(row('2026-11-09'))
    expect(linked.getByText('Recorded · comparison unavailable')).toBeInTheDocument()
    expect(linked.queryByText('Not recorded')).not.toBeInTheDocument()
    expect(linked.queryByRole('button', { name: 'Record outcome' })).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Record outcome' })).not.toBeInTheDocument()
    fireEvent.click(within(row('2026-11-10')).getByRole('button', { name: 'Record outcome' }))
    expect(screen.getByRole('dialog', { name: 'Record outcome' })).toBeInTheDocument()
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
    await waitFor(() =>
      expect(
        requests.filter((r) => r.url === '/api/v1/calendar/week' && r.method === 'GET').length,
      ).toBeGreaterThanOrEqual(2),
    )
    fireEvent.click(within(row('2026-11-12')).getByRole('button', { name: 'Edit' }))
    expect(screen.getByLabelText('Intent')).toHaveValue('Easy')
  })
  it('shows imported prose and includes mobility in the editor', async () => {
    head = {
      ...view,
      sessions: [
        session('s1', '2026-11-12', { kind: 'mobility', intent: 'Easy mobility' }),
        session('s4', '2026-11-10', {
          recipe_id: null,
          legacy_unstructured: true,
          intent: 'Old easy prescription',
          notes: 'Keep this plan prose',
        }),
      ],
    }
    mount()
    await screen.findByText('Version 2')
    expect(within(row('2026-11-10')).getByText('Imported run')).toBeInTheDocument()
    expect(within(row('2026-11-10')).getByText('Old easy prescription')).toBeInTheDocument()
    expect(within(row('2026-11-10')).getByText('Keep this plan prose')).toBeInTheDocument()
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
