export const REASON_LABELS: Record<string, string> = {
  LAP_STEP_ORDER_MISMATCH: 'Laps do not follow the watch workout',
  LAP_STEP_UNKNOWN: 'A lap refers to an unknown workout step',
  LAP_ALIGNMENT_AMBIGUOUS: 'Laps can match the workout in more than one way',
  NO_INDEXED_LAPS: 'Laps are not linked to workout steps',
  WATCH_WORKOUT_MISMATCH: 'Watch workout does not match the plan',
  NO_WATCH_WORKOUT: 'No watch workout recorded',
  NO_STRUCTURED_PLAN: 'Plan has no structured steps',
  WORK_STEP_SKIPPED: 'A work rep was skipped',
  WORK_STEP_NOT_RECORDED: 'A work rep was not recorded',
  WORKOUT_ENDED_EARLY: 'Workout ended before the last rep',
  WATCH_PLAN_DURATION_DIFFERS: 'Watch rep length differs from the plan',
  INCOMPLETE_WORK_STEP: 'Some reps were shorter than planned',
  INCOMPLETE_WORK_STEPS: 'Some reps were shorter than planned',
  COMPONENT_NOT_ASSESSABLE: 'Part of the comparison is unavailable',
  WORK_MEASUREMENT_MISSING: 'Some rep measurements are missing',
  LOW_COVERAGE: 'Limited pace data',
  LAP_SPLIT_MERGED: 'Split laps combined',
  NONWORK_STEP_OMITTED: 'A warm-up, recovery, or cool-down step was not recorded',
  LEADING_LAPS_IGNORED: 'Laps outside the workout ignored',
  TRAILING_LAPS_IGNORED: 'Laps outside the workout ignored',
  UNINDEXED_LAP_IGNORED: 'Laps outside the workout ignored',
  COMPLETED_WITHIN_TOLERANCE: 'Counted complete within measurement tolerance',
  LAP_INTENSITY_DISAGREES: 'Lap type differs from the workout step',
}

export function reasonText(code: string): string {
  return REASON_LABELS[code] ?? code
}
