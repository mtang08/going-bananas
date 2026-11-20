import { Button, Card } from '../components/ui'
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { CalendarView } from '../api/types/calendar'
import { ApiError, api, post } from '../api/client'
import { invalidateKeys, qk } from '../api/queryKeys'
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
import { ProposalIntro } from './proposal/ProposalIntro'
import { AnchorChangeCard, BlockChangeCard } from './proposal/ChangeCards'
import { DecisionActions } from './proposal/DecisionActions'

export function ProposalReview({ proposalId }: { proposalId: string }) {
  return <ReviewForm key={proposalId} proposalId={proposalId} />
}

function ReviewForm({ proposalId }: { proposalId: string }) {
  const qc = useQueryClient()
  const detail = useQuery({
    queryKey: qk.proposal(proposalId),
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
  const head = useQuery({
    queryKey: qk.calendarView('head'),
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
    onSuccess: (response) => {
      setResult(response.data)
      invalidateKeys(qc, [
        qk.proposals,
        qk.calendar,
        qk.metrics,
        qk.prompts,
        qk.exceptions,
        qk.blocks,
        qk.anchors,
      ])
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
    onSuccess: () => {
      setDiscarded(true)
      setConfirmDiscard(false)
      invalidateKeys(qc, [qk.proposals])
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
            <ProposalIntro
              proposal={proposal}
              statusLabel={
                isDiscarded ? 'discarded' : (result?.status ?? proposal.status).replaceAll('_', ' ')
              }
              plain={plain}
            />
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
                today={head.data?.data.today ?? null}
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
              <BlockChangeCard
                change={proposal.block_change}
                terminal={terminal}
                isDiscarded={isDiscarded}
                decision={decision}
                checked={block}
                disabled={disabled}
                plain={plain}
                onChange={(value) => {
                  setBlock(value)
                  mutation.reset()
                  frozen.current = null
                }}
              />
            )}
            {proposal.anchor_changes.map((anchor) => (
              <AnchorChangeCard
                key={anchor.anchor_key}
                anchor={anchor}
                terminal={terminal}
                isDiscarded={isDiscarded}
                decision={decision}
                checked={anchors.includes(anchor.anchor_key)}
                disabled={disabled}
                onToggle={() => toggle(anchor.anchor_key, anchors, setAnchors)}
              />
            ))}
            {proposal.event_review && (
              <EventReviewCard
                review={proposal.event_review}
                operation={proposal.operation}
                plain={plain}
              />
            )}
            {proposal.patch_resolutions.length > 0 && (
              <PatchUpdates items={proposal.patch_resolutions} plain={plain} />
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
              <DecisionActions
                hasChanges={hasChanges}
                acceptDisabled={
                  disabled ||
                  invalidSelection ||
                  (hasChanges && selected.length === 0 && anchors.length === 0 && !block)
                }
                rejectDisabled={disabled}
                discardDisabled={discardDisabled}
                discardPending={discard.isPending}
                confirmDiscard={confirmDiscard}
                onAccept={() => submit(false)}
                onRejectAll={() => submit(true)}
                onAskDiscard={() => setConfirmDiscard(true)}
                onConfirmDiscard={() => discard.mutate(proposal.revision)}
                onCancelDiscard={() => setConfirmDiscard(false)}
              />
            )}
            <p>
              <a href="#calendar">Plan versions and protected undo</a>
            </p>
          </>
        )}
      </QueryState>
    </section>
  )
}
