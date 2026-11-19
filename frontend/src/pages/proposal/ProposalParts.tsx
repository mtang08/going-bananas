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

// Coach copy supports plain paragraphs and dash bullets, without interpreting HTML.
export function CoachText({ text }: { text: string }) {
  return (
    <div className="proposal-copy">
      {text
        .split(/\n\s*\n/)
        .filter((part) => part.trim())
        .map((part, index) => {
          const lines = part.trim().split('\n')
          return lines.every((line) => /^\s*[-*] /.test(line)) ? (
            <ul key={index}>
              {lines.map((line, i) => (
                <li key={i}>{line.replace(/^\s*[-*] /, '')}</li>
              ))}
            </ul>
          ) : (
            <p key={index}>{part}</p>
          )
        })}
    </div>
  )
}

export function SessionView({
  value,
  empty,
  compact = false,
  plain,
}: {
  value: ProposalSession | null
  empty: string
  compact?: boolean
  plain: (text: string) => string
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
      {value.intent && <p>{plain(value.intent)}</p>}
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
      {value.notes && <p>{plain(value.notes)}</p>}
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
                  ? `${step.count} × (${step.steps.map((child) => plain(formatStep(child, 'km'))).join('; ')})`
                  : plain(formatStep(step, 'km'))}
              </li>
            ))}
          </ol>
        )
      )}
    </div>
  )
}

const shortDate = (d: string) => dateLabel(d, { weekday: 'short', month: 'short', day: 'numeric' })
function TextList({
  title,
  items,
  plain,
}: {
  title: string
  items: string[]
  plain: (t: string) => string
}) {
  return (
    <>
      <h3>{title}</h3>
      <ul>
        {items.map((item, i) => (
          <li key={i}>{plain(item)}</li>
        ))}
      </ul>
    </>
  )
}
export function ExceptionCard({
  exc,
  sessions,
  plain,
}: {
  exc: ProposalException
  sessions: SessionState[]
  plain: (t: string) => string
}) {
  return (
    <Card className="proposal-exception" data-testid="proposal-exception">
      <h2>Exception</h2>
      <p>
        <Badge>{CATEGORY_LABELS[exc.category]}</Badge>{' '}
        <Badge>{SEVERITY_LABELS[exc.severity]}</Badge> <span>Confidence: {exc.confidence}</span>
      </p>
      <h3>Why now</h3>
      <CoachText text={plain(exc.triggering_evidence)} />
      {exc.relevant_context && (
        <>
          <h3>Context</h3>
          <CoachText text={plain(exc.relevant_context)} />
        </>
      )}
      <h3>Plan impact</h3>
      <p>
        {LADDER_LABELS[exc.ladder_level]} · {shortDate(exc.patch_window.start)}–
        {shortDate(exc.patch_window.end)}
      </p>
      {exc.unchanged.length > 0 && (
        <>
          <h4>Unchanged</h4>
          <ul>
            {exc.unchanged.map((item) => {
              const s = sessions.find((row) => row.session_uid === item.session_uid)
              return (
                <li key={item.session_uid}>
                  {s ? `${shortDate(s.local_date)} · ${sessionTitle(s)}` : 'Session'} —{' '}
                  {plain(item.reason)}
                </li>
              )
            })}
          </ul>
        </>
      )}
      <p>
        <strong>Reassess on {shortDate(exc.reassess_on)}</strong>
      </p>
      <TextList title="Watch for" items={exc.monitor} plain={plain} />
      <TextList title="Back to plan when" items={exc.return_criteria} plain={plain} />
      <TextList title="Escalate if" items={exc.escalate_criteria} plain={plain} />
    </Card>
  )
}

export function EventReviewCard({
  review,
  operation,
  plain,
}: {
  review: ProposalEventReview
  operation: string
  plain: (t: string) => string
}) {
  const rows: [string, string | null][] = [
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
                <CoachText text={plain(value!)} />
              </dd>
            </div>
          ))}
      </dl>
    </Card>
  )
}
export function PatchUpdates({
  items,
  plain,
}: {
  items: ProposalPatchResolution[]
  plain: (t: string) => string
}) {
  return (
    <Card className="proposal-patch-updates" data-testid="proposal-patch-updates">
      <h2>Patch updates</h2>
      <ul>
        {items.map((item) => (
          <li key={item.patch_id}>
            <Badge>{item.status === 'resolved' ? 'Resolved' : 'Escalated'}</Badge>
            <CoachText text={plain(item.note)} />
          </li>
        ))}
      </ul>
    </Card>
  )
}
