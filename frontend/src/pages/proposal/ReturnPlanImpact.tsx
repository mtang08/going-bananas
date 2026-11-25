import type { ProposalChange, ProposalInterruption } from '../../api/types/coach'
import { Card } from '../../components/ui'
import { dateLabel } from '../../lib/format'
import { proposedSession, sessionName } from './helpers'

function selectionEffect(change: ProposalChange | undefined, day: string) {
  if (!change) return 'Stays on the calendar'
  const after = proposedSession(change)
  if (!after) return 'Removed from the plan'
  if (after.kind && after.kind !== 'run') return `Replaced with ${sessionName(after).toLowerCase()}`
  if (after.local_date && after.local_date !== day) return `Moved to ${dateLabel(after.local_date)}`
  return 'Still scheduled on this date'
}

export function ReturnPlanImpact({
  evidence,
  changes,
  selected,
}: {
  evidence: ProposalInterruption
  changes: ProposalChange[]
  selected: string[]
}) {
  const { interruption, affected_runs, affected_runs_omitted, today } = evidence
  const upcoming = affected_runs.filter((run) => run.local_date >= today)
  const checked = new Map(
    changes
      .filter((change) => selected.includes(change.change_id))
      .map((change) => [change.session_uid, change]),
  )
  return (
    <Card role="region" aria-label="Running break in this proposal" className="space-y-2">
      <h2>Running break in this proposal</h2>
      <p>
        Unavailable from {dateLabel(interruption.starts_on)}.{' '}
        {interruption.return_on
          ? `Earliest available day is ${dateLabel(interruption.return_on)}.`
          : `Reassess on ${dateLabel(interruption.review_on!)} before setting a return date.`}
      </p>
      {upcoming.length > 0 && (
        <>
          <p>How the checked changes affect runs during your break</p>
          <ul className="space-y-1">
            {upcoming.map((run) => (
              <li key={run.session_uid}>
                {dateLabel(run.local_date)} ·{' '}
                {sessionName({ kind: 'run', recipe_id: run.recipe_id, custom: !run.recipe_id })} ·{' '}
                {selectionEffect(checked.get(run.session_uid), run.local_date)}
              </li>
            ))}
          </ul>
        </>
      )}
      {affected_runs_omitted > 0 && (
        <p>
          {affected_runs_omitted} additional affected{' '}
          {affected_runs_omitted === 1 ? 'session was' : 'sessions were'} outside the saved preview.
        </p>
      )}
    </Card>
  )
}
