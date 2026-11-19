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
import { CoachText, SessionView } from './ProposalParts'

export function ProposedChanges({
  changes,
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
  plain,
}: {
  changes: ProposalChange[]
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
  plain: (text: string) => string
}) {
  return (
    <>
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
                return (
                  <TableRow
                    key={change.change_id}
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
                          const reason = document.getElementById(`proposal-reason-${index + 1}`)
                          const disclosure = reason?.closest<HTMLDetailsElement>(
                            'details.proposal-reasons',
                          )
                          if (disclosure) disclosure.open = true
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
                      <strong>{sessionName(session)}</strong>
                      <Badge className="status-chip">{ACTION_LABELS[change.op]}</Badge>
                      {change.material_flags.length > 0 && (
                        <small>
                          Review carefully:{' '}
                          {change.material_flags
                            .map((flag) => flag.replaceAll('_', ' '))
                            .join(', ')}
                        </small>
                      )}
                    </TableCell>
                    <TableCell>
                      {after ? (
                        <SessionView value={after} empty="" compact plain={plain} />
                      ) : (
                        <>
                          <p>Remove this session from the plan.</p>
                          <SessionView value={change.before} empty="" compact plain={plain} />
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
                            aria-label={`Accept change ${change.change_id}`}
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
                )
              })}
            </TableBody>
          </Table>
        </div>
      </Card>
      <Disclosure variant="card" className="proposal-reasons">
        <summary>Session reasons and comparisons</summary>
        <ol>
          {changes.map((change, index) => (
            <li id={`proposal-reason-${index + 1}`} key={change.change_id}>
              <h3>
                {sessionDate(proposedSession(change) ?? change.before)} ·{' '}
                {sessionName(proposedSession(change) ?? change.before)}
              </h3>
              <CoachText text={plain(change.reason)} />
              {(change.before || isStale) && (
                <Disclosure>
                  <summary>
                    Compare with {isStale ? 'saved and current plan' : 'previous plan'}
                  </summary>
                  <div className="proposal-diff">
                    <div>
                      <h3>Before</h3>
                      <SessionView value={change.before} empty="New session" plain={plain} />
                    </div>
                    {isStale && (
                      <div>
                        <h3>Current session</h3>
                        <SessionView
                          value={change.current}
                          empty="No current session"
                          plain={plain}
                        />
                      </div>
                    )}
                  </div>
                </Disclosure>
              )}
            </li>
          ))}
        </ol>
      </Disclosure>
    </>
  )
}
