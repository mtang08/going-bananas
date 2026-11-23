import { CoachText, EffortLabel } from '../../components/CoachText'
import { SessionBrief } from '../../components/SessionBrief'
import { Fragment } from 'react'
import { mondayOfWeek } from '../../components/PlanOverview'
import { addDays, dateLabel } from '../../lib/format'
import type { ProposalChange } from '../../api/types/coach'
import {
  Badge,
  Button,
  Card,
  Disclosure,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui'
import { ACTION_LABELS, proposedSession, sessionName, sessionDate } from './helpers'
import { SessionView } from './ProposalParts'

export function ProposedChanges({
  changes,
  today,
  revision,
  firstRevisionChangeIds,
  terminal,
  isDiscarded,
  isStale,
  disabled,
  selected,
  invalidChangeIds,
  acceptedChangeIds,
  onSelect,
  onToggle,
}: {
  changes: ProposalChange[]
  today: string | null
  revision: number
  firstRevisionChangeIds: string[]
  terminal: boolean
  isDiscarded: boolean
  isStale: boolean
  disabled: boolean
  selected: string[]
  invalidChangeIds: Set<string>
  acceptedChangeIds: string[] | null
  onSelect: (ids: string[]) => void
  onToggle: (id: string) => void
}) {
  const weeks = changes.map((change) => {
    const date = (proposedSession(change) ?? change.before)?.local_date
    return date ? mondayOfWeek(date) : null
  })
  const committedThrough = today ? addDays(today, 6) : null
  const weekStatus = new Map<string, Set<string>>()
  changes.forEach((change, index) => {
    const week = weeks[index]
    const date = (proposedSession(change) ?? change.before)?.local_date
    if (!week || !date || !committedThrough) return
    const statuses = weekStatus.get(week) ?? new Set<string>()
    statuses.add(date <= committedThrough ? 'Committed' : 'Provisional')
    weekStatus.set(week, statuses)
  })
  const weekHeading = (week: string) => {
    const label = `Week of ${dateLabel(week)}`
    const statuses = weekStatus.get(week)
    if (!statuses) return label
    const status = statuses.size === 2 ? 'Committed and provisional' : [...statuses][0]
    return `${label} · ${status}`
  }
  return (
    <Card className="proposal-plan">
      <h2>Proposed plan changes</h2>
      <p>
        {terminal
          ? 'These are the changes saved with this proposal.'
          : 'Review the sessions below. Only changed sessions are shown; unchecked changes will be rejected.'}
      </p>
      {!terminal && (
        <div className="proposal-select-controls">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            onClick={() =>
              onSelect(
                changes.filter((c) => !invalidChangeIds.has(c.change_id)).map((c) => c.change_id),
              )
            }
          >
            Select all
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={disabled || selected.length === 0}
            onClick={() => onSelect([])}
          >
            Clear
          </Button>
        </div>
      )}
      <div className="table-scroll" role="region" aria-label="Proposed plan changes" tabIndex={0}>
        <Table
          className="proposal-table [&_td]:align-top [&_td]:whitespace-normal [&_th]:align-top [&_th]:whitespace-normal"
          aria-label="Proposed plan changes"
        >
          <TableHeader>
            <TableRow>
              <TableHead scope="col">#</TableHead>
              <TableHead scope="col">Day</TableHead>
              <TableHead scope="col">Session</TableHead>
              <TableHead scope="col">Workout</TableHead>
              <TableHead scope="col">{terminal ? 'Decision' : 'Accept'}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {changes.map((change, index) => {
              const after = proposedSession(change),
                session = after ?? change.before
              const week = weeks[index]
              const isStrengthOmission = change.material_flags.includes('strength_omission')
              const name = isStrengthOmission
                ? (session?.intent ?? '').trim() || 'Confirmed lift'
                : sessionName(session)
              const otherFlags = change.material_flags.filter(
                (flag) => flag !== 'strength_omission',
              )
              return (
                <Fragment key={change.change_id}>
                  {week && week !== weeks[index - 1] && (
                    <TableRow className="proposal-week-row">
                      <TableHead scope="colgroup" colSpan={5}>
                        {weekHeading(week)}
                      </TableHead>
                    </TableRow>
                  )}
                  <TableRow
                    className={
                      revision > 1 && firstRevisionChangeIds.includes(change.change_id)
                        ? 'proposal-revised-row'
                        : undefined
                    }
                  >
                    <TableHead scope="row">
                      <a
                        href={`#proposal-reason-${index + 1}`}
                        onClick={(event) => {
                          event.preventDefault()
                          const reason =
                            document.getElementById(`proposal-reason-${index + 1}`) ??
                            document.getElementById(`proposal-omission-${index + 1}`)
                          if (reason instanceof HTMLDetailsElement) reason.open = true
                          reason?.scrollIntoView({ behavior: 'smooth' })
                        }}
                        aria-label={`Read reason ${index + 1}`}
                      >
                        {index + 1}
                      </a>
                    </TableHead>
                    <TableCell>
                      {sessionDate(session)}
                      {change.before?.local_date &&
                        after?.local_date &&
                        change.before.local_date !== after.local_date && (
                          <small>Previously {sessionDate(change.before)}</small>
                        )}
                    </TableCell>
                    <TableCell>
                      <strong>{name}</strong>
                      <Badge className="status-chip">
                        {isStrengthOmission ? 'Skip lift' : ACTION_LABELS[change.op]}
                      </Badge>
                      {otherFlags.length > 0 && (
                        <small>
                          Review carefully:{' '}
                          {otherFlags.map((flag) => flag.replaceAll('_', ' ')).join(', ')}
                        </small>
                      )}
                    </TableCell>
                    <TableCell>
                      {!isStrengthOmission && after?.brief && (
                        <EffortLabel effort={after.brief.effort} />
                      )}
                      {isStrengthOmission ? (
                        <div id={`proposal-omission-${index + 1}`}>
                          <CoachText text={change.reason} />
                          <small>This change applies only to the lift.</small>
                        </div>
                      ) : after ? (
                        <SessionView value={after} empty="" compact />
                      ) : (
                        <>
                          <p>Remove this session from the plan.</p>
                          <SessionView value={change.before} empty="" compact />
                        </>
                      )}
                    </TableCell>
                    <TableCell>
                      {isDiscarded ? (
                        <span>Not applied</span>
                      ) : terminal ? (
                        <span>
                          Decision:{' '}
                          {acceptedChangeIds
                            ? acceptedChangeIds.includes(change.change_id)
                              ? 'accepted'
                              : 'rejected'
                            : change.decision}
                        </span>
                      ) : (
                        <label className="proposal-choice">
                          <input
                            type="checkbox"
                            aria-label={
                              isStrengthOmission
                                ? `Accept skipping ${name} on ${sessionDate(session)}`
                                : `Accept change ${change.change_id}`
                            }
                            aria-describedby={
                              isStrengthOmission ? `proposal-omission-${index + 1}` : undefined
                            }
                            checked={selected.includes(change.change_id)}
                            disabled={disabled || invalidChangeIds.has(change.change_id)}
                            onChange={() => onToggle(change.change_id)}
                          />
                          <span className="sr-only">Include session {index + 1}</span>
                          <span className="proposal-choice-mobile" aria-hidden="true">
                            Accept
                          </span>
                        </label>
                      )}
                    </TableCell>
                  </TableRow>
                  {!isStrengthOmission && (
                    <TableRow className="proposal-detail-row">
                      <TableCell colSpan={5}>
                        <Disclosure
                          id={`proposal-reason-${index + 1}`}
                          className="proposal-row-details"
                        >
                          <summary>{change.reason}</summary>
                          {after?.brief && (
                            <SessionBrief brief={after.brief} notes={null} layout="full" />
                          )}
                          {(change.before || isStale) && (
                            <Disclosure>
                              <summary>
                                Compare with {isStale ? 'saved and current plan' : 'previous plan'}
                              </summary>
                              <div className="proposal-diff">
                                <div>
                                  <h3>Before</h3>
                                  <SessionView value={change.before} empty="New session" />
                                </div>
                                {isStale && (
                                  <div>
                                    <h3>Current session</h3>
                                    <SessionView
                                      value={change.current}
                                      empty="No current session"
                                    />
                                  </div>
                                )}
                              </div>
                            </Disclosure>
                          )}
                        </Disclosure>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </Card>
  )
}
