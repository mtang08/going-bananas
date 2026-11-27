import {
  CATEGORY_LABELS,
  LADDER_LABELS,
  OUTCOME_LABELS,
  RECALIBRATION_LABELS,
  SEVERITY_LABELS,
} from '../../coachLabels'
import type {
  ProposalEventReview,
  ProposalException,
  ProposalPatchResolution,
} from '../../api/types/exceptions'
import { Badge, Card } from '../../components/ui'
import { sessionTitle } from '../../lib/session'
import type { SessionState } from '../../api/types/calendar'
import { dateLabel, fmtDuration } from '../../lib/format'
import { formatStep } from '../../lib/structure'
import type { ProposalSession } from '../../api/types/coach'
import { readStructure, sessionName, sessionDate } from './helpers'

import { CoachText } from '../../components/CoachText'
import { SessionBrief } from '../../components/SessionBrief'

export function SessionView({
  value,
  empty,
  compact = false,
}: {
  value: ProposalSession | null
  empty: string
  compact?: boolean
}) {
  if (!value) return <p className="muted-text">{empty}</p>
  const structure = readStructure(value)
  return (
    <div className="proposal-session">
      {!compact && value.local_date && (
        <strong>
          {sessionDate(value)} · {sessionName(value)}
        </strong>
      )}
      {value.intent && <p>{value.intent}</p>}
      {'planned_duration_s' in value && (
        <p>
          Duration:{' '}
          {value.planned_duration_s == null
            ? 'Not specified'
            : fmtDuration(value.planned_duration_s)}
        </p>
      )}
      {'planned_distance_m' in value && (
        <p>
          Distance:{' '}
          {value.planned_distance_m == null
            ? 'Not specified'
            : `${(value.planned_distance_m / 1000).toFixed(2)} km`}
        </p>
      )}
      {compact && value.notes && <p>{value.notes}</p>}
      {value.legacy_unstructured ? (
        <p>Imported prescription · structured comparison unavailable</p>
      ) : structure.invalid ? (
        <p role="alert">
          This workout's steps are invalid. Ask the coach for a corrected proposal.
        </p>
      ) : (
        value.structure && (
          <ol>
            {value.structure.map((step, index) => (
              <li key={index}>
                {step.type === 'repeat'
                  ? `${step.count} × (${step.steps.map((child) => formatStep(child, 'km')).join('; ')})`
                  : formatStep(step, 'km')}
              </li>
            ))}
          </ol>
        )
      )}
      {!compact && (value.brief || value.notes) && (
        <SessionBrief brief={value.brief ?? null} notes={value.notes ?? null} layout="full" />
      )}
    </div>
  )
}

const shortDate = (d: string) => dateLabel(d, { weekday: 'short', month: 'short', day: 'numeric' })
function TextList({ title, items }: { title: string; items: string[] }) {
  return (
    <>
      <h3>{title}</h3>
      <ul>
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </>
  )
}
export function ExceptionCard({
  exc,
  sessions,
}: {
  exc: ProposalException
  sessions: SessionState[]
}) {
  return (
    <Card className="proposal-exception" data-testid="proposal-exception">
      <h2>Exception</h2>
      <p>
        <Badge>{CATEGORY_LABELS[exc.category]}</Badge>{' '}
        <Badge>{SEVERITY_LABELS[exc.severity]}</Badge> <span>Confidence: {exc.confidence}</span>
      </p>
      <h3>Why now</h3>
      <CoachText text={exc.triggering_evidence} />
      {exc.relevant_context && (
        <>
          <h3>Context</h3>
          <CoachText text={exc.relevant_context} />
        </>
      )}
      <h3>Plan impact</h3>
      <p>
        {LADDER_LABELS[exc.ladder_level]} · {shortDate(exc.patch_window.start)}–
        {shortDate(exc.patch_window.end)}
      </p>
      {exc.unchanged && exc.unchanged.length > 0 && (
        <>
          <h4>Unchanged</h4>
          <ul>
            {exc.unchanged.map((item) => {
              const s = sessions.find((row) => row.session_uid === item.session_uid)
              return (
                <li key={item.session_uid}>
                  {s ? `${shortDate(s.local_date)} · ${sessionTitle(s)}` : 'Session'} —{' '}
                  {item.reason}
                </li>
              )
            })}
          </ul>
        </>
      )}
      <p>
        <strong>Reassess on {shortDate(exc.reassess_on)}</strong>
      </p>
      <TextList title="Watch for" items={exc.monitor} />
      <TextList title="Back to plan when" items={exc.return_criteria} />
      <TextList title="Escalate if" items={exc.escalate_criteria} />
    </Card>
  )
}

export function EventReviewCard({
  review,
  operation,
}: {
  review: ProposalEventReview
  operation: string
}) {
  const rows: [string, string | null | undefined][] = [
    ['Outcome', review.outcome ? OUTCOME_LABELS[review.outcome] : null],
    ['Compared with', review.compared_with],
    ['Pacing', review.pacing],
    ['Effort and limiter', review.effort_and_limiter],
    ['Conditions', review.conditions],
    ['Symptoms', review.symptoms],
    ['Recovery observation', review.recovery_observation],
    ['Recalibration', RECALIBRATION_LABELS[review.recalibration]],
    ['Training implication', review.training_implication],
  ]
  return (
    <Card className="proposal-event-review" data-testid="proposal-event-review">
      <h2>{operation === 'review_training_block' ? 'Benchmark review' : 'Race review'}</h2>
      <dl>
        {rows
          .filter(([, value]) => value)
          .map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>
                <CoachText text={value!} />
              </dd>
            </div>
          ))}
      </dl>
    </Card>
  )
}
export function PatchUpdates({ items }: { items: ProposalPatchResolution[] }) {
  return (
    <Card className="proposal-patch-updates" data-testid="proposal-patch-updates">
      <h2>Patch updates</h2>
      <ul>
        {items.map((item) => (
          <li key={item.patch_id}>
            <Badge>{item.status === 'resolved' ? 'Resolved' : 'Escalated'}</Badge>
            <CoachText text={item.note} />
          </li>
        ))}
      </ul>
    </Card>
  )
}
