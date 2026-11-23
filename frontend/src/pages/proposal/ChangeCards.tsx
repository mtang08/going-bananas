import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import { qk } from '../../api/queryKeys'
import type { RaceEvent } from '../../api/types/blocks'
import { dateLabel } from '../../lib/format'
import { RECIPE_LABELS } from '../../api/types/calendar'
import type { ProposalDecisionResult, ProposalDetail } from '../../api/types/coach'
import {
  Badge,
  Card,
  Disclosure,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui'
import { INDICATOR_LABELS, WhyList } from '../../components/CoachText'

export function BlockChangeCard({
  change,
  terminal,
  isDiscarded,
  decision,
  checked,
  disabled,
  onChange,
}: {
  change: NonNullable<ProposalDetail['block_change']>
  terminal: boolean
  isDiscarded: boolean
  decision: ProposalDecisionResult | null | undefined
  checked: boolean
  disabled: boolean
  onChange: (checked: boolean) => void
}) {
  const fields = change.version_fields
  const targetId = fields.target_event_id
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
  const outline = fields.build_outline ?? []
  const why = fields.why ?? []
  const indicators = fields.indicators ?? []
  const triggers = fields.early_review_triggers ?? []
  const qualities = fields.maintained_qualities ?? []
  const nonGoals = fields.non_goals ?? []
  const constraints = fields.constraints ?? []
  const eligible = fields.eligible_recipe_ids ?? []
  const benchmark = fields.benchmark
  return (
    <Card className="block-change-card">
      <h2>Training block: {change.decision}</h2>
      <p className="block-change-summary">
        <strong>{fields.objective ?? ''}</strong>
        {' · '}
        {fields.start_date ? dateLabel(fields.start_date) : 'Start not set'} →{' '}
        {fields.review_date ? dateLabel(fields.review_date) : 'review not set'}
        {' · '}
        <span data-testid="builds-toward">{`Builds toward: ${builtToward}`}</span>
      </p>
      <div className="block-change-chips">
        {fields.status && <Badge variant="secondary">{fields.status}</Badge>}
        {fields.progression_dimension && (
          <Badge variant="outline">
            Progression: {fields.progression_dimension.replaceAll('_', ' ')}
          </Badge>
        )}
        {fields.objective_status && (
          <Badge variant="outline">Objective: {fields.objective_status.replaceAll('_', ' ')}</Badge>
        )}
        {benchmark && (
          <Badge variant="outline">Benchmark: {dateLabel(benchmark.planned_date)}</Badge>
        )}
      </div>
      {outline.length > 0 && (
        <ul aria-label="Build outline">
          {outline.map((step, index) => (
            <li key={index}>{`${step.weeks} wk ${step.emphasis}`}</li>
          ))}
        </ul>
      )}
      {why.length > 0 && (
        <Disclosure className="block-change-section">
          <summary>Why this block</summary>
          <WhyList items={why} />
        </Disclosure>
      )}
      {(indicators.length > 0 || triggers.length > 0) && (
        <Disclosure className="block-change-section">
          <summary>Review by</summary>
          {indicators.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Indicator</TableHead>
                  <TableHead>Progress when</TableHead>
                  <TableHead>Source</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {indicators.map((item, index) => (
                  <TableRow key={index}>
                    <TableCell>{item.label}</TableCell>
                    <TableCell>{item.progress_when}</TableCell>
                    <TableCell>{INDICATOR_LABELS[item.source]}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {triggers.length > 0 && (
            <p>
              <strong>Review early if:</strong>{' '}
              {triggers.map((value, index) => (
                <span key={index}>
                  {index > 0 && ' · '}
                  {value}
                </span>
              ))}
            </p>
          )}
        </Disclosure>
      )}
      {(qualities.length > 0 ||
        nonGoals.length > 0 ||
        constraints.length > 0 ||
        eligible.length > 0) && (
        <Disclosure className="block-change-section">
          <summary>Qualities, constraints, eligible sessions</summary>
          {qualities.length > 0 && (
            <p>
              <strong>Maintains:</strong> {qualities.join(', ')}
            </p>
          )}
          {nonGoals.length > 0 && (
            <p>
              <strong>Outside this block:</strong> {nonGoals.join(', ')}
            </p>
          )}
          {constraints.length > 0 && (
            <ul>
              {constraints.map((constraint, index) => (
                <li key={index}>
                  {constraint.kind}: {constraint.text}
                </li>
              ))}
            </ul>
          )}
          {eligible.length > 0 && (
            <p>
              <strong>Eligible sessions:</strong>{' '}
              {eligible.map((id) => RECIPE_LABELS[id] ?? 'Custom session').join(', ')}
            </p>
          )}
        </Disclosure>
      )}
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
