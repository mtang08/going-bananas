import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { mondayOfWeek, SessionSummary } from '../src/components/PlanOverview'
import type { SessionState } from '../src/api'

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
  is_original: true,
  changed_by_version: 2,
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

  it('labels benchmark sessions', () => {
    renderSession({ recipe_id: 'REC009' })
    expect(screen.getByText('Benchmark').closest('.plan-session-status')).not.toBeNull()
    cleanup()
    renderSession({ recipe_id: 'REC001' })
    expect(screen.queryByText('Benchmark')).toBeNull()
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
