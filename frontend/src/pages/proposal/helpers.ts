import { dateLabel } from '../../lib/format'
import { flattenStructure } from '../../lib/structure'
import { RECIPE_LABELS } from '../../api/types/calendar'
import type { ProposalSession, ProposalChange } from '../../api/types/coach'

export function readStructure(value: ProposalSession | null) {
  if (!value?.structure || value.legacy_unstructured) return { steps: [], invalid: false }
  try {
    return { steps: flattenStructure(value.structure), invalid: false }
  } catch {
    return { steps: [], invalid: true }
  }
}

export const ACTION_LABELS = { add: 'Add', modify: 'Update', move: 'Move', delete: 'Remove' }
export function proposedSession(change: ProposalChange): ProposalSession | null {
  return change.op === 'delete' ? null : { ...change.before, ...change.after }
}
export function sessionName(value: ProposalSession | null): string {
  if (!value) return 'Session'
  if (value.recipe_id && RECIPE_LABELS[value.recipe_id]) return RECIPE_LABELS[value.recipe_id]
  return {
    run: 'Run',
    strength: 'Strength',
    cross: 'Cross-training',
    rest: 'Rest',
    mobility: 'Mobility',
  }[value.kind ?? 'run']
}
export function sessionDate(value: ProposalSession | null): string {
  return value?.local_date
    ? dateLabel(value.local_date, { weekday: 'short', month: 'short', day: 'numeric' })
    : 'Date not specified'
}
