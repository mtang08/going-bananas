import { RECIPE_LABELS } from '../api/types/calendar'
import type { Completion, SessionKind, SessionMarker, SessionState } from '../api/types/calendar'

export function sessionTitle(s: {
  kind: SessionKind
  recipe_id: string | null
  custom: boolean
}): string {
  if (s.kind === 'run')
    return s.recipe_id
      ? (RECIPE_LABELS[s.recipe_id] ?? s.recipe_id)
      : s.custom
        ? 'Custom run'
        : 'Quality slot'
  if (s.kind === 'strength') return 'Strength'
  if (s.kind === 'cross') return 'Cross-training'
  if (s.kind === 'mobility') return 'Mobility'
  if (s.kind === 'rehab') return 'Rehab'
  return 'Rest'
}
export function sessionMarker(
  s: SessionState,
  c: Completion | undefined,
  today: string,
): SessionMarker {
  if (c?.status === 'completed_as_planned') return 'completed'
  if (c?.status === 'completed_modified') return 'modified'
  if (c?.status === 'partial') return 'partial'
  if (c?.status === 'moved') return 'moved'
  if (c?.status === 'skipped') return 'missed'
  if (c?.activity_id || c?.strong_workout_id || c?.manual_session_id) return 'recorded'
  return s.local_date < today ? 'not_recorded' : 'planned'
}
