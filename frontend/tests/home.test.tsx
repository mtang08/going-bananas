import type { ExceptionsView, Finding, Patch, Severity } from '../src/api/types/exceptions'
import type {
  RunningInterruption,
  RunningInterruptionView,
} from '../src/api/types/runningInterruption'
import { EXCEPTION_PROMPT, INTERRUPTION_PROMPT } from '../src/coachPrompts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Home } from '../src/pages/Home'
import type { ProposalSummary } from '../src/api/types/coach'
import { addDays } from '../src/lib/format'
import type { BlockVersion, TargetEvent } from '../src/api/types/blocks'
import type { CalendarView, DigestRow, SessionState, WeeklyDigest } from '../src/api/types/calendar'

const emptyInterruption = (): RunningInterruptionView => ({
  today: '2026-11-11',
  profile_version: 3,
  interruption: null,
  phase: null,
  affected_runs: [],
  affected_runs_omitted: 0,
  first_run: null,
  recorded_return: null,
  review_reason: null,
})
let interruption: RunningInterruptionView
let interruptionWriteError: 'network' | 'conflict' | null
const currentEpisode: RunningInterruption = {
  reason: 'travel',
  starts_on: '2026-11-11',
  return_on: '2026-11-16',
  review_on: null,
}

const finding = (id: string, severity: Severity, summary: string, version = 1): Finding => ({
  id,
  rule_code: 'FATIGUE_PERSISTING',
  category: 'accumulated_fatigue',
  severity,
  status: 'open',
  entity_key: `fatigue:${id}`,
  summary,
  evidence: [],
  evidence_at: '2026-11-11T12:00:00Z',
  first_seen_at: '2026-11-11T12:00:00Z',
  last_seen_at: '2026-11-11T12:00:00Z',
  patch_id: null,
  version,
  is_new_since_last_review: true,
})
const pa1: Patch = {
  id: 'pa1',
  proposal_id: 'p9',
  calendar_version_number: 2,
  category: 'accumulated_fatigue',
  severity: 'caution',
  ladder_level: 'next_days',
  window_start: '2026-11-11',
  window_end: '2026-11-13',
  reassess_on: '2026-11-11',
  monitor: ['Morning fatigue'],
  return_criteria: ['Fatigue below 6'],
  escalate_criteria: ['Fatigue rising'],
  unchanged: [],
  status: 'open',
  resolved_at: null,
  resolved_by: null,
  resolution_note: null,
  created_at: '2026-11-10T12:00:00Z',
  version: 1,
  session_uids: [],
  reassess_due: true,
}
const rec = {
  operation: 'exception_review' as const,
  reason: 'Open findings at caution or hold need an exception review',
  finding_ids: ['f1'],
  prompt: EXCEPTION_PROMPT,
}
const BM = {
  kind: 'time_trial' as const,
  event_id: null,
  protocol: '5 km solo time trial, flat loop',
  distance_m: 5000,
  planned_date: '2026-12-10',
  progress_if: 'Faster than 21:40',
  consolidate_if: 'Within 20 s of 21:40',
}
const activeBlock = (planned: string | null): BlockVersion => ({
  id: 'v1',
  block_uid: 'b1',
  version: 1,
  status: 'active',
  objective: 'Build consistency',
  why: [],
  maintained_qualities: ['Easy endurance'],
  non_goals: ['Peak racing'],
  eligible_recipe_ids: ['REC001'],
  progression_dimension: 'duration',
  constraints: [{ kind: 'schedule', text: 'Keep strength days' }],
  start_date: '2026-11-01',
  review_date: '2026-12-13',
  indicators: [],
  early_review_triggers: ['Symptoms increase'],
  objective_status: 'unresolved',
  created_at: '2026-11-01T12:00:00Z',
  proposal_id: 'p1',
  legacy_text: null,
  benchmark: planned ? { ...BM, planned_date: planned } : null,
  benchmark_status: {
    status: 'pending',
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
})

const session = (id: string, day: string, overrides: Partial<SessionState> = {}): SessionState => ({
  id,
  session_uid: id,
  local_date: day,
  slot: 1,
  kind: 'run',
  recipe_id: 'REC001',
  custom: false,
  intent: 'Comfortable effort',
  placeholder: false,
  locked: false,
  planned_duration_s: 1800,
  planned_distance_m: null,
  structure: null,
  strength_slot_id: null,
  notes: null,
  brief: null,
  certainty: 'committed',
  legacy_unstructured: false,
  legacy_payload: null,
  revision: 1,
  calendar_version_number: 2,
  deleted: false,
  is_original: true,
  changed_by_version: 2,
  exception_patch: null,
  ...overrides,
})
const baseSessions = () => [
  session('s1', '2026-11-11'),
  session('s2', '2026-11-13', { recipe_id: null, placeholder: true, is_original: false }),
  session('s3', '2026-11-19', { recipe_id: 'REC002', certainty: 'provisional' }),
]
const digestFor = (weekStart: string, done = 2): WeeklyDigest => {
  const by_outcome = {
    planned: 0,
    completed: done,
    modified: 0,
    partial: 0,
    moved: 0,
    missed: 0,
    recorded: 0,
    not_recorded: 0,
  }
  return {
    schema: 'weekly_digest.v1',
    decision_follow_up: null,
    week_start: weekStart,
    week_end: addDays(weekStart, 6),
    today: '2026-11-11',
    days_elapsed: 3,
    timezone: 'America/New_York',
    calendar_version: 2,
    plan_available: true,
    activity_coverage_complete: true,
    totals: {
      sessions: { planned: 5, planned_to_date: 3, done, by_outcome, removed: 0, unplanned: 0 },
      by_kind: {
        run: { planned: 3, planned_to_date: 2, done },
        strength: { planned: 2, planned_to_date: 1, done: 0 },
        cross: { planned: 0, planned_to_date: 0, done: 0 },
        rehab: { planned: 0, planned_to_date: 0, done: 0 },
        mobility: { planned: 0, planned_to_date: 0, done: 0 },
      },
      time: {
        planned_s: 18000,
        planned_to_date_s: 9000,
        planned_unknown: 0,
        actual_s: 7200,
        actual_unknown: 0,
        unplanned_s: 0,
      },
      run_distance: {
        planned_m: 30000,
        planned_to_date_m: 16000,
        planned_estimated: 0,
        planned_unknown: 0,
        actual_m: 12000,
        actual_unknown: 0,
      },
      key_sessions: { planned: 1, planned_to_date: 1, done: 1, by_outcome },
    },
    sessions: digestSessions.filter(
      (row) => row.local_date >= weekStart && row.local_date <= addDays(weekStart, 6),
    ),
    unplanned: [],
    removed: [],
  }
}
let proposalItems: ProposalSummary[]
let promptItems: unknown[]
let calendar: CalendarView
let exceptionsData: ExceptionsView
let blockData: BlockVersion | null
let error = false
let digestFail = false
let digestSessions: DigestRow[]
let requests: { url: string; method: string; body: unknown; headers: Headers }[]
const onCheckin = vi.fn()
const clients: QueryClient[] = []
beforeEach(() => {
  exceptionsData = {
    rule_version: 'exceptions.v1',
    findings: [],
    patches: [],
    review_recommended: [],
    counts: { observe: 0, caution: 0, hold: 0, escalate: 0 },
  }
  blockData = null
  proposalItems = []
  promptItems = [
    { id: 'p1', kind: 'rpe', activity_id: 'a1', session_uid: null, status: 'open' },
    { id: 'p2', kind: 'delayed_symptom', activity_id: 'a1', session_uid: null, status: 'open' },
  ]
  requests = []
  error = false
  onCheckin.mockReset()
  digestFail = false
  digestSessions = []
  interruption = emptyInterruption()
  interruptionWriteError = null
  calendar = {
    today: '2026-11-11',
    timezone: 'America/New_York',
    start: '2026-11-04',
    end: '2026-11-24',
    head: 2,
    version: 2,
    undo: null,
    last_planned_date: null,
    sessions: baseSessions(),
    completions: [],
    recorded_runs: [],
  }
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
      if (url.endsWith('/running-interruption') && method === 'PUT') {
        if (interruptionWriteError === 'network') throw new Error('offline')
        if (interruptionWriteError === 'conflict')
          return {
            ok: false,
            status: 409,
            json: async () => ({ error: { code: 'version_conflict', message: 'Profile changed' } }),
          }
        const body = JSON.parse(String(init?.body))
        interruption = body.interruption
          ? {
              ...interruption,
              interruption: body.interruption,
              profile_version: body.expected_version + 1,
              phase: body.interruption.return_on ? 'paused' : 'review_due',
            }
          : { ...emptyInterruption(), profile_version: body.expected_version + 1 }
      }
      if (url.endsWith('/calendar') && error)
        return {
          ok: false,
          status: 500,
          json: async () => ({ error: { code: 'request_failed', message: 'boom' } }),
        }
      if (url.includes('/calendar/weekly-digest') && digestFail)
        return {
          ok: false,
          status: 500,
          json: async () => ({ error: { code: 'request_failed', message: 'digest boom' } }),
        }
      const data = url.endsWith('/running-interruption')
        ? interruption
        : url.endsWith('/sync/status')
          ? { datasets: [], active_jobs: [] }
          : url.includes('/calendar/weekly-digest')
            ? digestFor(
                new URL(url, 'http://x').searchParams.get('week_start') ?? '2026-11-09',
                url.includes('week_start') ? 1 : 2,
              )
            : url.includes('/coach/proposals')
              ? { items: proposalItems }
              : url.endsWith('/calendar')
                ? calendar
                : url.endsWith('/prompts')
                  ? { items: promptItems }
                  : url.endsWith('/activities/a1')
                    ? { id: 'a1', local_date: '2026-11-10', distance_m: 6437.376, sport: 'running' }
                    : url.includes('/exceptions') || url.includes('/exception-patches')
                      ? exceptionsData
                      : url.includes('/blocks/active')
                        ? blockData
                        : null
      return {
        ok: true,
        status: 200,
        json: async () => ({ schema_version: 'v1', data_revision: 1, mode: 'demo', data }),
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
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  return render(
    <QueryClientProvider client={client}>
      <Home unit="mi" onCheckin={onCheckin} />
    </QueryClientProvider>,
  )
}

describe('training home', () => {
  it("shows today's plan", async () => {
    mount()
    await screen.findByRole('heading', { name: 'Wednesday, November 11' })
    const card = screen.getByTestId('today-card')
    expect(within(card).getByText('Easy run')).toBeInTheDocument()
    expect(within(card).getByText('30m')).toBeInTheDocument()
  })
  it('links the upcoming workout to Calendar', async () => {
    mount()
    const card = within(await screen.findByTestId('today-card'))
    expect(card.getByRole('link', { name: 'Open workout on Calendar' })).toHaveAttribute(
      'href',
      '#calendar/2026-11-11',
    )
  })
  it('links a finished workout to its recorded run and omits removed rows', async () => {
    calendar.sessions.push(session('deleted-run', '2026-11-11', { deleted: true }))
    calendar.completions = [
      {
        id: 'c1',
        input_version: 1,
        session_uid: 's1',
        activity_id: 'a1',
        strong_workout_id: null,
        manual_session_id: null,
        status: 'completed_as_planned',
        match_method: 'auto_same_day',
        modification_reason: null,
        reason_note: null,
        version: 1,
        updated_at: '2026-11-11T11:00:00Z',
        local_date: '2026-11-11',
      },
    ]
    mount()
    const card = within(await screen.findByTestId('today-card'))
    expect(card.getByRole('link', { name: 'Open run and feedback' })).toHaveAttribute(
      'href',
      '#activity/a1',
    )
    expect(card.getAllByTestId('session-tag')).toHaveLength(1)
  })
  it("flags a running restriction on Today's accepted prescription", async () => {
    calendar.sessions[0].running_restriction_conflict =
      'Running restriction on 2026-11-11 caps each run at 900 s.'
    mount()
    const card = within(await screen.findByTestId('today-card'))
    expect(card.getByRole('status')).toHaveTextContent('caps each run at 900 s')
    expect(card.getByRole('link', { name: 'Open workout on Calendar' })).toBeVisible()
  })
  it('shows the coach brief on the Today card', async () => {
    calendar.sessions[0].intent = 'Threshold control'
    calendar.sessions[0].brief = {
      effort: { rpe_low: 6, rpe_high: 7, feel: 'controlled' },
      focus: ['Even splits'],
      adjust_if: [{ when: 'Rep pace fades more than 5%', then: 'stop after rep 4' }],
      why: 'Last two sessions hit pace at RPE 7',
    }
    mount()
    const card = within(await screen.findByTestId('today-card'))
    expect(card.getByText('RPE 6–7')).toBeVisible()
    expect(card.getByRole('heading', { name: 'Adjust if' })).toBeVisible()
    expect(card.getByText('Rep pace fades more than 5%').closest('li')).toHaveTextContent(
      'Rep pace fades more than 5% → stop after rep 4',
    )
    expect(card.getByText('Why and notes').closest('details')).not.toHaveAttribute('open')
  })

  it('prompt actions open the right check-in', async () => {
    mount()
    await screen.findByText('Rate your run on Nov 10 · 4.0 mi')
    fireEvent.click(screen.getByRole('button', { name: 'Add RPE' }))
    expect(onCheckin).toHaveBeenCalledWith({
      kind: 'post_run',
      prompt: expect.objectContaining({ id: 'p1' }),
      activityId: 'a1',
    })
    fireEvent.click(screen.getByRole('button', { name: 'Answer check' }))
    expect(onCheckin).toHaveBeenCalledWith({
      kind: 'delayed_followup',
      prompt: expect.objectContaining({ id: 'p2' }),
      activityId: 'a1',
    })
    expect(requests.filter((r) => r.url.endsWith('/activities/a1'))).toHaveLength(1)
  })
  it('dismiss posts and refetches prompts', async () => {
    mount()
    fireEvent.click((await screen.findAllByRole('button', { name: 'Dismiss' }))[0])
    await waitFor(() => expect(requests.filter((r) => r.url.endsWith('/prompts'))).toHaveLength(2))
    const request = requests.find((r) => r.method === 'POST')!
    expect(request.url).toBe('/api/v1/prompts/p1/dismiss')
    expect(request.headers.get('X-Local-Request')).toBe('1')
    expect(request.body).toEqual({})
  })
  it('shows empty block', async () => {
    mount()
    const blockLine = await screen.findByTestId('block-line')
    expect(blockLine).toHaveTextContent('No active training block. Training block')
    expect(within(blockLine).getByRole('link', { name: 'Training block' })).toHaveAttribute(
      'href',
      '#block',
    )
  })
  it('shows the block benchmark line', async () => {
    blockData = activeBlock('2026-11-14')
    mount()
    await screen.findByText(/Ends with/)
    const line = screen.getByTestId('block-line')
    expect(line).toHaveTextContent(
      'Block: Build consistency · Ends with 5 km solo time trial, flat loop on Nov 14 (3 days) · Pending',
    )
    expect(line).not.toHaveTextContent('Pending · Nov 14')
    expect(within(line).getByRole('link', { name: 'View training block' })).toHaveAttribute(
      'href',
      '#block',
    )
  })
  it('drops the day count on the benchmark day', async () => {
    blockData = activeBlock('2026-11-11')
    mount()
    const line = await screen.findByTestId('block-line')
    expect(line).toHaveTextContent('on Nov 11 · Pending')
    expect(line).not.toHaveTextContent('days)')
  })
  it('says a block without a benchmark is judged on training indicators', async () => {
    blockData = activeBlock(null)
    mount()
    expect(await screen.findByTestId('block-line')).toHaveTextContent(
      'Block: Build consistency · No benchmark this block · judged on training indicators',
    )
  })
  const half: TargetEvent = {
    id: 'e1',
    name: 'NYC Half',
    event_date: '2027-03-14',
    distance_m: 21098,
    purpose: 'pr',
    goal_time_s: 6300,
    rank: 1,
  }

  it.each([
    ['2027-03-14', 'Mar 14, 17 wk'],
    ['2026-11-20', 'Nov 20, 9 d'],
  ])('names a current goal race on %s and gives the time remaining', async (date, when) => {
    blockData = {
      ...activeBlock('2026-11-14'),
      target_event: { ...half, event_date: date },
      target_event_status: 'current',
    }
    mount()
    expect(await screen.findByTestId('block-line')).toHaveTextContent(
      `Pending · Building toward NYC Half (${when}) · View training block`,
    )
  })

  it.each(['changed', 'unset'] as const)(
    'says the goal race changed when the target is %s',
    async (status) => {
      blockData = { ...activeBlock('2026-11-14'), target_event: half, target_event_status: status }
      mount()
      const line = await screen.findByTestId('block-line')
      expect(line).toHaveTextContent('Goal race changed; next review re-targets')
      expect(line).not.toHaveTextContent('Building toward')
    },
  )

  it('adds nothing for a block with no goal race', async () => {
    blockData = { ...activeBlock('2026-11-14'), target_event_status: 'none' }
    mount()
    const line = await screen.findByTestId('block-line')
    expect(line).toHaveTextContent('Pending · View training block')
    expect(line).not.toHaveTextContent(/Building toward|Goal race changed/)
  })

  it('shows setup without a calendar', async () => {
    calendar = { ...calendar, head: 0, sessions: [] }
    mount()
    expect(await screen.findByText('No calendar yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open setup' })).toHaveAttribute('href', '#settings')
    expect(screen.queryByTestId('today-card')).not.toBeInTheDocument()
  })
  it('shows the plan-end banner for a short plan', async () => {
    calendar.sessions = calendar.sessions.slice(0, 2)
    mount()
    expect(await screen.findByTestId('plan-end-banner')).toHaveTextContent(
      'Plan ends on Nov 13 — run the weekly review',
    )
  })
  it('omits the plan-end banner for a longer plan', async () => {
    mount()
    await screen.findByTestId('today-card')
    expect(screen.queryByTestId('plan-end-banner')).not.toBeInTheDocument()
  })
  it('shows a calendar error without hiding independent panels', async () => {
    error = true
    mount()
    expect(await screen.findByText('Could not load this view')).toBeInTheDocument()
    expect(screen.getByText('boom')).toBeInTheDocument()
    expect(await screen.findByTestId('block-line')).toBeInTheDocument()
  })
  it('shows Planned vs done for the current week', async () => {
    mount()
    const digest = await screen.findByTestId('weekly-digest')
    expect(digest).toHaveTextContent('2 of 3 sessions done so far · 5 planned this week')
    expect(digest).toHaveTextContent('Nov 9–Nov 15')
    expect(within(digest).getByRole('button', { name: 'This week' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(requests.some(({ url }) => url.endsWith('/calendar/weekly-digest'))).toBe(true)
    expect(requests.some(({ url }) => url.includes('week_start'))).toBe(false)
  })
  it('loads the previous Monday for Last week', async () => {
    mount()
    const current = await screen.findByTestId('weekly-digest')
    fireEvent.click(within(current).getByRole('button', { name: 'Last week' }))
    const last = await screen.findByTestId('weekly-digest')
    expect(last).toHaveTextContent('Nov 2–Nov 8')
    expect(last).toHaveTextContent('1 of 3 sessions done so far')
    expect(
      requests.some(({ url }) => url.endsWith('/calendar/weekly-digest?week_start=2026-11-02')),
    ).toBe(true)
    expect(within(last).getByRole('button', { name: 'Last week' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    fireEvent.click(within(last).getByRole('button', { name: 'This week' }))
    expect(await screen.findByTestId('weekly-digest')).toHaveTextContent('Nov 9–Nov 15')
  })
  it('keeps independent panels when the digest fails', async () => {
    digestFail = true
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent('digest boom')
    expect(await screen.findByTestId('today-card')).toBeInTheDocument()
  })
  it('lets the athlete leave a failed Last week', async () => {
    mount()
    const current = await screen.findByTestId('weekly-digest')
    digestFail = true
    fireEvent.click(within(current).getByRole('button', { name: 'Last week' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('digest boom')
    digestFail = false
    fireEvent.click(screen.getByRole('button', { name: 'Back to this week' }))
    expect(await screen.findByTestId('weekly-digest')).toHaveTextContent('Nov 9–Nov 15')
  })
  it('compacts repeats and preserves structured and imported prescription notes', async () => {
    calendar.sessions[0].notes = 'Stop if form deteriorates'
    calendar.sessions[0].structure = [
      {
        type: 'repeat',
        count: 2,
        steps: [
          { type: 'work', duration_type: 'time', duration_value: 60, target: null },
          { type: 'recovery', duration_type: 'time', duration_value: 30, target: null },
        ],
      },
    ]
    calendar.sessions.push(
      session('legacy', '2026-11-11', {
        recipe_id: null,
        slot: 2,
        legacy_unstructured: true,
        notes: 'Original prescribed easy progression',
      }),
    )
    mount()
    const card = await screen.findByTestId('today-card')
    expect(within(card).getByText('2 ×')).toBeVisible()
    expect(within(card).getByText('2 ×').closest('details')).toBeNull()
    expect(within(card).queryByText('Session details')).not.toBeInTheDocument()
    expect(within(card).queryByText('Session notes')).not.toBeInTheDocument()
    for (const toggle of within(card).getAllByText('Why and notes')) fireEvent.click(toggle)
    expect(within(card).getByText('Stop if form deteriorates')).toBeVisible()
    expect(within(card).getByText('Original prescribed easy progression')).toBeVisible()
    expect(within(card).getByText('Work 1:00 · effort')).toBeInTheDocument()
    expect(
      within(card).getByText('Recovery after every rep, including the final rep.'),
    ).toBeInTheDocument()
    expect(within(card).getByText('Stop if form deteriorates')).toBeInTheDocument()
    expect(within(card).getByText('Original prescribed easy progression')).toBeInTheDocument()
    expect(within(card).getByText('Structured comparison unavailable')).toBeInTheDocument()
    expect(within(card).queryByText('Quality slot')).not.toBeInTheDocument()
  })
  it('lists open proposals in Needs attention without deciding', async () => {
    proposalItems = [
      {
        id: 'p1',
        status: 'stale',
        operation: 'review_rolling_plan',
        submitted_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
        change_count: 3,
        headline: 'Keep tomorrow easy',
      } as ProposalSummary,
    ]
    mount()
    await screen.findByText('Weekly review')
    const row = document.querySelector('[data-kind="proposal"]')!
    for (const text of [
      'Stale — ask the coach to refresh',
      'Weekly review',
      '2 h ago',
      '3 changes',
    ])
      expect(row).toHaveTextContent(text)
    expect(within(row as HTMLElement).getByRole('link', { name: 'Review' })).toHaveAttribute(
      'href',
      '#proposal/p1',
    )
    expect(
      row.compareDocumentPosition(screen.getByRole('heading', { name: "Today's plan" })) &
        Node.DOCUMENT_POSITION_PRECEDING,
    ).toBeTruthy()
    expect(requests.every((r) => r.method === 'GET')).toBe(true)
  })
  it('puts today and open actions before weekly summaries', async () => {
    digestSessions = [
      {
        session_uid: 's1',
        local_date: '2026-11-10',
        slot: 1,
        kind: 'run',
        class: 'easy',
        recipe_id: 'REC001',
        custom: false,
        intent: null,
        key: false,
        changed: false,
        outcome: 'completed',
        modification_reason: null,
        planned_duration_s: 1800,
        planned_distance_m: null,
        planned_distance_estimated: false,
        actual: {
          subject: 'activity',
          id: 'a1',
          local_date: '2026-11-10',
          duration_s: 1800,
          distance_m: 5000,
          sport: 'running',
          avg_hr_bpm: 152,
          moving_pace_s_per_km: 360,
          rpe: 5,
          rpe_source: 'manual',
        },
        execution: null,
      },
    ]
    const { container } = mount()
    const sessions = await screen.findByTestId('week-sessions')
    expect(sessions).toHaveTextContent('Easy run')
    expect(
      Array.from(
        container.querySelectorAll(
          '[data-testid="home-status"], .home-gauges, [data-testid="needs-attention"], [data-testid="today-card"], [data-testid="week-sessions"]',
        ),
        (section) => section.getAttribute('data-testid') ?? section.className,
      ),
    ).toEqual(['today-card', 'needs-attention', 'home-status', 'home-gauges', 'week-sessions'])
    expect(screen.queryByText('Next week')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Last week' }))
    expect(await screen.findByRole('heading', { name: "Last week's sessions" })).toBeInTheDocument()
    expect(screen.getByTestId('week-sessions')).not.toHaveTextContent('Easy run')
    expect(
      requests.filter(({ url }) => url.endsWith('/calendar/weekly-digest?week_start=2026-11-02')),
    ).toHaveLength(1)
  })
  it('hides Needs attention when nothing needs it', async () => {
    promptItems = []
    mount()
    await screen.findByTestId('today-card')
    expect(screen.queryByTestId('needs-attention')).toBeNull()
  })
  it('has no page-level check-in button', async () => {
    mount()
    await screen.findByTestId('today-card')
    expect(screen.queryByRole('button', { name: 'Record check-in' })).toBeNull()
  })

  it('orders exception rows inside Needs attention', async () => {
    proposalItems = [
      {
        id: 'p1',
        status: 'stale',
        operation: 'review_rolling_plan',
        submitted_at: new Date(Date.now() - 2 * 3600_000).toISOString(),
        change_count: 3,
        headline: 'Keep tomorrow easy',
      } as ProposalSummary,
    ]
    exceptionsData = {
      ...exceptionsData,
      review_recommended: [rec],
      findings: [
        finding('f1', 'caution', 'Fatigue 8 on two days.'),
        finding('f2', 'observe', 'Easy run felt RPE 7.'),
      ],
      patches: [pa1],
    }
    mount()
    await screen.findByText('Fatigue 8 on two days.')
    const rows = screen.getAllByTestId('attention-row')
    expect(rows.map((row) => row.getAttribute('data-kind'))).toEqual([
      'proposal',
      'recommendation',
      'finding',
      'patch',
    ])
    expect(
      rows[3].compareDocumentPosition(screen.getAllByTestId('prompt-item')[0]) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    for (const text of ['Caution', 'Fatigue and recovery', 'Fatigue 8 on two days.'])
      expect(rows[2]).toHaveTextContent(text)
    expect(screen.getByTestId('needs-attention')).not.toHaveTextContent('Easy run felt RPE 7.')
    expect(rows[3]).toHaveTextContent('Reassess due · Nov 11–Nov 13')
  })
  it('copies the coach prompt', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    try {
      exceptionsData = { ...exceptionsData, review_recommended: [rec] }
      mount()
      await screen.findByText(rec.reason)
      const row = document.querySelector('[data-kind="recommendation"]') as HTMLElement
      fireEvent.click(within(row).getByRole('button', { name: 'Copy prompt' }))
      await waitFor(() => expect(writeText).toHaveBeenCalledWith(EXCEPTION_PROMPT))
    } finally {
      if (original) Object.defineProperty(navigator, 'clipboard', original)
      else Reflect.deleteProperty(navigator, 'clipboard')
    }
  })
  it('dismiss sends expected_version and refetches findings', async () => {
    exceptionsData.findings = [finding('f1', 'caution', 'Fatigue 8 on two days.', 3)]
    mount()
    await screen.findByText('Fatigue 8 on two days.')
    fireEvent.click(
      within(document.querySelector('[data-kind="finding"]') as HTMLElement).getByRole('button', {
        name: 'Dismiss',
      }),
    )
    await waitFor(() =>
      expect(
        requests.filter((r) => r.method === 'GET' && r.url === '/api/v1/exceptions'),
      ).toHaveLength(2),
    )
    const posts = requests.filter((r) => r.method === 'POST')
    expect(posts).toHaveLength(1)
    expect(posts[0].url).toBe('/api/v1/exceptions/f1/dismiss')
    expect(posts[0].body).toEqual({ expected_version: 3, note: null })
    expect(posts[0].headers.get('X-Local-Request')).toBe('1')
  })
  it('lists logged findings last in a closed disclosure', async () => {
    promptItems = []
    proposalItems = []
    exceptionsData = {
      ...exceptionsData,
      findings: [finding('f2', 'observe', 'Easy run felt RPE 7.')],
    }
    mount()
    const box = await screen.findByTestId('logged-findings')
    expect(box).not.toHaveAttribute('open')
    expect(box.querySelector('summary')).toHaveTextContent('Logged for Sunday review (1)')
    expect(box).toHaveTextContent('Easy run felt RPE 7.')
    expect(
      screen.getByTestId('block-line').compareDocumentPosition(box) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    expect(screen.queryByTestId('needs-attention')).toBeNull()
  })
  it('resolves or escalates a due patch', async () => {
    exceptionsData.patches = [pa1]
    mount()
    const resolved = await screen.findByRole('button', { name: 'Mark resolved' })
    fireEvent.click(resolved)
    await waitFor(() => expect(requests.filter((r) => r.method === 'POST')).toHaveLength(1))
    await waitFor(() => expect(resolved).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Still not right' }))
    await waitFor(() => expect(requests.filter((r) => r.method === 'POST')).toHaveLength(2))
    const posts = requests.filter((r) => r.method === 'POST')
    for (const [i, status] of ['resolved', 'escalated'].entries()) {
      expect(posts[i].url).toBe('/api/v1/exception-patches/pa1/resolve')
      expect(posts[i].body).toEqual({ expected_version: 1, status, note: null })
    }
  })
})

const interruptionWrites = () => requests.filter(({ method }) => method === 'PUT')

it('records a dated interruption from Today and shows affected and return runs with the stable draft link', async () => {
  const forecastRun = {
    session_uid: 'return-run',
    local_date: '2026-11-16',
    intent: 'Easy',
    recipe_id: 'REC001',
    planned_duration_s: 1800,
    planned_distance_m: null,
  }
  interruption.affected_runs = [
    { ...forecastRun, session_uid: 'affected-run', local_date: '2026-11-11' },
  ]
  interruption.first_run = forecastRun
  interruption.review_reason = 'Review the quality run before the first available easy day.'
  proposalItems = [
    {
      id: 'stable-draft',
      status: 'stale',
      operation: 'review_rolling_plan',
      change_count: 1,
    } as ProposalSummary,
  ]
  const writeText = vi.fn().mockResolvedValue(undefined)
  const originalClipboard = navigator.clipboard
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  try {
    mount()
    const today = within(await screen.findByTestId('today-card'))
    fireEvent.click(await today.findByRole('button', { name: 'Record a running interruption' }))
    const form = within(screen.getByRole('dialog', { name: 'Record a running interruption' }))
    fireEvent.change(form.getByLabelText('Reason'), { target: { value: 'travel' } })
    fireEvent.change(form.getByLabelText('First day available'), {
      target: { value: '2026-11-16' },
    })
    expect(interruptionWrites()).toHaveLength(0)
    fireEvent.click(form.getByRole('button', { name: 'Save interruption' }))
    const episode = within(await today.findByRole('region', { name: 'Running interruption' }))
    expect(episode.getByText('Paused')).toBeVisible()
    expect(episode.getByText('Accepted runs to leave behind or review')).toBeVisible()
    expect(episode.getByText(/Review the quality run/)).toBeVisible()
    expect(episode.getByText('Wed, Nov 11 · Easy run · 30m')).toBeVisible()
    expect(episode.getByRole('link', { name: 'Mon, Nov 16 · Easy run · 30m' })).toHaveAttribute(
      'href',
      '#calendar/2026-11-16',
    )
    expect(episode.getByRole('link', { name: 'Open current coach draft' })).toHaveAttribute(
      'href',
      '#proposal/stable-draft',
    )
    fireEvent.click(episode.getByText('Discuss with the coach'))
    fireEvent.click(episode.getByRole('button', { name: 'Copy prompt' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(INTERRUPTION_PROMPT))
    expect(interruptionWrites().map(({ body, url }) => ({ body, url }))).toEqual([
      {
        body: { expected_version: 3, interruption: currentEpisode },
        url: '/api/v1/running-interruption',
      },
    ])
    expect(today.getByTestId('session-tag')).toHaveTextContent('Planned')
  } finally {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: originalClipboard })
  }
})

it('shows the reassessment on an open-ended interruption and ends it only after confirmation', async () => {
  interruption = {
    ...emptyInterruption(),
    interruption: {
      ...currentEpisode,
      reason: 'illness',
      return_on: null,
      review_on: '2026-11-11',
    },
    phase: 'review_due',
    review_reason: 'First feasible run is uncertain while return availability is unconfirmed.',
  }
  mount()
  const episode = within(await screen.findByRole('region', { name: 'Running interruption' }))
  expect(episode.getByText('Review due')).toBeVisible()
  expect(episode.getByText(/Return date open/)).toBeVisible()
  expect(episode.getByText(/Reassess Wed, Nov 11/)).toBeVisible()
  expect(episode.getByText(/First feasible run is uncertain/)).toBeVisible()
  expect(episode.queryByText('First run to review')).toBeNull()
  fireEvent.click(episode.getByRole('button', { name: 'End interruption' }))
  const endDialog = () => within(screen.getByRole('dialog', { name: 'End running interruption' }))
  fireEvent.click(endDialog().getByRole('button', { name: 'Cancel' }))
  expect(interruptionWrites()).toHaveLength(0)
  fireEvent.click(episode.getByRole('button', { name: 'End interruption' }))
  fireEvent.click(endDialog().getByRole('button', { name: 'Confirm end' }))
  expect(await screen.findByRole('button', { name: 'Record a running interruption' })).toBeVisible()
  expect(interruptionWrites().map(({ body }) => body)).toEqual([
    { expected_version: 3, interruption: null },
  ])
  expect(screen.getByTestId('today-card')).toHaveTextContent('Easy run')
})

it('preserves the form through network failure and refreshes a version conflict before retrying', async () => {
  interruption = { ...emptyInterruption(), interruption: currentEpisode, phase: 'paused' }
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Edit interruption' }))
  const form = within(screen.getByRole('dialog', { name: 'Edit running interruption' }))
  fireEvent.change(form.getByLabelText('Return timing'), { target: { value: 'open' } })
  fireEvent.change(form.getByLabelText('Reassess on'), {
    target: { value: '2026-11-18' },
  })
  interruptionWriteError = 'network'
  const save = form.getByRole('button', { name: 'Save interruption' })
  fireEvent.click(save)
  expect(await form.findByText(/Cannot reach the local server/)).toBeVisible()
  expect(form.getByLabelText('Reassess on')).toHaveValue('2026-11-18')
  interruptionWriteError = 'conflict'
  interruption = {
    ...interruption,
    profile_version: 4,
    interruption: { ...currentEpisode, reason: 'schedule' },
  }
  fireEvent.click(save)
  expect(await form.findByText(/profile changed/)).toBeVisible()
  expect(save).toBeDisabled()
  fireEvent.click(form.getByRole('button', { name: 'Review latest before saving' }))
  expect(await form.findByText(/Currently saved: Schedule/)).toBeVisible()
  expect(form.getByLabelText('Return timing')).toHaveValue('open')
  expect(form.getByLabelText('Reassess on')).toHaveValue('2026-11-18')
  interruptionWriteError = null
  fireEvent.click(save)
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(interruptionWrites().map(({ body }) => body)).toEqual([
    {
      expected_version: 3,
      interruption: { ...currentEpisode, return_on: null, review_on: '2026-11-18' },
    },
    {
      expected_version: 3,
      interruption: { ...currentEpisode, return_on: null, review_on: '2026-11-18' },
    },
    {
      expected_version: 4,
      interruption: { ...currentEpisode, return_on: null, review_on: '2026-11-18' },
    },
  ])
})

it('holds an omitted locked run during the interruption while preserving other prescriptions', async () => {
  calendar.sessions[0] = {
    ...calendar.sessions[0],
    locked: true,
    structure: [{ type: 'work', duration_type: 'time', duration_value: 1200, target: null }],
  }
  calendar.sessions.push(
    session('rehab', '2026-11-11', {
      kind: 'rehab',
      slot: 2,
      intent: 'Calf raises',
      recipe_id: null,
    }),
  )
  interruption = {
    ...emptyInterruption(),
    interruption: currentEpisode,
    phase: 'paused',
    affected_runs_omitted: 3,
  }
  mount()
  const today = within(await screen.findByTestId('today-card'))
  const acceptedRun = within(today.getByText('Easy run').closest('article')!)
  expect(
    await acceptedRun.findByText('Unavailable during your interruption. Review this accepted run.'),
  ).toBeVisible()
  expect(acceptedRun.getByText('Planned')).toBeVisible()
  expect(acceptedRun.queryByText(/Work 20:00/)).toBeNull()
  expect(today.getByRole('link', { name: 'Review workout on Calendar' })).toBeVisible()
  expect(today.getByText('Calf raises')).toBeVisible()
})

it('links the observed first run back to feedback and keeps the interruption open', async () => {
  interruption = {
    ...emptyInterruption(),
    interruption: { ...currentEpisode, starts_on: '2026-11-06', return_on: '2026-11-10' },
    phase: 'returning',
    recorded_return: { activity_id: 'first-return', local_date: '2026-11-10' },
    review_reason: 'Review how the recorded run felt before ending the interruption.',
  }
  mount()
  const episode = within(await screen.findByRole('region', { name: 'Running interruption' }))
  expect(episode.getByText('First recorded run back')).toBeVisible()
  expect(episode.getByRole('link', { name: 'Review feedback for Tue, Nov 10' })).toHaveAttribute(
    'href',
    '#activity/first-return',
  )
  expect(episode.getByText(/Review how the recorded run felt/)).toBeVisible()
  expect(episode.queryByText('First run to review')).toBeNull()
  expect(episode.getByRole('button', { name: 'End interruption' })).toBeVisible()
  expect(interruptionWrites()).toHaveLength(0)
})
