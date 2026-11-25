import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { mondayOfWeek, SessionSummary } from '../src/components/PlanOverview'
import type { SessionBrief, SessionState } from '../src/api/types/calendar'

const base = {
  id: 's1-rev',
  session_uid: 's1',
  revision: 1,
  calendar_version_number: 2,
  deleted: false,
  local_date: '2026-11-19',
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
  brief: null,
  is_original: true,
  changed_by_version: 2,
  exception_patch: null,
} satisfies SessionState

afterEach(() => cleanup())
describe('athlete calendar week', () => {
  it('keeps Sunday in the week ending today', () => {
    expect(mondayOfWeek('2026-11-15')).toBe('2026-11-09')
  })
  it('starts a new week on Monday independent of browser time', () => {
    expect(mondayOfWeek('2026-11-16')).toBe('2026-11-16')
  })
})

describe('session status badges', () => {
  const renderSession = (overrides: Partial<SessionState> = {}) =>
    render(<SessionSummary session={{ ...base, ...overrides }} today="2026-11-11" unit="mi" />)

  it('shows the open patch badge in the status row', () => {
    renderSession({
      exception_patch: {
        patch_id: 'pa1',
        proposal_id: 'p9',
        reassess_on: '2026-11-19',
        status: 'open',
      },
    })
    const badge = screen.getByTestId('patch-badge')
    expect(badge).toHaveTextContent('Patched · reassess Thursday')
    expect(badge.closest('.plan-session-status')).not.toBeNull()
  })

  it('hides the badge for closed patches and missing data', () => {
    renderSession({
      exception_patch: {
        patch_id: 'pa1',
        proposal_id: 'p9',
        reassess_on: '2026-11-19',
        status: 'resolved',
      },
    })
    expect(screen.queryByTestId('patch-badge')).toBeNull()
    cleanup()
    renderSession()
    expect(screen.queryByTestId('patch-badge')).toBeNull()
  })

  it('names the rehab routine before opening its details', () => {
    renderSession({ kind: 'rehab', recipe_id: null, intent: 'Calf routine' })
    expect(screen.getByTestId('session-tag').querySelector('strong')).toHaveTextContent(
      'Calf routine',
    )
    expect(screen.getByText('Rehab')).toBeVisible()
  })

  it('labels benchmark sessions', () => {
    renderSession({ recipe_id: 'REC009' })
    expect(screen.getByText('Benchmark').closest('.plan-session-status')).not.toBeNull()
    cleanup()
    renderSession({ recipe_id: 'REC001' })
    expect(screen.queryByText('Benchmark')).toBeNull()
  })
})

describe('session notes', () => {
  const notes = 'Stop if form deteriorates'

  it('shows notes as plain text inside Session details', () => {
    render(<SessionSummary session={{ ...base, notes }} today="2026-11-11" unit="mi" />)
    fireEvent.click(screen.getByText('Session details'))
    const paragraph = screen.getByText(notes)
    expect(paragraph).toBeVisible()
    expect(paragraph.closest('details')).toHaveClass('plan-session-details')
    expect(screen.queryByText('Session notes')).not.toBeInTheDocument()
  })

  it('keeps notes in a closed Why and notes disclosure on the Today card', () => {
    render(<SessionSummary session={{ ...base, notes }} today="2026-11-11" unit="mi" showWorkout />)
    const paragraph = screen.getByText(notes)
    expect(paragraph).not.toBeVisible()
    fireEvent.click(screen.getByText('Why and notes'))
    expect(paragraph).toBeVisible()
  })
  it('shows imported notes the same way', () => {
    render(
      <SessionSummary
        session={{ ...base, legacy_unstructured: true, notes: 'Old easy prescription' }}
        today="2026-11-11"
        unit="mi"
        showWorkout
      />,
    )
    fireEvent.click(screen.getByText('Why and notes'))
    expect(screen.getByText('Old easy prescription')).toBeVisible()
  })

  it('omits blank notes', () => {
    const { container } = render(
      <SessionSummary session={{ ...base, notes: '   ' }} today="2026-11-11" unit="mi" />,
    )
    expect(container.querySelector('.plan-session-notes')).toBeNull()
  })
})

it('distinguishes a recorded run with unknown comparison from an unrecorded plan', () => {
  const completion = {
    id: 'c1',
    session_uid: base.session_uid,
    activity_id: 'a1',
    strong_workout_id: null,
    manual_session_id: null,
    status: 'unknown' as const,
    match_method: 'auto_same_day' as const,
    modification_reason: null,
    reason_note: null,
    version: 1,
    input_version: 1,
    updated_at: '2026-11-19T12:00:00Z',
    local_date: base.local_date,
  }
  render(<SessionSummary session={base} completion={completion} today="2026-11-20" unit="mi" />)
  expect(screen.getByText('Recorded · comparison unavailable')).toBeInTheDocument()
  expect(screen.queryByText('Not recorded')).toBeNull()
  expect(screen.queryByText('Completed')).toBeNull()
  cleanup()
  render(
    <SessionSummary
      session={base}
      completion={{ ...completion, activity_id: null }}
      today="2026-11-20"
      unit="mi"
    />,
  )
  expect(screen.getByText('Not recorded')).toBeInTheDocument()
})

describe('session brief', () => {
  const brief: SessionBrief = {
    effort: { rpe_low: 6, rpe_high: 7, feel: 'controlled' },
    focus: ['Even splits; last rep no faster than first'],
    adjust_if: [{ when: 'Rep pace fades more than 5%', then: 'stop after rep 4' }],
    why: 'Last two threshold sessions hit pace at RPE 7',
  }
  const coached = {
    ...base,
    intent: 'Threshold control',
    brief,
    notes: 'Felt flat after travel',
    structure: [
      { type: 'work' as const, duration_type: 'time' as const, duration_value: 600, target: null },
    ],
  }

  it('opens focus, why and notes on demand', () => {
    render(<SessionSummary session={coached} showWorkout today="2026-11-11" unit="mi" />)
    expect(screen.getByText('RPE 6–7')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Adjust if' })).toBeVisible()
    expect(screen.getByText(brief.why)).not.toBeVisible()
    fireEvent.click(screen.getByText('Why and notes'))
    expect(screen.getByText(brief.why)).toBeVisible()
    expect(screen.getByText(brief.focus[0])).toBeVisible()
    expect(screen.getByText(coached.notes)).toBeVisible()
  })
  it('orders purpose, effort, workout, then adjust-if', () => {
    const { container } = render(
      <SessionSummary session={coached} showWorkout today="2026-11-11" unit="mi" />,
    )
    const purpose = screen.getByText('Threshold control')
    const effort = screen.getByText('RPE 6–7')
    const workout = container.querySelector('.compact-workout')!
    const adjustIf = screen.getByRole('heading', { name: 'Adjust if' })
    for (const [first, second] of [
      [purpose, effort],
      [effort, workout],
      [workout, adjustIf],
    ]) {
      expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }
    expect(screen.getByText('controlled')).toBeVisible()
    expect(screen.getByText('Rep pace fades more than 5%').closest('li')).toHaveTextContent(
      'Rep pace fades more than 5% → stop after rep 4',
    )
  })

  it('renders no brief controls without a brief or notes', () => {
    render(<SessionSummary session={base} showWorkout today="2026-11-11" unit="mi" />)
    expect(screen.queryByText('Why and notes')).not.toBeInTheDocument()
    expect(screen.queryByText('Adjust if')).not.toBeInTheDocument()
  })

  it('shows the entire brief when session details are opened', () => {
    render(<SessionSummary session={coached} today="2026-11-11" unit="mi" />)
    fireEvent.click(screen.getByText('Session details'))
    expect(screen.getByText(brief.why)).toBeVisible()
    expect(screen.getByText(brief.focus[0])).toBeVisible()
    expect(screen.queryByText('Why and notes')).toBeNull()
  })
})
