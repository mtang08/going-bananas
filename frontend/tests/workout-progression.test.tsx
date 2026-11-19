import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import { WorkoutProgressionChart, WorkoutProgressionTable } from '../src/components/WorkoutProgression'
import type { ProgressionPoint } from '../src/api'

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  LineChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Line: () => null, Tooltip: () => null, CartesianGrid: () => null, XAxis: () => null, YAxis: () => null,
}))
afterEach(cleanup)

function point(overrides: Partial<ProgressionPoint> = {}): ProgressionPoint {
  return { session_uid: 's1', activity_id: 'a1', local_date: '2026-10-20', planned_date: '2026-10-20',
    recipe_id: 'REC003', intent: 'Threshold', signature: 'ws1:4xt300', recovery_s: 360,
    target_modalities: ['speed'], sport: 'running', completion_status: 'completed_as_planned',
    status: 'available', reason_codes: [], quality_flags: [], n_planned: 4, n_completed: 4,
    step_completion_ratio: 1, reps_used: 4, reps_used_hr: 4, work_speed_mps: 3.55, work_hr_bpm: 161,
    work_m_per_beat: 1.323, cv_speed: 2.817, last_first_change_pct: -1.2, target_coverage: 0.75,
    interval_result_id: 'r1', ...overrides }
}

it('renders newest sessions, statuses, missing values and the current run', () => {
  const points = [point(), point({ session_uid: 's2', activity_id: 'a2', local_date: '2026-10-27',
    status: 'partial', n_completed: 3, reason_codes: ['INCOMPLETE_WORK_STEPS'] }),
  point({ session_uid: 's3', activity_id: 'a3', local_date: '2026-11-03', status: 'not_assessable',
    reason_codes: ['WATCH_WORKOUT_MISMATCH'], n_completed: null, work_hr_bpm: null, work_speed_mps: null,
    work_m_per_beat: null, cv_speed: null, last_first_change_pct: null, target_coverage: null }),
  point({ session_uid: 's4', activity_id: null, local_date: '2026-11-10', status: 'missing',
    reason_codes: ['NO_LINKED_ACTIVITY'], completion_status: 'skipped' })]
  render(<WorkoutProgressionTable points={points} unit="mi" showSignature currentActivityId="a1" />)
  const rows = screen.getAllByTestId('progression-row')
  expect(rows).toHaveLength(4)
  expect(rows[0]).toHaveTextContent('Nov 10')
  expect(screen.getByText('Skipped')).toBeInTheDocument()
  expect(screen.getByText('Not assessable: Watch workout does not match the plan')).toBeInTheDocument()
  expect(screen.getByText('Partial: Some reps were shorter than planned')).toBeInTheDocument()
  expect(within(rows[1]).getAllByText('missing').length).toBeGreaterThan(0)
  expect(within(rows[1]).getAllByRole('cell')[4]).toHaveTextContent('missing')
  expect(within(rows[2]).getByText('3/4')).toBeInTheDocument()
  for (const text of ['161 bpm', '1.32', '2.8%', '-1.2%', '75%']) expect(within(rows[3]).getByText(text)).toBeInTheDocument()
  expect(rows[3]).toHaveAttribute('aria-current', 'true')
  expect(rows[3]).toHaveTextContent('(this run)')
  expect(screen.getByRole('columnheader', { name: 'Work steps' })).toBeInTheDocument()
  expect(within(rows[3]).getByText('4 × 5:00')).toBeInTheDocument()
})

it('shows a chart only with two assessed sessions', () => {
  const { rerender } = render(<WorkoutProgressionChart points={[point()]} unit="mi" />)
  expect(screen.getByText('Two or more assessed sessions are needed for a chart.')).toBeInTheDocument()
  rerender(<WorkoutProgressionChart points={[point(), point({ session_uid: 's2' })]} unit="mi" />)
  expect(screen.getByRole('img', { name: 'Work pace and heart rate by session' })).toBeInTheDocument()
})
