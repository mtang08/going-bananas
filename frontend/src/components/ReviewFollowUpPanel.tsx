import { MARKER_LABELS, type ReviewFollowUp } from '../api/types/calendar'
import { dateLabel, fmtDistance, fmtDuration, fmtRpe, type Unit } from '../lib/format'
import { pageHref } from '../lib/routes'

function dose(duration: number | null, distance: number | null, unit: Unit) {
  return [
    duration !== null && fmtDuration(duration),
    distance !== null && fmtDistance(distance, unit),
  ]
    .filter(Boolean)
    .join(' · ')
}

function responseText(response: ReviewFollowUp['response']) {
  if (!response) return 'No delayed response recorded.'
  const details = response.symptoms.map((s) =>
    [s.side !== 'na' && s.side, s.site, `${s.severity}/10`].filter(Boolean).join(' '),
  )
  const pain =
    response.pain_reported === false
      ? 'No pain reported'
      : details.length
        ? details.join(', ')
        : response.pain_reported
          ? 'Pain reported'
          : 'Pain question unanswered'
  const gait = { yes: 'gait changed', no: 'no gait change', unsure: 'gait change uncertain' }
  return [
    pain,
    response.gait_change && gait[response.gait_change],
    response.hours_after_end !== null && `${response.hours_after_end} h after the run`,
  ]
    .filter(Boolean)
    .join(' · ')
}

export function ReviewFollowUpPanel({ review, unit }: { review: ReviewFollowUp; unit: Unit }) {
  const { accepted, actual, next_check: next } = review
  const planned = dose(accepted.duration_s, accepted.distance_m, unit)
  const recorded = actual && dose(actual.duration_s, actual.distance_m, unit)
  return (
    <section className="grid gap-2 rounded-md border p-3" aria-label="Follow-up on an accepted run">
      <h3>Follow-up on an accepted run</h3>
      <p>
        <strong>
          {dateLabel(accepted.local_date)} · {accepted.intent}
        </strong>
        {planned && ` · ${planned}`}
        {accepted.effort && ` · RPE ${accepted.effort.rpe_low}–${accepted.effort.rpe_high}/10`}
      </p>
      <p>{review.reason}</p>
      {review.edited_since && (
        <p className="muted-text">The calendar was edited after this prescription was accepted.</p>
      )}
      <p>
        <strong>{MARKER_LABELS[review.outcome]}</strong>
        {review.modification_reason && ` · ${review.modification_reason.replaceAll('_', ' ')}`}
        {actual && ` · ${dateLabel(actual.local_date)}`}
        {recorded && ` · ${recorded}`}
        {actual && (actual.rpe === null ? ' · Effort unreported' : ` · RPE ${fmtRpe(actual.rpe)}`)}
      </p>
      <p>{responseText(review.response)}</p>
      {next && (
        <p>
          <strong>Plan review on {dateLabel(next.on)}</strong> · {next.check}
        </p>
      )}
      <div className="flex flex-wrap gap-x-4">
        <a href={`#proposal/${encodeURIComponent(review.proposal_id)}`}>View accepted decision</a>
        {actual?.subject === 'activity' && (
          <a href={pageHref.activity(actual.id)}>View workout feedback</a>
        )}
      </div>
    </section>
  )
}
