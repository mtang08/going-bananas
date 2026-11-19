import { Badge, Button, Card } from './ui'
import {
  MARKER_LABELS,
  dateLabel,
  fmtDistance,
  fmtDuration,
  fmtPercent,
  pageHref,
  sessionTitle,
  type Unit,
  type WeeklyDigest as WeeklyDigestData,
} from '../api'
import { COMPONENT_LABELS, COMPONENT_STATUS_LABELS, reasonText } from '../lib/reasonLabels'
import './plan-overview.css'

export type DigestWeek = 'this' | 'last'

const KIND_LABELS = [
  ['run', 'Runs'],
  ['strength', 'Strength'],
  ['cross', 'Cross-training'],
  ['mobility', 'Mobility'],
] as const

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`
}

const NOT_DONE = new Set(['missed', 'not_recorded'])

export function WeeklyDigest({
  digest: d,
  unit,
  week,
  onWeekChange,
}: {
  digest: WeeklyDigestData
  unit: Unit
  week: DigestWeek
  onWeekChange: (week: DigestWeek) => void
}) {
  const t = d.totals
  const finished = d.days_elapsed >= 7
  const keyRows = d.sessions.filter((s) => s.key)
  const notDone = d.sessions.filter((s) => !s.key && s.kind !== 'mobility' && NOT_DONE.has(s.outcome))
  const outcomeDetail = (
    [
      ['partial', 'partial'],
      ['modified', 'modified'],
      ['missed', 'missed'],
      ['not_recorded', 'not recorded'],
    ] as const
  )
    .filter(([key]) => t.sessions.by_outcome[key] > 0)
    .map(([key, label]) => `${t.sessions.by_outcome[key]} ${label}`)
  const byKind = KIND_LABELS.filter(([kind]) => t.by_kind[kind].planned > 0).map(([kind, label]) => {
    const { done, planned_to_date } = t.by_kind[kind]
    return `${label} ${done}/${planned_to_date}`
  })
  const unplannedUnknown = d.unplanned.some((u) => u.duration_s === null)
  const unknowns = [
    t.time.planned_unknown > 0 && `${t.time.planned_unknown} planned without a duration`,
    t.time.actual_unknown > 0 && `${t.time.actual_unknown} recorded without a duration`,
    t.run_distance.planned_unknown > 0 &&
      `${t.run_distance.planned_unknown} planned runs without a distance`,
    t.run_distance.actual_unknown > 0 &&
      `${t.run_distance.actual_unknown} recorded runs without a distance`,
    !d.activity_coverage_complete && 'activity history may be incomplete',
  ].filter(Boolean)

  return (
    <Card className="weekly-digest" data-testid="weekly-digest">
      <div className="panel-head">
        <div>
          <h2>Planned vs done</h2>
          <p>
            {dateLabel(d.week_start)}–{dateLabel(d.week_end)} · Monday–Sunday
          </p>
        </div>
        <div className="digest-toggle" role="group" aria-label="Week">
          <Button
            size="sm"
            variant={week === 'this' ? 'default' : 'outline'}
            aria-pressed={week === 'this'}
            onClick={() => onWeekChange('this')}
          >
            This week
          </Button>
          <Button
            size="sm"
            variant={week === 'last' ? 'default' : 'outline'}
            aria-pressed={week === 'last'}
            onClick={() => onWeekChange('last')}
          >
            Last week
          </Button>
        </div>
      </div>
      {!d.plan_available ? (
        <p>No accepted plan for this week.</p>
      ) : (
        <>
          <strong className="digest-headline">
            {finished
              ? `${t.sessions.done} of ${t.sessions.planned} sessions done`
              : `${t.sessions.done} of ${t.sessions.planned_to_date} sessions done so far · ${t.sessions.planned} planned this week`}
          </strong>
          {outcomeDetail.length > 0 && <p className="muted-text">{outcomeDetail.join(' · ')}</p>}
          {byKind.length > 0 && <p className="muted-text">{byKind.join(' · ')}</p>}
          <p>
            Time: {fmtDuration(t.time.actual_s)} of {fmtDuration(t.time.planned_to_date_s)} planned
          </p>
          <p>
            Running: {fmtDistance(t.run_distance.actual_m, unit)} of{' '}
            {t.run_distance.planned_estimated > 0 ? '~' : ''}
            {fmtDistance(t.run_distance.planned_to_date_m, unit)} planned
          </p>
          {keyRows.length > 0 && (
            <>
              <h3>Key sessions</h3>
              {keyRows.map((row) => {
                const ex = row.execution
                return (
                  <div
                    className="digest-key-session"
                    data-testid="digest-key-session"
                    key={row.session_uid}
                  >
                    <strong>
                      {sessionTitle(row)} · {dateLabel(row.local_date, { weekday: 'short' })}
                    </strong>
                    <Badge className={`marker marker-${row.outcome}`}>
                      {MARKER_LABELS[row.outcome]}
                    </Badge>
                    {ex && (
                      <>
                        {ex.components.length > 0 && (
                          <ul className="digest-chips">
                            {ex.components.map((c) => (
                              <li key={c.name}>
                                {COMPONENT_LABELS[c.name]} {fmtPercent(c.value)} ·{' '}
                                {COMPONENT_STATUS_LABELS[c.status]}
                              </li>
                            ))}
                          </ul>
                        )}
                        {ex.reps_completed !== null && ex.reps_planned !== null && (
                          <span>Reps {ex.reps_completed} of {ex.reps_planned}</span>
                        )}
                        {ex.reason_codes.length > 0 && (
                          <span className="muted-text">
                            {ex.reason_codes.map(reasonText).join(' · ')}
                          </span>
                        )}
                      </>
                    )}
                    {row.actual?.subject === 'activity' && (
                      <a href={pageHref.activity(row.actual.id)}>Open run</a>
                    )}
                  </div>
                )
              })}
            </>
          )}
          {notDone.length > 0 && (
            <>
              <h3>Missed or not recorded</h3>
              <ul data-testid="digest-not-done">
                {notDone.map((row) => (
                  <li key={row.session_uid}>
                    {sessionTitle(row)} · {dateLabel(row.local_date, { weekday: 'short' })} ·{' '}
                    {MARKER_LABELS[row.outcome]}
                  </li>
                ))}
              </ul>
            </>
          )}
          {t.sessions.unplanned > 0 && (
            <p data-testid="digest-unplanned">
              Unplanned: {plural(t.sessions.unplanned, 'session', 'sessions')} ·{' '}
              {unplannedUnknown ? 'duration unknown' : fmtDuration(t.time.unplanned_s)}
            </p>
          )}
          {t.sessions.removed > 0 && (
            <p className="muted-text">
              {t.sessions.removed} removed from the plan by an accepted change
            </p>
          )}
          {unknowns.length > 0 && (
            <p className="muted-text weekly-mileage-note">
              Some amounts are unknown: {unknowns.join('; ')}
            </p>
          )}
        </>
      )}
    </Card>
  )
}
