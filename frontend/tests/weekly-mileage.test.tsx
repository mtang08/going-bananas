import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { WeeklyMileage } from '../src/components/WeeklyMileage'
import type { WeeklyProjection } from '../src/api/types/calendar'

const base: WeeklyProjection = {
  week_start: '2026-11-09', week_end: '2026-11-15', today: '2026-11-11', timezone: 'America/New_York', calendar_version: 2,
  actual_distance_m: 8046.72, remaining_distance_m: 16093.44, projected_distance_m: 24140.16,
  actual_runs: 1, remaining_runs: 2, estimated_runs: 0, missing_actual_runs: 0, missing_planned_runs: 0,
  unrecorded_past_runs: 0, pace_sample_count: 4, pace_mps: 3, plan_available: true,
  plan_through: '2026-11-15', activity_coverage_complete: true,
}

describe('weekly mileage', () => {
  it('shows the athlete week, recorded and remaining accepted mileage', () => {
    render(<WeeklyMileage projection={base} unit="mi" />)
    expect(screen.getByText(/Nov 9–Nov 15 · Monday–Sunday/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Recorded 5.0 mi; remaining accepted plan 10.0 mi' })).toBeInTheDocument()
    expect(screen.getByText('15.0 mi')).toBeInTheDocument()
    expect(screen.getByText('Recorded: 5.0 mi · 1 run')).toBeInTheDocument()
    expect(screen.getByText('Remaining accepted plan: 10.0 mi · 2 runs')).toBeInTheDocument()
  })
  it('marks estimated and incomplete distance clearly', () => {
    render(<WeeklyMileage projection={{ ...base, estimated_runs: 1, missing_actual_runs: 1, plan_through: '2026-11-13' }} unit="km" />)
    expect(screen.getByText('~24.1 km')).toBeInTheDocument()
    expect(screen.getByText(/Incomplete projection · accounted distance/)).toBeInTheDocument()
    expect(screen.getByText(/Time-based runs estimated/)).toBeInTheDocument()
    expect(screen.getByText(/recorded run has no distance/)).toBeInTheDocument()
    expect(screen.getByText(/accepted plan does not cover the full week/)).toBeInTheDocument()
  })
  it('explains when no accepted plan is available', () => {
    render(<WeeklyMileage projection={{ ...base, plan_available: false, plan_through: null, remaining_runs: 0, remaining_distance_m: 0, projected_distance_m: base.actual_distance_m }} unit="mi" />)
    expect(screen.getByText(/no accepted plan is available/)).toBeInTheDocument()
  })
})
