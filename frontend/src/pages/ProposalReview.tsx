import { Badge, Button, Card, Disclosure } from '../components/ui'
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { qk, type CalendarView, ApiError, api, post, RECIPE_LABELS } from '../api'
import type {
  ProposalDecision,
  ProposalDecisionResult,
  ProposalDetail,
  ProposalDiscardResult,
} from '../api/types/coach'
import { QueryState } from '../components/QueryState'
import { readStructure, proposedSession, stripReferenceIds } from './proposal/helpers'
import { CoachText, ExceptionCard, EventReviewCard, PatchUpdates } from './proposal/ProposalParts'
import { ProposedChanges } from './proposal/ProposedChanges'

export function ProposalReview({ proposalId }: { proposalId: string }) {
  return <ReviewForm key={proposalId} proposalId={proposalId} />
}

function ReviewForm({ proposalId }: { proposalId: string }) {
  const qc = useQueryClient()
  const detail = useQuery({
    queryKey: ['v2', 'proposals', proposalId],
    queryFn: () => api<ProposalDetail>(`/coach/proposals/${encodeURIComponent(proposalId)}`),
  })
  const [selected, setSelected] = useState<string[]>([])
  const [anchors, setAnchors] = useState<string[]>([])
  const [block, setBlock] = useState(false)
  const [result, setResult] = useState<ProposalDecisionResult | null>(null)
  const [stale, setStale] = useState(false)
  const [revisionConflict, setRevisionConflict] = useState(false)
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const [discarded, setDiscarded] = useState(false)
  const [reviewedRevision, setReviewedRevision] = useState<number | null>(null)
  const frozen = useRef<{ signature: string; body: ProposalDecision } | null>(null)
  const proposal = detail.data?.data
  const needsSessions = (proposal?.exception?.unchanged.length ?? 0) > 0
  const head = useQuery({
    queryKey: qk.calendarView('head'),
    enabled: needsSessions,
    queryFn: () => api<CalendarView>('/calendar'),
  })

  useEffect(() => {
    if (!proposal || reviewedRevision === proposal.revision) return
    setSelected([])
    setAnchors([])
    setBlock(false)
    setResult(null)
    setConfirmDiscard(false)
    frozen.current = null
    mutation.reset()
    setReviewedRevision(proposal.revision)
    setStale(false)
    // A new saved revision always starts a new review.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proposal?.revision])
  const mutation = useMutation({
    mutationFn: (body: ProposalDecision) =>
      post<ProposalDecisionResult>(
        `/coach/proposals/${encodeURIComponent(proposalId)}/decision`,
        body,
      ),
    onSuccess: async (response) => {
      setResult(response.data)
      await qc.invalidateQueries({ queryKey: ['v2'] })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'proposal_revision_conflict') {
        setRevisionConflict(true)
        frozen.current = null
      }
      if (
        error instanceof ApiError &&
        ['proposal_stale', 'stale_evidence', 'knowledge_unavailable'].includes(error.code)
      )
        setStale(true)
    },
  })
  const discard = useMutation({
    mutationFn: (revision: number) =>
      api<ProposalDiscardResult>(
        `/coach/proposals/${encodeURIComponent(proposalId)}?expected_revision=${revision}`,
        { method: 'DELETE' },
      ),
    onSuccess: async () => {
      setDiscarded(true)
      setConfirmDiscard(false)
      await qc.invalidateQueries({ queryKey: ['v2'] })
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'proposal_revision_conflict')
        setRevisionConflict(true)
    },
  })
  const decision = result ?? proposal?.decision_result
  const isDiscarded = discarded || proposal?.status === 'discarded'
  const terminal = Boolean(
    isDiscarded ||
    decision ||
    (proposal && !['pending', 'stale', 'invalid'].includes(proposal.status)),
  )
  const isStale =
    !isDiscarded &&
    (stale ||
      proposal?.status === 'stale' ||
      (proposal?.status === 'pending' && !proposal.is_current))
  const disabled =
    mutation.isPending ||
    discard.isPending ||
    detail.isFetching ||
    terminal ||
    isStale ||
    revisionConflict ||
    reviewedRevision !== proposal?.revision ||
    proposal?.status === 'invalid'
  const discardDisabled =
    discard.isPending ||
    mutation.isPending ||
    detail.isFetching ||
    terminal ||
    revisionConflict ||
    reviewedRevision !== proposal?.revision
  const hasChanges = Boolean(
    proposal &&
    (proposal.changes.length || proposal.block_change || proposal.anchor_changes.length),
  )
  const changes = [...(proposal?.changes ?? [])].sort((a, b) => {
    const first = proposedSession(a) ?? a.before,
      second = proposedSession(b) ?? b.before
    return (
      (first?.local_date ?? '9999').localeCompare(second?.local_date ?? '9999') ||
      (first?.slot ?? 0) - (second?.slot ?? 0)
    )
  })
  const referenceIds = [
    ...(proposal?.evidence_ids ?? []),
    ...(proposal?.policy_ids ?? []),
    ...(proposal?.recipe_ids ?? []),
  ]
  const plain = (text: string) => stripReferenceIds(text, referenceIds)
  const invalidChanges = new Set(
    changes
      .filter((change) => readStructure(change.after).invalid)
      .map((change) => change.change_id),
  )
  const invalidSelection = selected.some((id) => invalidChanges.has(id))
  const toggle = (id: string, values: string[], update: (values: string[]) => void) => {
    update(values.includes(id) ? values.filter((value) => value !== id) : [...values, id])
    mutation.reset()
    frozen.current = null
  }
  const submit = (rejectAll: boolean) => {
    if (!proposal || disabled || (!rejectAll && invalidSelection)) return
    const selection = {
      expected_head: proposal.head,
      expected_revision: proposal.revision,
      accept_change_ids: rejectAll ? [] : selected,
      reject_change_ids: proposal.changes
        .filter((change) => rejectAll || !selected.includes(change.change_id))
        .map((change) => change.change_id),
      accept_block_change: !rejectAll && block,
      accept_anchor_changes: rejectAll ? [] : anchors,
    }
    const signature = JSON.stringify(selection)
    if (!frozen.current || frozen.current.signature !== signature)
      frozen.current = { signature, body: { ...selection, idempotency_key: crypto.randomUUID() } }
    mutation.mutate(frozen.current.body)
  }
  return (
    <section className="page-content proposal-review space-y-5">
      <div className="page-heading">
        <div>
          <span className="eyebrow">COACHING</span>
          <h1>Review proposal</h1>
          <p>Choose the changes you want to apply.</p>
        </div>
        <a href="#calendar">Calendar</a>
      </div>
      <QueryState
        loading={detail.isPending}
        error={detail.error}
        stale={!!proposal}
        retry={() => {
          void detail.refetch()
        }}
      >
        {proposal && (
          <>
            {isStale && (
              <div className="notice warning" role="alert">
                This proposal is stale. Ask the coach for a fresh review; the saved changes remain
                visible below.
              </div>
            )}
            {proposal.status === 'invalid' && (
              <div className="notice warning" role="alert">
                This proposal did not pass validation.
              </div>
            )}
            {revisionConflict && (
              <div className="notice warning" role="alert">
                This proposal was edited while you reviewed it. Reload the latest revision before
                making a decision.{' '}
                <Button
                  variant="outline"
                  disabled={detail.isFetching}
                  onClick={async () => {
                    const refreshed = await detail.refetch()
                    if (refreshed.isSuccess) {
                      setRevisionConflict(false)
                      setSelected([])
                      setAnchors([])
                      setBlock(false)
                      setConfirmDiscard(false)
                      frozen.current = null
                      mutation.reset()
                      discard.reset()
                    }
                  }}
                >
                  Reload proposal
                </Button>
              </div>
            )}
            <Card className="proposal-intro">
              <div className="proposal-intro-heading">
                <h2>Plan focus</h2>
                <Badge className="status-chip">
                  Status:{' '}
                  {isDiscarded
                    ? 'discarded'
                    : (result?.status.replaceAll('_', ' ') ??
                      proposal.status.replaceAll('_', ' '))}{' '}
                  · Revision {proposal.revision}
                </Badge>
              </div>
              <CoachText text={plain(proposal.summary)} />
              <div className="proposal-rationale">
                <h3>Why this plan</h3>
                <CoachText text={plain(proposal.rationale)} />
              </div>
              {proposal.revisions.length > 0 && (
                <Disclosure className="proposal-revision-details">
                  <summary>Revision history</summary>
                  <ol>
                    {proposal.revisions.map((entry) => {
                      const removed = entry.changed_change_ids.filter(
                        (id) => !proposal.changes.some((change) => change.change_id === id),
                      )
                      return (
                        <li key={entry.revision}>
                          <strong>Revision {entry.revision}</strong> ·{' '}
                          {new Date(entry.saved_at).toLocaleString()}
                          <p>{entry.reason}</p>
                          {entry.changed_fields.length > 0 && (
                            <small>
                              Updated fields:{' '}
                              {entry.changed_fields
                                .map((field) => field.replaceAll('_', ' '))
                                .join(', ')}
                              .{' '}
                            </small>
                          )}
                          {entry.changed_change_ids.length > 0 && (
                            <small>
                              Changed sessions: {entry.changed_change_ids.length - removed.length}
                              {removed.length > 0 && `; removed sessions: ${removed.length}`}
                            </small>
                          )}
                        </li>
                      )
                    })}
                  </ol>
                </Disclosure>
              )}
              <Disclosure className="proposal-confidence-details">
                <summary>Confidence details</summary>
                <dl className="proposal-confidence">
                  {Object.entries(proposal.confidence).map(([key, value]) => (
                    <div key={key}>
                      <dt>{key}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
              </Disclosure>
            </Card>
            {proposal.exception && (
              <ExceptionCard
                exc={proposal.exception}
                sessions={head.data?.data.sessions ?? []}
                plain={plain}
              />
            )}
            {changes.length > 0 && (
              <ProposedChanges
                changes={changes}
                revision={proposal.revision}
                firstRevisionChangeIds={proposal.revisions[0]?.changed_change_ids ?? []}
                terminal={terminal}
                isDiscarded={isDiscarded}
                isStale={isStale}
                disabled={disabled}
                selected={selected}
                invalidChangeIds={invalidChanges}
                acceptedChangeIds={
                  result && frozen.current ? frozen.current.body.accept_change_ids : null
                }
                onSelect={(ids) => {
                  setSelected(ids)
                  mutation.reset()
                  frozen.current = null
                }}
                onToggle={(id) => toggle(id, selected, setSelected)}
                plain={plain}
              />
            )}
            {proposal.block_change && (
              <Card>
                <h2>Training block: {proposal.block_change.decision}</h2>
                <p>{plain(proposal.block_change.version_fields.objective ?? '')}</p>
                <p>{plain(proposal.block_change.version_fields.rationale ?? '')}</p>
                <p>
                  {proposal.block_change.version_fields.start_date} · Review{' '}
                  {proposal.block_change.version_fields.review_date ?? 'Not specified'}
                </p>
                <p>
                  Status: {proposal.block_change.version_fields.status} · Objective:{' '}
                  {proposal.block_change.version_fields.objective_status?.replaceAll('_', ' ')}
                </p>
                <p>
                  Progression:{' '}
                  {proposal.block_change.version_fields.progression_dimension?.replaceAll('_', ' ')}
                </p>
                <p>
                  Eligible sessions:{' '}
                  {proposal.block_change.version_fields.eligible_recipe_ids
                    ?.map((id) => RECIPE_LABELS[id] ?? 'Custom session')
                    .join(', ') || 'Not specified'}
                </p>
                <p>
                  Maintained qualities:{' '}
                  {proposal.block_change.version_fields.maintained_qualities?.join(', ') ||
                    'Not specified'}
                </p>
                <p>
                  Outside this block:{' '}
                  {proposal.block_change.version_fields.non_goals?.join(', ') || 'Not specified'}
                </p>
                <ul>
                  {proposal.block_change.version_fields.constraints?.map((constraint, index) => (
                    <li key={index}>
                      {constraint.kind}: {plain(constraint.text)}
                    </li>
                  ))}
                </ul>
                <p>
                  Completion indicators:{' '}
                  {proposal.block_change.version_fields.completion_indicators?.join('; ') ||
                    'Not specified'}
                </p>
                <p>
                  Earlier review:{' '}
                  {proposal.block_change.version_fields.early_review_triggers?.join('; ') ||
                    'Not specified'}
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
                      checked={block}
                      disabled={disabled}
                      onChange={(event) => {
                        setBlock(event.target.checked)
                        mutation.reset()
                        frozen.current = null
                      }}
                    />
                    Accept block change
                  </label>
                )}
              </Card>
            )}
            {proposal.anchor_changes.map((anchor) => (
              <Card key={anchor.anchor_key}>
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
                    <input
                      type="checkbox"
                      checked={anchors.includes(anchor.anchor_key)}
                      disabled={disabled}
                      onChange={() => toggle(anchor.anchor_key, anchors, setAnchors)}
                    />
                    Accept anchor {anchor.anchor_key}
                  </label>
                )}
              </Card>
            ))}
            {proposal.event_review && (
              <EventReviewCard
                review={proposal.event_review}
                operation={proposal.operation}
                plain={plain}
              />
            )}
            {(proposal.patch_resolutions?.length ?? 0) > 0 && (
              <PatchUpdates items={proposal.patch_resolutions!} plain={plain} />
            )}
            {(proposal.follow_up || proposal.escalation) && (
              <Card className="proposal-next-check">
                <h2>Next check-in</h2>
                {proposal.follow_up && <CoachText text={plain(proposal.follow_up)} />}
                {proposal.escalation && (
                  <p>Suggested next review: {proposal.escalation.replaceAll('_', ' ')}</p>
                )}
              </Card>
            )}
            {mutation.error && (
              <div className="notice warning" role="alert">
                <p>{mutation.error.message}</p>
                {mutation.error instanceof ApiError && mutation.error.fields.length > 0 && (
                  <ul>
                    {mutation.error.fields.map((field, index) => (
                      <li key={index}>
                        {field.path || field.field}: {field.message}
                      </li>
                    ))}
                  </ul>
                )}
                {!isStale && (
                  <p>Your selections are preserved. Review the issue before trying again.</p>
                )}
              </div>
            )}
            {proposal.validation_errors && proposal.validation_errors.length > 0 && (
              <ul>
                {proposal.validation_errors.map((issue, index) => (
                  <li key={index}>
                    {issue.path}: {issue.message}
                  </li>
                ))}
              </ul>
            )}
            {decision && (
              <div className="notice" role="status">
                <p>
                  {decision.calendar_version != null
                    ? `Accepted — calendar version ${decision.calendar_version}`
                    : 'Decision recorded — calendar unchanged'}
                </p>
                <p>
                  <a href="#calendar">Open calendar</a> · <a href="#home">Return home</a>
                </p>
              </div>
            )}
            {isDiscarded && (
              <div className="notice" role="status">
                Proposal discarded. No calendar changes were made. <a href="#home">Return home</a>
              </div>
            )}
            {discard.error && (
              <div className="notice warning" role="alert">
                {discard.error.message}
              </div>
            )}
            {!terminal && (
              <div className="proposal-actions">
                <Button
                  disabled={
                    disabled ||
                    invalidSelection ||
                    (hasChanges && selected.length === 0 && anchors.length === 0 && !block)
                  }
                  onClick={() => submit(false)}
                >
                  {hasChanges ? 'Accept selected' : 'Accept (no changes)'}
                </Button>
                {hasChanges && (
                  <Button variant="outline" disabled={disabled} onClick={() => submit(true)}>
                    Reject all
                  </Button>
                )}
              </div>
            )}
            {!terminal && (
              <div className="proposal-secondary" data-testid="proposal-secondary">
                <p className="fineprint">
                  Reject all keeps this proposal in history. Discard removes it without a decision.
                </p>
                {confirmDiscard ? (
                  <div className="notice warning">
                    <p>
                      Discard this proposal? It will be removed from the open list. The calendar
                      will not change.
                    </p>
                    <Button
                      variant="outline"
                      disabled={discardDisabled}
                      onClick={() => {
                        if (proposal && !discardDisabled) discard.mutate(proposal.revision)
                      }}
                    >
                      Confirm discard
                    </Button>{' '}
                    <Button
                      variant="outline"
                      disabled={discard.isPending}
                      onClick={() => setConfirmDiscard(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="link"
                    disabled={discardDisabled}
                    onClick={() => setConfirmDiscard(true)}
                  >
                    Discard proposal
                  </Button>
                )}
              </div>
            )}
            <p>
              <a href="#calendar">Calendar history and protected undo</a>
            </p>
          </>
        )}
      </QueryState>
    </section>
  )
}
