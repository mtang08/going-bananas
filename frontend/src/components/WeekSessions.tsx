import { MARKER_LABELS, type DigestRow, type WeeklyDigest } from '../api/types/calendar'
import {
  dateLabel,
  distance,
  duration,
  fmtPercent,
  pace,
  sportLabel,
  type Unit,
} from '../lib/format'
import { COMPONENT_LABELS, COMPONENT_STATUS_LABELS, reasonText } from '../lib/reasonLabels'
import { pageHref } from '../lib/routes'
import { sessionTitle } from '../lib/session'
import type { DigestWeek } from './WeeklyDigest'
import { Badge, Card } from './ui'
import './plan-overview.css'

function PlannedSession({ row, unit }: { row: DigestRow; unit: Unit }) {
  const { actual, execution } = row
  const isRun = row.kind === 'run'
  const plannedDistance = distance(row.planned_distance_m, unit)
  const estimate = row.planned_distance_estimated && row.planned_distance_m !== null ? '~' : ''
  return (
    <article
      className="week-session"
      data-testid="week-session"
      data-date={row.local_date}
      data-kind={row.kind}
    >
      <div>
        <strong>{sessionTitle(row)}</strong> · {dateLabel(row.local_date, { weekday: 'short' })}{' '}
        <Badge className={`marker marker-${row.outcome}`}>{MARKER_LABELS[row.outcome]}</Badge>
      </div>
      <p>
        Planned: {duration(row.planned_duration_s)}
        {isRun && ` · ${estimate}${plannedDistance}`}
      </p>
      {actual && (
        <p>
          Done: {duration(actual.duration_s)}
          {actual.subject === 'activity' && (
            <>
              {isRun &&
                ` · ${distance(actual.distance_m, unit)} · ${pace(actual.moving_pace_s_per_km, unit)}`}
              {' · '}
              {actual.avg_hr_bpm == null ? '—' : `${Math.round(actual.avg_hr_bpm)} bpm`}
              {' · RPE '}
              {actual.rpe == null ? '—' : Number(actual.rpe.toFixed(1))}
              {isRun && ` · ${actual.sport ? sportLabel(actual.sport) : '—'}`}
            </>
          )}
        </p>
      )}
      {isRun && execution && (
        <>
          {execution.components.length > 0 && (
            <ul className="digest-chips">
              {execution.components.map((c) => (
                <li key={c.name}>
                  {COMPONENT_LABELS[c.name]} {fmtPercent(c.value)} ·{' '}
                  {COMPONENT_STATUS_LABELS[c.status]}
                </li>
              ))}
            </ul>
          )}
          {execution.reps_completed !== null && execution.reps_planned !== null && (
            <span>
              Reps {execution.reps_completed} of {execution.reps_planned}
            </span>
          )}
          {execution.reason_codes.length > 0 && (
            <span className="muted-text">{execution.reason_codes.map(reasonText).join(' · ')}</span>
          )}
        </>
      )}
      {actual?.subject === 'activity' && <a href={pageHref.activity(actual.id)}>Open run</a>}
    </article>
  )
}

export function WeekSessions({
  digest,
  unit,
  week,
}: {
  digest: WeeklyDigest
  unit: Unit
  week: DigestWeek
}) {
  const items = [
    ...digest.sessions.map((row) => ({ type: 'planned' as const, row })),
    ...digest.unplanned.map((row) => ({ type: 'unplanned' as const, row })),
  ].sort((a, b) => a.row.local_date.localeCompare(b.row.local_date))

  return (
    <Card className="week-sessions" data-testid="week-sessions">
      <h2>{week === 'this' ? "This week's sessions" : "Last week's sessions"}</h2>
      {items.length === 0 && (
        <p>
          {digest.plan_available ? 'No sessions this week.' : 'No accepted plan for this week.'}
        </p>
      )}
      {items.map(({ type, row }) =>
        type === 'planned' ? (
          <PlannedSession key={row.session_uid} row={row} unit={unit} />
        ) : (
          <article
            key={`${row.subject}:${row.id}`}
            className="week-session"
            data-testid="week-session"
            data-date={row.local_date}
            data-kind="unplanned"
          >
            <div>
              <strong>Unplanned {row.kind}</strong> ·{' '}
              {dateLabel(row.local_date, { weekday: 'short' })}
            </div>
            <p>
              {duration(row.duration_s)}
              {row.kind === 'run' && ` · ${distance(row.distance_m, unit)}`}
            </p>
            {row.subject === 'activity' && <a href={pageHref.activity(row.id)}>Open run</a>}
          </article>
        ),
      )}
    </Card>
  )
}
