import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { DigestRow } from '../src/api/types/calendar'
import { WeekSessions } from '../src/components/WeekSessions'
import { pace, sportLabel } from '../src/lib/format'
import { digest } from './fixtures/weekly-digest'

const run = {
  session_uid: 's1',
  local_date: '2026-11-10',
  slot: 0,
  kind: 'run',
  class: 'quality',
  recipe_id: 'REC004',
  custom: false,
  intent: null,
  key: true,
  changed: false,
  outcome: 'completed',
  modification_reason: null,
  planned_duration_s: 3600,
  planned_distance_m: 5000,
  planned_distance_estimated: true,
  actual: {
    subject: 'activity',
    id: 'a1',
    local_date: '2026-11-10',
    duration_s: 2952,
    distance_m: 5000,
    sport: 'treadmill_running',
    avg_hr_bpm: 152.4,
    moving_pace_s_per_km: 335,
    rpe: 6,
    rpe_source: 'manual',
  },
  execution: {
    assessment_status: 'partial',
    components: [{ name: 'duration_ratio', value: 0.82, status: 'partially_met' }],
    reps_planned: 6,
    reps_completed: 5,
    quality_flags: [],
    reason_codes: ['WORK_STEP_SKIPPED'],
  },
} satisfies DigestRow

afterEach(cleanup)

describe('week sessions', () => {
  it('renders a done run with pace, HR, RPE, and sport', () => {
    render(<WeekSessions digest={digest({ sessions: [run] })} unit="mi" week="this" />)
    const row = screen.getByTestId('week-session')
    expect(row).toHaveTextContent('Planned: 1h 00m · ~3.1 mi')
    expect(row).toHaveTextContent('Done: 49m · 3.1 mi')
    expect(row).toHaveTextContent(pace(335, 'mi'))
    expect(row).toHaveTextContent('152 bpm · RPE 6')
    expect(row).toHaveTextContent(sportLabel('treadmill_running'))
    expect(within(row).getByRole('link', { name: 'Open run' })).toHaveAttribute(
      'href',
      '#activity/a1',
    )
  })

  it('shows unknown values as a dash, never zero', () => {
    const actual = {
      ...run.actual,
      duration_s: null,
      distance_m: null,
      sport: null,
      avg_hr_bpm: null,
      moving_pace_s_per_km: null,
      rpe: null,
      rpe_source: null,
    }
    render(
      <WeekSessions digest={digest({ sessions: [{ ...run, actual }] })} unit="mi" week="this" />,
    )
    expect(screen.getByTestId('week-session')).toHaveTextContent('Done: — · — · — · — · RPE — · —')
  })

  it('shows execution chips and reps only for runs', () => {
    const strength: DigestRow = {
      ...run,
      session_uid: 's2',
      kind: 'strength',
      execution: {
        assessment_status: null,
        components: [],
        reps_planned: null,
        reps_completed: null,
        quality_flags: [],
        reason_codes: ['ASSESSMENT_MISSING'],
      },
    }
    render(<WeekSessions digest={digest({ sessions: [run, strength] })} unit="mi" week="this" />)
    const [runRow, strengthRow] = screen.getAllByTestId('week-session')
    expect(runRow).toHaveTextContent('Reps 5 of 6')
    expect(runRow).toHaveTextContent('82%')
    expect(strengthRow).toHaveTextContent('Done: 49m · 152 bpm · RPE 6')
    expect(strengthRow).not.toHaveTextContent(pace(335, 'mi'))
    expect(strengthRow).not.toHaveTextContent('Not assessed yet')
  })

  it('lists unplanned activities in date order with planned sessions', () => {
    const mobility: DigestRow = {
      ...run,
      session_uid: 's2',
      kind: 'mobility',
      local_date: '2026-11-12',
      outcome: 'planned',
      actual: null,
      execution: null,
    }
    render(
      <WeekSessions
        digest={digest({
          sessions: [mobility, run],
          unplanned: [
            {
              subject: 'activity',
              id: 'a2',
              local_date: '2026-11-11',
              kind: 'run',
              duration_s: null,
              distance_m: 5000,
            },
          ],
        })}
        unit="mi"
        week="this"
      />,
    )
    const rows = screen.getAllByTestId('week-session')
    expect(rows.map((row) => row.dataset.date)).toEqual(['2026-11-10', '2026-11-11', '2026-11-12'])
    expect(rows[1]).toHaveTextContent('Unplanned run')
    expect(rows[2]).toHaveTextContent('Mobility')
  })

  it('labels the card for last week', () => {
    render(<WeekSessions digest={digest()} unit="mi" week="last" />)
    expect(screen.getByRole('heading', { name: "Last week's sessions" })).toBeInTheDocument()
    expect(screen.getByText('No sessions this week.')).toBeInTheDocument()
  })
})
