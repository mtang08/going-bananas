import {
  Badge,
  Button,
  Card,
  Disclosure,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui'
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  api,
  dateLabel,
  flattenStructure,
  fmtDuration,
  formatStep,
  post,
  RECIPE_LABELS,
  type Profile,
} from '../api'
import type {
  ProposalDecision,
  ProposalDecisionResult,
  ProposalDetail,
  ProposalDiscardResult,
  ProposalSession,
  ProposalChange,
} from '../api/types/coach'
import { QueryState } from '../components/QueryState'

function readStructure(value: ProposalSession | null) {
  if (!value?.structure || value.legacy_unstructured) return { steps: [], invalid: false }
  try {
    return { steps: flattenStructure(value.structure), invalid: false }
  } catch {
    return { steps: [], invalid: true }
  }
}

const ACTION_LABELS = { add: 'Add', modify: 'Update', move: 'Move', delete: 'Remove' }
function proposedSession(change: ProposalChange): ProposalSession | null {
  return change.op === 'delete' ? null : { ...change.before, ...change.after }
}
function sessionName(value: ProposalSession | null): string {
  if (!value) return 'Session'
  if (value.recipe_id && RECIPE_LABELS[value.recipe_id]) return RECIPE_LABELS[value.recipe_id]
  return {
    run: 'Run',
    strength: 'Strength',
    cross: 'Cross-training',
    rest: 'Rest',
    mobility: 'Mobility',
  }[value.kind ?? 'run']
}
function sessionDate(value: ProposalSession | null): string {
  return value?.local_date
    ? dateLabel(value.local_date, { weekday: 'short', month: 'short', day: 'numeric' })
    : 'Date not specified'
}

// Coach copy supports plain paragraphs and dash bullets, without interpreting HTML.
function CoachText({ text }: { text: string }) {
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

function SessionView({
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

export function ProposalReview({ proposalId }: { proposalId: string }) {
  return <ReviewForm key={proposalId} proposalId={proposalId} />
}

function ReviewForm({ proposalId }: { proposalId: string }) {
  const qc = useQueryClient()
  const detail = useQuery({
    queryKey: ['v2', 'proposals', proposalId],
    queryFn: () => api<ProposalDetail>(`/coach/proposals/${encodeURIComponent(proposalId)}`),
  })
  const profile = useQuery({ queryKey: ['profile'], queryFn: () => api<Profile>('/profile') })
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
  const authorityError =
    mutation.error instanceof ApiError &&
    ['planning_not_active', 'legacy_write_disabled'].includes(mutation.error.code)
  const active = profile.data?.data.planning_authority === 'calendar' && !authorityError
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
    !active ||
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
  const plain = (text: string) => {
    let result = text
    for (const id of referenceIds) {
      const escaped = id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      result = result.replace(new RegExp(`\\b${escaped}\\b`, 'g'), '')
    }
    return result
      .replace(/\[\s*[,;·\s]*\]/g, '')
      .replace(/\(\s*[,;·\s]*\)/g, '')
      .replace(/[ \t]+([.,;:])/g, '$1')
      .replace(/[ \t]{2,}/g, ' ')
      .trim()
  }
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
        loading={detail.isPending || profile.isPending}
        error={detail.error || profile.error}
        stale={!!proposal}
        retry={() => {
          void detail.refetch()
          void profile.refetch()
        }}
      >
        {proposal && (
          <>
            {(profile.data?.data.planning_authority === 'legacy' || authorityError) && (
              <div className="notice warning" role="alert">
                Planning upgrade required
              </div>
            )}
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
            {changes.length > 0 && (
              <>
                <Card className="proposal-plan">
                  <h2>Proposed plan changes</h2>
                  <p>
                    {terminal
                      ? 'These are the changes saved with this proposal.'
                      : 'Review the sessions below. Only changed sessions are shown; unchecked changes will be rejected.'}
                  </p>
                  <div
                    className="table-scroll"
                    role="region"
                    aria-label="Proposed plan changes"
                    tabIndex={0}
                  >
                    <Table
                      className="proposal-table [&_td]:align-top [&_td]:whitespace-normal [&_th]:align-top [&_th]:whitespace-normal"
                      aria-label="Proposed plan changes"
                    >
                      <TableHeader>
                        <TableRow>
                          <TableHead scope="col">#</TableHead>
                          <TableHead scope="col">Day</TableHead>
                          <TableHead scope="col">Session</TableHead>
                          <TableHead scope="col">Workout</TableHead>
                          <TableHead scope="col">{terminal ? 'Decision' : 'Accept'}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {changes.map((change, index) => {
                          const after = proposedSession(change),
                            session = after ?? change.before
                          return (
                            <TableRow
                              key={change.change_id}
                              className={
                                proposal.revision > 1 &&
                                proposal.revisions[0]?.changed_change_ids.includes(change.change_id)
                                  ? 'proposal-revised-row'
                                  : undefined
                              }
                            >
                              <TableHead scope="row">
                                <a
                                  href={`#proposal-reason-${index + 1}`}
                                  onClick={(event) => {
                                    event.preventDefault()
                                    const reason = document.getElementById(
                                      `proposal-reason-${index + 1}`,
                                    )
                                    const disclosure = reason?.closest<HTMLDetailsElement>(
                                      'details.proposal-reasons',
                                    )
                                    if (disclosure) disclosure.open = true
                                    reason?.scrollIntoView({ behavior: 'smooth' })
                                  }}
                                  aria-label={`Read reason ${index + 1}`}
                                >
                                  {index + 1}
                                </a>
                              </TableHead>
                              <TableCell>
                                {sessionDate(session)}
                                {change.before?.local_date &&
                                  after?.local_date &&
                                  change.before.local_date !== after.local_date && (
                                    <small>Previously {sessionDate(change.before)}</small>
                                  )}
                              </TableCell>
                              <TableCell>
                                <strong>{sessionName(session)}</strong>
                                <Badge className="status-chip">{ACTION_LABELS[change.op]}</Badge>
                                {change.material_flags.length > 0 && (
                                  <small>
                                    Review carefully:{' '}
                                    {change.material_flags
                                      .map((flag) => flag.replaceAll('_', ' '))
                                      .join(', ')}
                                  </small>
                                )}
                              </TableCell>
                              <TableCell>
                                {after ? (
                                  <SessionView value={after} empty="" compact plain={plain} />
                                ) : (
                                  <>
                                    <p>Remove this session from the plan.</p>
                                    <SessionView
                                      value={change.before}
                                      empty=""
                                      compact
                                      plain={plain}
                                    />
                                  </>
                                )}
                              </TableCell>
                              <TableCell>
                                {isDiscarded ? (
                                  <span>Not applied</span>
                                ) : terminal ? (
                                  <span>
                                    Decision:{' '}
                                    {result && frozen.current
                                      ? frozen.current.body.accept_change_ids.includes(
                                          change.change_id,
                                        )
                                        ? 'accepted'
                                        : 'rejected'
                                      : change.decision}
                                  </span>
                                ) : (
                                  <label className="proposal-choice">
                                    <input
                                      type="checkbox"
                                      aria-label={`Accept change ${change.change_id}`}
                                      checked={selected.includes(change.change_id)}
                                      disabled={disabled || invalidChanges.has(change.change_id)}
                                      onChange={() =>
                                        toggle(change.change_id, selected, setSelected)
                                      }
                                    />
                                    <span className="sr-only">Include session {index + 1}</span>
                                  </label>
                                )}
                              </TableCell>
                            </TableRow>
                          )
                        })}
                      </TableBody>
                    </Table>
                  </div>
                </Card>
                <Disclosure variant="card" className="proposal-reasons">
                  <summary>Session reasons and comparisons</summary>
                  <ol>
                    {changes.map((change, index) => (
                      <li id={`proposal-reason-${index + 1}`} key={change.change_id}>
                        <h3>
                          {sessionDate(proposedSession(change) ?? change.before)} ·{' '}
                          {sessionName(proposedSession(change) ?? change.before)}
                        </h3>
                        <CoachText text={plain(change.reason)} />
                        {(change.before || isStale) && (
                          <Disclosure>
                            <summary>
                              Compare with {isStale ? 'saved and current plan' : 'previous plan'}
                            </summary>
                            <div className="proposal-diff">
                              <div>
                                <h3>Before</h3>
                                <SessionView
                                  value={change.before}
                                  empty="New session"
                                  plain={plain}
                                />
                              </div>
                              {isStale && (
                                <div>
                                  <h3>Current session</h3>
                                  <SessionView
                                    value={change.current}
                                    empty="No current session"
                                    plain={plain}
                                  />
                                </div>
                              )}
                            </div>
                          </Disclosure>
                        )}
                      </li>
                    ))}
                  </ol>
                </Disclosure>
              </>
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
                {!isStale && !authorityError && (
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
                {decision.calendar_version != null
                  ? `Accepted — calendar version ${decision.calendar_version}`
                  : 'Decision recorded — calendar unchanged'}
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
              <div className="proposal-actions">
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
                    variant="outline"
                    disabled={discardDisabled}
                    onClick={() => setConfirmDiscard(true)}
                  >
                    Discard proposal
                  </Button>
                )}
              </div>
            )}
            <p>
              <a href="#coach">Legacy coaching history</a> ·{' '}
              <a href="#calendar">Calendar history and protected undo</a>
            </p>
          </>
        )}
      </QueryState>
    </section>
  )
}
