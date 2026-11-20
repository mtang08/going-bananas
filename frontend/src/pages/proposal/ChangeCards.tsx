import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import { qk } from '../../api/queryKeys'
import type { RaceEvent } from '../../api/types/blocks'
import { dateLabel } from '../../lib/format'
import { RECIPE_LABELS } from '../../api/types/calendar'
import type { ProposalDecisionResult, ProposalDetail } from '../../api/types/coach'
import { Card } from '../../components/ui'

export function BlockChangeCard({
  change,
  terminal,
  isDiscarded,
  decision,
  checked,
  disabled,
  onChange,
  plain,
}: {
  change: NonNullable<ProposalDetail['block_change']>
  terminal: boolean
  isDiscarded: boolean
  decision: ProposalDecisionResult | null | undefined
  checked: boolean
  disabled: boolean
  onChange: (checked: boolean) => void
  plain: (text: string) => string
}) {
  const targetId = change.version_fields.target_event_id
  const events = useQuery({
    queryKey: qk.events,
    queryFn: () => api<{ items: RaceEvent[] }>('/events'),
    enabled: Boolean(targetId),
  })
  const target = events.data?.data?.items?.find((event) => event.id === targetId)
  const builtToward = !targetId
    ? 'no event'
    : target
      ? `${target.name} (${dateLabel(target.event_date)})`
      : events.isPending
        ? 'loading event'
        : events.isError
          ? 'event unavailable'
          : 'event not found'
  const outline = change.version_fields.build_outline ?? []
  return (
    <Card>
      <h2>Training block: {change.decision}</h2>
      <p>{plain(change.version_fields.objective ?? '')}</p>
      <p>{plain(change.version_fields.rationale ?? '')}</p>
      <p>
        {change.version_fields.start_date} · Review{' '}
        {change.version_fields.review_date ?? 'Not specified'}
      </p>
      <p data-testid="builds-toward">{`Builds toward: ${builtToward}`}</p>
      {outline.length > 0 && (
        <ul aria-label="Build outline">
          {outline.map((step, index) => (
            <li key={index}>{`${step.weeks} wk ${plain(step.emphasis)}`}</li>
          ))}
        </ul>
      )}
      <p>
        Status: {change.version_fields.status} · Objective:{' '}
        {change.version_fields.objective_status?.replaceAll('_', ' ')}
      </p>
      <p>Progression: {change.version_fields.progression_dimension?.replaceAll('_', ' ')}</p>
      <p>
        Eligible sessions:{' '}
        {change.version_fields.eligible_recipe_ids
          ?.map((id) => RECIPE_LABELS[id] ?? 'Custom session')
          .join(', ') || 'Not specified'}
      </p>
      <p>
        Maintained qualities:{' '}
        {change.version_fields.maintained_qualities?.join(', ') || 'Not specified'}
      </p>
      <p>Outside this block: {change.version_fields.non_goals?.join(', ') || 'Not specified'}</p>
      <ul>
        {change.version_fields.constraints?.map((constraint, index) => (
          <li key={index}>
            {constraint.kind}: {plain(constraint.text)}
          </li>
        ))}
      </ul>
      <p>
        Completion indicators:{' '}
        {change.version_fields.completion_indicators?.join('; ') || 'Not specified'}
      </p>
      <p>
        Earlier review: {change.version_fields.early_review_triggers?.join('; ') || 'Not specified'}
      </p>
      {terminal ? (
        <p>
          {isDiscarded
            ? 'Block change not applied'
            : `Block decision: ${decision ? (decision.block_version_id ? 'accepted' : 'rejected') : 'Unavailable'}`}
        </p>
      ) : (
        <label className="proposal-choice">
          <input
            type="checkbox"
            checked={checked}
            disabled={disabled}
            onChange={(event) => onChange(event.target.checked)}
          />
          Accept block change
        </label>
      )}
    </Card>
  )
}

export function AnchorChangeCard({
  anchor,
  terminal,
  isDiscarded,
  decision,
  checked,
  disabled,
  onToggle,
}: {
  anchor: ProposalDetail['anchor_changes'][number]
  terminal: boolean
  isDiscarded: boolean
  decision: ProposalDecisionResult | null | undefined
  checked: boolean
  disabled: boolean
  onToggle: () => void
}) {
  return (
    <Card>
      <h2>{anchor.kind.replaceAll('_', ' ')}</h2>
      <p>
        {anchor.value_low}
        {anchor.value_high != null ? `–${anchor.value_high}` : ''} {anchor.unit} ·{' '}
        {anchor.protocol.replaceAll('_', ' ')} · {anchor.confidence} confidence
      </p>
      <p>
        Calibrated {anchor.calibrated_at.slice(0, 10)}
        {anchor.supersedes_key ? ` · Replaces ${anchor.supersedes_key}` : ''}
      </p>
      {terminal ? (
        <p>
          {isDiscarded
            ? 'Anchor change not applied'
            : `Anchor decision: ${decision ? (decision.anchor_keys.includes(anchor.anchor_key) ? 'accepted' : 'rejected') : 'Unavailable'}`}
        </p>
      ) : (
        <label className="proposal-choice">
          <input type="checkbox" checked={checked} disabled={disabled} onChange={onToggle} />
          Accept anchor {anchor.anchor_key}
        </label>
      )}
    </Card>
  )
}
