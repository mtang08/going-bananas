import type { BenchmarkOutcome, Category, Ladder, Severity } from './api/types/exceptions'
import type { ProposalStatus } from './api/types/coach'

export const CATEGORY_LABELS: Record<Category, string> = {
  symptoms_illness: 'Symptoms or illness',
  training_response: 'Training response',
  accumulated_fatigue: 'Fatigue and recovery',
  calendar_disruption: 'Schedule',
  post_event: 'Race review',
}
export const SEVERITY_LABELS: Record<Severity, string> = {
  observe: 'Logged',
  caution: 'Caution',
  hold: 'Hold',
  escalate: 'Needs bigger review',
}
export const OPERATION_LABELS: Record<string, string> = {
  review_rolling_plan: 'Weekly review',
  exception_review: 'Exception review',
  review_training_block: 'Block review',
  post_event_review: 'Race review',
  recalibrate_intensity: 'Pace recalibration',
  select_quality_session: 'Quality session',
  handle_goal_or_race_change: 'Goal or race change',
  proceed_or_modify_today: 'Today adjustment',
}
export const LADDER_LABELS: Record<Ladder, string> = {
  current_session: "Today's session only",
  next_session: 'Next session only',
  next_days: 'Next few days',
  committed_window: 'This committed week',
  block: 'Block-level review',
}
// The chip uses `status` only (contracts §9.2); do not derive staleness from anything else.
export const PROPOSAL_CHIP_LABELS: Partial<Record<ProposalStatus, string>> = {
  pending: 'Pending',
  stale: 'Stale — ask the coach to refresh',
  invalid: 'Invalid — ask the coach to fix',
}
export const operationLabel = (op: string): string =>
  OPERATION_LABELS[op] ?? op.replaceAll('_', ' ')

export const OUTCOME_LABELS: Record<BenchmarkOutcome, string> = {
  progress: 'Progress',
  consolidate: 'Consolidate',
  recalibrate_only: 'Recalibrate paces only',
  inconclusive: 'Inconclusive',
}
export const RECALIBRATION_LABELS: Record<'none' | 'propose_anchors' | 'defer', string> = {
  none: 'No pace change',
  propose_anchors: 'New paces proposed',
  defer: 'Recalibrate later',
}
