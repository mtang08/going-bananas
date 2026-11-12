import { Badge, Button, Card, Disclosure } from './ui'
import type { ReactNode } from 'react'
import {
  addDays,
  dateLabel,
  fmtDistance,
  fmtDuration,
  MARKER_LABELS,
  sessionMarker,
  sessionTitle,
  type CalendarView,
  type Completion,
  type SessionState,
  type Unit,
} from '../api'
import { WorkoutStructure } from './WorkoutStructure'
import './plan-overview.css'

// Calendar dates come from the server's athlete timezone; UTC is only date arithmetic.
export function mondayOfWeek(today: string): string {
  const weekday = new Date(`${today}T12:00:00Z`).getUTCDay()
  return addDays(today, -((weekday + 6) % 7))
}
const kindLabels = {
  run: 'Run',
  strength: 'Strength',
  cross: 'Cross-training',
  rest: 'Rest',
  mobility: 'Mobility',
}
export function SessionSummary({
  session: s,
  completion,
  today,
  unit,
  children,
  showWorkout = false,
}: {
  session: SessionState
  completion?: Completion
  today: string
  unit: Unit
  children?: ReactNode
  showWorkout?: boolean
}) {
  const marker = sessionMarker(s, completion, today)
  const title =
    s.legacy_unstructured && s.kind === 'run'
      ? 'Imported run'
      : s.custom && !s.recipe_id
        ? s.intent
        : sessionTitle(s)
  return (
    <article
      className={`plan-session kind-${s.kind} certainty-${s.certainty}`}
      data-testid="session-tag"
    >
      <strong>{title}</strong>
      <span className="plan-session-type">{kindLabels[s.kind]}</span>
      <div className="plan-session-amounts">
        {s.planned_duration_s !== null && <span>{fmtDuration(s.planned_duration_s)}</span>}
        {s.planned_distance_m !== null && <span>{fmtDistance(s.planned_distance_m, unit)}</span>}
      </div>
      <div className="plan-session-status">
        <Badge className={`marker marker-${marker}`}>{MARKER_LABELS[marker]}</Badge>
        <span>{s.certainty === 'committed' ? 'Committed' : 'Provisional'}</span>
        {!s.is_original && <span>Changed</span>}
      </div>
      {showWorkout && s.structure && <WorkoutStructure structure={s.structure} unit={unit} />}
      {showWorkout ? (
        <>
          {s.intent && s.intent !== title && <p>{s.intent}</p>}
          {s.notes?.trim() &&
            (s.legacy_unstructured ? (
              <p className="plan-session-notes">{s.notes}</p>
            ) : (
              <Disclosure className="workout-notes">
                <summary>Session notes</summary>
                <p className="plan-session-notes">{s.notes}</p>
              </Disclosure>
            ))}
          {s.legacy_unstructured && <small>Structured comparison unavailable</small>}
        </>
      ) : (
        <>
          <Disclosure
            className="plan-session-details"
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.currentTarget.open = false
                event.currentTarget.querySelector('summary')?.focus()
              }
            }}
          >
            <summary>Session details</summary>
            {s.intent && <p>{s.intent}</p>}
            {!showWorkout && s.structure && (
              <WorkoutStructure structure={s.structure} unit={unit} />
            )}
            {s.notes?.trim() && (
              <Disclosure className="workout-notes">
                <summary>Session notes</summary>
                <p className="plan-session-notes">{s.notes}</p>
              </Disclosure>
            )}
            {s.legacy_unstructured && <small>Structured comparison unavailable</small>}
            {children}
            <Button
              variant="link"
              onClick={(event) => {
                const details = event.currentTarget.closest('details')
                if (details) {
                  details.open = false
                  details.querySelector('summary')?.focus()
                }
              }}
            >
              Close details
            </Button>
          </Disclosure>
        </>
      )}
    </article>
  )
}
export function WeekOverview({ view, unit }: { view: CalendarView; unit: Unit }) {
  const start = mondayOfWeek(view.today)
  return (
    <div className="plan-overview space-y-5">
      {[0, 1].map((week) => (
        <Card className="plan-week" key={week}>
          <div className="panel-head">
            <h2>{week === 0 ? 'This week' : 'Next week'}</h2>
            <span>
              {dateLabel(addDays(start, week * 7))}–{dateLabel(addDays(start, week * 7 + 6))}
            </span>
          </div>
          <div className="plan-week-grid">
            {Array.from({ length: 7 }, (_, i) => {
              const day = addDays(start, week * 7 + i)
              const sessions = view.sessions
                .filter((s) => !s.deleted && s.local_date === day)
                .sort((a, b) => a.slot - b.slot)
              return (
                <div
                  className={`plan-day${day === view.today ? ' is-today' : ''}`}
                  data-testid="strip-day"
                  data-date={day}
                  key={day}
                >
                  <h3>
                    {dateLabel(day, { weekday: 'short', day: 'numeric' })}
                    {day === view.today && <small>Today</small>}
                  </h3>
                  {sessions.length === 0 && <span className="day-empty">No session</span>}
                  {sessions.map((s) => (
                    <SessionSummary
                      key={s.session_uid}
                      session={s}
                      completion={view.completions.find((c) => c.session_uid === s.session_uid)}
                      today={view.today}
                      unit={unit}
                    />
                  ))}
                </div>
              )
            })}
          </div>
        </Card>
      ))}
    </div>
  )
}
