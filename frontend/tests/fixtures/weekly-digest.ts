import type { DigestCounts, DigestOutcome, WeeklyDigest } from '../../src/api/types/calendar'

const counts: DigestCounts = { planned: 0, planned_to_date: 0, done: 0 }
const outcomes: Record<DigestOutcome, number> = {
  planned: 0,
  completed: 0,
  modified: 0,
  partial: 0,
  moved: 0,
  missed: 0,
  recorded: 0,
  not_recorded: 0,
}
const totals: WeeklyDigest['totals'] = {
  sessions: { ...counts, by_outcome: outcomes, removed: 0, unplanned: 0 },
  by_kind: { run: counts, strength: counts, cross: counts, mobility: counts, rehab: counts },
  time: {
    planned_s: 0,
    planned_to_date_s: 0,
    planned_unknown: 0,
    actual_s: 0,
    actual_unknown: 0,
    unplanned_s: 0,
  },
  run_distance: {
    planned_m: 0,
    planned_to_date_m: 0,
    planned_estimated: 0,
    planned_unknown: 0,
    actual_m: 0,
    actual_unknown: 0,
  },
  key_sessions: { ...counts, by_outcome: outcomes },
}

export function digest(overrides: Partial<WeeklyDigest> = {}): WeeklyDigest {
  return {
    schema: 'weekly_digest.v1',
    decision_follow_up: null,
    week_start: '2026-11-09',
    week_end: '2026-11-15',
    today: '2026-11-11',
    days_elapsed: 3,
    timezone: 'America/New_York',
    calendar_version: 1,
    plan_available: true,
    activity_coverage_complete: true,
    totals,
    sessions: [],
    unplanned: [],
    removed: [],
    ...overrides,
  }
}
