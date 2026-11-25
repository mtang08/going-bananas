import { Badge, Button, Disclosure } from './ui'
import type { ReactNode } from 'react'
import { addDays, dateLabel, fmtDistance, fmtDuration, type Unit } from '../lib/format'
import {
  MARKER_LABELS,
  type Completion,
  type SessionBrief as SessionBriefData,
  type SessionState,
} from '../api/types/calendar'
import { sessionMarker, sessionTitle } from '../lib/session'
import { WorkoutStructure } from './WorkoutStructure'
import { EffortLabel } from './CoachText'
import { SessionBrief } from './SessionBrief'
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
  rehab: 'Rehab',
}
function PurposeEffort({
  intent,
  brief,
}: {
  intent: string | null
  brief: SessionBriefData | null
}) {
  if (!intent && !brief) return null
  return (
    <div className="plan-session-purpose">
      {intent && (
        <p>
          <small>Purpose</small> <span>{intent}</span>
        </p>
      )}
      {brief && <EffortLabel effort={brief.effort} />}
    </div>
  )
}

export function SessionSummary({
  session: s,
  completion,
  today,
  unit,
  children,
  showWorkout = false,
  unavailable = false,
}: {
  session: SessionState
  completion?: Completion
  today: string
  unit: Unit
  children?: ReactNode
  showWorkout?: boolean
  unavailable?: boolean
}) {
  const marker = sessionMarker(s, completion, today)
  const title =
    s.legacy_unstructured && s.kind === 'run'
      ? 'Imported run'
      : (s.custom && !s.recipe_id) || (s.kind === 'rehab' && s.intent)
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
        <Badge className={`marker marker-${marker}`}>
          {completion?.match_method === 'user_marked' && marker === 'completed'
            ? 'Completed · self-reported'
            : MARKER_LABELS[marker]}
        </Badge>
        <span>{s.certainty === 'committed' ? 'Committed' : 'Provisional'}</span>
        {!s.is_original && <span>Changed</span>}
        {s.recipe_id === 'REC009' && <Badge className="benchmark-chip">Benchmark</Badge>}
        {s.exception_patch?.status === 'open' && (
          <Badge className="patch-chip" data-testid="patch-badge">
            Patched · reassess {dateLabel(s.exception_patch.reassess_on, { weekday: 'long' })}
          </Badge>
        )}
      </div>
      {showWorkout ? (
        <>
          {s.running_restriction_conflict &&
            (marker === 'planned' || marker === 'not_recorded') && (
              <p className="error-text" role="status">
                {s.running_restriction_conflict}
              </p>
            )}
          {unavailable ? (
            <p role="status">Unavailable during your interruption. Review this accepted run.</p>
          ) : (
            <>
              <PurposeEffort
                intent={s.intent && s.intent !== title ? s.intent : null}
                brief={s.brief}
              />
              {s.structure && <WorkoutStructure structure={s.structure} unit={unit} />}
              <SessionBrief brief={s.brief} notes={s.notes} layout="today" />
            </>
          )}
          {children}
          {s.legacy_unstructured && <small>Structured comparison unavailable</small>}
        </>
      ) : (
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
          <PurposeEffort intent={s.intent || null} brief={s.brief} />
          {s.structure && <WorkoutStructure structure={s.structure} unit={unit} />}
          <SessionBrief brief={s.brief} notes={s.notes} layout="full" />
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
      )}
    </article>
  )
}
