import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DigestRow, WeeklyDigest as WeeklyDigestData } from '../src/api/types/calendar'
import { WeeklyDigest } from '../src/components/WeeklyDigest'
import { digest } from './fixtures/weekly-digest'

const { totals } = digest()
const outcomes = totals.sessions.by_outcome
const a1 = {
  session_uid: 's1',
  local_date: '2026-11-10',
  slot: 1,
  kind: 'run',
  class: 'quality',
  recipe_id: 'REC004',
  custom: false,
  intent: null,
  key: true,
  changed: false,
  outcome: 'partial',
  modification_reason: null,
  planned_duration_s: 3600,
  planned_distance_m: null,
  planned_distance_estimated: false,
  actual: {
    subject: 'activity',
    id: 'a1',
    local_date: '2026-11-10',
    duration_s: 2952,
    distance_m: 5000,
    sport: 'running',
    avg_hr_bpm: 152,
    moving_pace_s_per_km: 335,
    rpe: 6,
    rpe_source: 'manual',
  },
  execution: {
    assessment_status: 'partial',
    components: [
      { name: 'duration_ratio', value: 0.82, status: 'partially_met' },
      { name: 'target_coverage', value: null, status: 'not_assessable' },
    ],
    reps_planned: 6,
    reps_completed: 5,
    quality_flags: [],
    reason_codes: ['WORK_STEP_SKIPPED'],
  },
} satisfies DigestRow

function mount(data: WeeklyDigestData, onWeekChange = vi.fn()) {
  return render(<WeeklyDigest digest={data} unit="mi" week="this" onWeekChange={onWeekChange} />)
}

afterEach(cleanup)

describe('weekly digest', () => {
  it('shows progress so far for a week in progress', () => {
    mount(
      digest({
        totals: {
          ...totals,
          sessions: { ...totals.sessions, planned: 5, planned_to_date: 3, done: 2 },
          by_kind: { ...totals.by_kind, run: { planned: 3, planned_to_date: 2, done: 2 } },
        },
      }),
    )
    expect(
      screen.getByText('2 of 3 sessions done so far · 5 planned this week'),
    ).toBeInTheDocument()
    expect(screen.getByText('Runs 2/2')).toBeInTheDocument()
    expect(screen.queryByText(/Mobility/)).not.toBeInTheDocument()
  })

  it('shows only the final count for a finished week', () => {
    mount(
      digest({
        days_elapsed: 7,
        totals: {
          ...totals,
          sessions: { ...totals.sessions, planned: 5, planned_to_date: 5, done: 4 },
        },
      }),
    )
    expect(screen.getByText('4 of 5 sessions done')).toBeInTheDocument()
    expect(screen.queryByText(/so far/)).not.toBeInTheDocument()
  })

  it('lists non-zero outcomes only', () => {
    mount(
      digest({
        totals: {
          ...totals,
          sessions: { ...totals.sessions, by_outcome: { ...outcomes, missed: 1, partial: 2 } },
        },
      }),
    )
    expect(screen.getByText('2 partial · 1 missed')).toBeInTheDocument()
    expect(screen.queryByText(/modified/)).not.toBeInTheDocument()
  })

  it('shows unplanned and removed lines', () => {
    const data = digest({
      totals: {
        ...totals,
        sessions: { ...totals.sessions, unplanned: 2, removed: 1 },
        time: { ...totals.time, unplanned_s: 5400 },
      },
    })
    const view = mount(data)
    expect(screen.getByTestId('digest-unplanned')).toHaveTextContent(
      'Unplanned: 2 sessions · 1h 30m',
    )
    expect(screen.getByText('1 removed from the plan by an accepted change')).toBeInTheDocument()
    const unplanned = [
      {
        subject: 'activity' as const,
        id: 'a2',
        local_date: '2026-11-11',
        kind: 'run',
        duration_s: null,
        distance_m: 5000,
      },
    ]
    view.rerender(
      <WeeklyDigest digest={{ ...data, unplanned }} unit="mi" week="this" onWeekChange={vi.fn()} />,
    )
    expect(screen.getByTestId('digest-unplanned')).toHaveTextContent('duration unknown')
  })

  it('shows unknown amounts as unknown', () => {
    mount(
      digest({
        activity_coverage_complete: false,
        totals: { ...totals, time: { ...totals.time, planned_unknown: 1, actual_unknown: 2 } },
      }),
    )
    expect(
      screen.getByText(
        'Some amounts are unknown: 1 planned without a duration; 2 recorded without a duration; activity history may be incomplete',
      ),
    ).toBeInTheDocument()
  })

  it('shows unknown time and distance when amounts due today and recorded amounts are missing', () => {
    const row: DigestRow = {
      ...a1,
      local_date: '2026-11-11',
      planned_duration_s: null,
      planned_distance_m: null,
      actual: { ...a1.actual, local_date: '2026-11-11', duration_s: null, distance_m: null },
    }
    mount(
      digest({
        sessions: [row],
        totals: {
          ...totals,
          time: { ...totals.time, planned_unknown: 1, actual_unknown: 1 },
          run_distance: { ...totals.run_distance, planned_unknown: 1, actual_unknown: 1 },
        },
      }),
    )
    expect(screen.getByText('Time: unknown of unknown planned')).toBeInTheDocument()
    expect(screen.getByText('Running: unknown of unknown planned')).toBeInTheDocument()
  })

  it('keeps known totals when only future planned amounts are missing', () => {
    const row: DigestRow = {
      ...a1,
      local_date: '2026-11-12',
      planned_duration_s: null,
      planned_distance_m: null,
      outcome: 'planned',
      actual: null,
      execution: null,
    }
    mount(
      digest({
        sessions: [row],
        totals: {
          ...totals,
          time: { ...totals.time, planned_unknown: 1, actual_s: 1500, actual_unknown: 1 },
          run_distance: {
            ...totals.run_distance,
            planned_unknown: 1,
            actual_m: 5000,
            actual_unknown: 1,
          },
        },
      }),
    )
    expect(screen.getByText('Time: 25m of 0m planned')).toBeInTheDocument()
    expect(screen.getByText('Running: 3.1 mi of 0.0 mi planned')).toBeInTheDocument()
    expect(screen.getByText(/^Some amounts are unknown:/)).toBeInTheDocument()
  })

  it('prefixes planned distance with ~ when estimated', () => {
    mount(
      digest({
        totals: {
          ...totals,
          run_distance: { ...totals.run_distance, planned_to_date_m: 5000, planned_estimated: 1 },
        },
      }),
    )
    expect(screen.getByText(/^Running:/)).toHaveTextContent('of ~3.1 mi planned')
  })

  it('shows the no-plan state', () => {
    mount(digest({ plan_available: false }))
    expect(screen.getByText('No accepted plan for this week.')).toBeInTheDocument()
    expect(screen.queryByText(/^Time:/)).not.toBeInTheDocument()
  })

  it('toggle reports the chosen week', () => {
    const onWeekChange = vi.fn()
    mount(digest(), onWeekChange)
    const toggle = within(screen.getByRole('group', { name: 'Week' }))
    expect(toggle.getByRole('button', { name: 'This week' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    const last = toggle.getByRole('button', { name: 'Last week' })
    expect(last).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(last)
    expect(onWeekChange).toHaveBeenCalledWith('last')
  })

  it('renders a key session with components, reps, reasons, and a run link', () => {
    mount(digest({ sessions: [a1] }))
    const row = within(screen.getByTestId('digest-key-session'))
    expect(row.getByText(/Steady \/ tempo · Tue/)).toBeInTheDocument()
    expect(row.getByText('Partial')).toBeInTheDocument()
    expect(row.getByText('Duration vs plan 82% · Partly met')).toBeInTheDocument()
    expect(row.getByText('Time in target missing · Not assessable')).toBeInTheDocument()
    expect(row.getByText('Reps 5 of 6')).toBeInTheDocument()
    expect(row.getByText('A work rep was skipped')).toBeInTheDocument()
    expect(row.getByRole('link', { name: 'Open run' })).toHaveAttribute('href', '#activity/a1')
  })

  it('marks a key session with no assessment row', () => {
    const execution = {
      assessment_status: null,
      reason_codes: ['ASSESSMENT_MISSING'],
      quality_flags: [],
      components: [],
      reps_planned: null,
      reps_completed: null,
    }
    mount(digest({ sessions: [{ ...a1, execution }] }))
    const row = within(screen.getByTestId('digest-key-session'))
    expect(row.getByText('Not assessed yet')).toBeInTheDocument()
    expect(row.queryByRole('list')).not.toBeInTheDocument()
  })

  it('labels an assessment with insufficient plan detail', () => {
    const execution = { ...a1.execution, reason_codes: ['INSUFFICIENT_PLAN'] }
    mount(digest({ sessions: [{ ...a1, execution }] }))
    expect(screen.getByText('Not enough plan detail to compare')).toBeInTheDocument()
  })

  it('omits Open run for a manual or Strong subject', () => {
    mount(digest({ sessions: [{ ...a1, actual: { ...a1.actual, subject: 'strong_workout' } }] }))
    expect(screen.queryByRole('link', { name: 'Open run' })).not.toBeInTheDocument()
  })

  it('lists missed non-key sessions and hides mobility', () => {
    const missed: DigestRow = { ...a1, outcome: 'missed', actual: null, execution: null }
    const strength: DigestRow = {
      ...missed,
      session_uid: 's2',
      kind: 'strength',
      recipe_id: null,
      key: false,
    }
    const mobility: DigestRow = {
      ...strength,
      session_uid: 's3',
      kind: 'mobility',
      outcome: 'not_recorded',
    }
    mount(digest({ sessions: [missed, strength, mobility] }))
    const notDone = screen.getByTestId('digest-not-done')
    expect(notDone).toHaveTextContent(/Strength.*Missed/)
    expect(notDone).not.toHaveTextContent(/Mobility|Steady/)
    expect(screen.getByTestId('digest-key-session')).toHaveTextContent(/Steady.*Missed/)
  })
})

it('connects the accepted prescription, observed effort and delayed response to the plan review', () => {
  const decision: NonNullable<WeeklyDigestData['decision_follow_up']> = {
    proposal_id: 'p1',
    session_uid: 's1',
    op: 'modify',
    reason: 'See how the shorter session feels.',
    accepted: {
      local_date: '2026-11-10',
      intent: 'Easy run',
      duration_s: 1800,
      distance_m: null,
      effort: null,
    },
    edited_since: true,
    modification_reason: 'schedule',
    outcome: 'modified',
    actual: a1.actual,
    response: null,
    next_check: { on: '2026-11-15', check: 'Review effort and next-morning response.' },
  }
  const view = mount(digest({ decision_follow_up: decision }))
  const panel = within(screen.getByRole('region', { name: 'Follow-up on an accepted run' }))
  expect(panel.getByText(decision.reason)).toBeInTheDocument()
  expect(panel.getByText(/RPE 6\/10/)).toBeInTheDocument()
  expect(panel.getByText(/No delayed response recorded/)).toBeInTheDocument()
  expect(panel.getByText(/calendar was edited/)).toBeInTheDocument()
  expect(panel.getByRole('link', { name: 'View accepted decision' })).toHaveAttribute(
    'href',
    '#proposal/p1',
  )
  expect(panel.getByRole('link', { name: 'View workout feedback' })).toHaveAttribute(
    'href',
    '#activity/a1',
  )
  const response = {
    observed_at: '2026-11-11T11:00:00Z',
    hours_after_end: 24,
    pain_reported: false,
    gait_change: null,
    symptoms: [],
  }
  view.rerender(
    <WeeklyDigest
      digest={digest({ decision_follow_up: { ...decision, response } })}
      unit="mi"
      week="this"
      onWeekChange={vi.fn()}
    />,
  )
  expect(panel.getByText('No pain reported · 24 h after the run')).toBeInTheDocument()
  expect(panel.getByText(/Review effort and next-morning response/)).toBeInTheDocument()
})
