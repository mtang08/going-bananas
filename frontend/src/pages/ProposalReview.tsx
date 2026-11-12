import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, dateLabel, flattenStructure, fmtDuration, formatStep, post, type Profile } from '../api'
import type { ProposalDecision, ProposalDecisionResult, ProposalDetail, ProposalSession } from '../api/types/coach'
import { QueryState } from '../components/QueryState'

function SessionView({ value, empty }: { value:ProposalSession|null; empty:string }) {
  if (!value) return <p className="muted-text">{empty}</p>
  return <div className="proposal-session">
    {value.local_date && <strong>{dateLabel(value.local_date)} · {value.kind}</strong>}
    {value.intent && <p>{value.intent}</p>}
    {'planned_duration_s' in value && <p>Duration: {value.planned_duration_s == null ? 'Not specified' : fmtDuration(value.planned_duration_s)}</p>}
    {'planned_distance_m' in value && <p>Distance: {value.planned_distance_m == null ? 'Not specified' : `${(value.planned_distance_m/1000).toFixed(2)} km`}</p>}
    {value.notes && <p>{value.notes}</p>}
    {value.legacy_unstructured ? <p>Imported prescription · structured comparison unavailable</p> :
      value.structure && <ol>{flattenStructure(value.structure).map(step => <li key={`${step.step_path}:${step.repeat_index}`}>{formatStep(step,'km')}</li>)}</ol>}
  </div>
}

export function ProposalReview({ proposalId }: { proposalId:string }) {
  return <ReviewForm key={proposalId} proposalId={proposalId}/>
}

function ReviewForm({ proposalId }: { proposalId:string }) {
  const qc = useQueryClient()
  const detail = useQuery({ queryKey:['v2','proposals',proposalId], queryFn:()=>api<ProposalDetail>(`/coach/proposals/${encodeURIComponent(proposalId)}`) })
  const profile = useQuery({ queryKey:['profile'], queryFn:()=>api<Profile>('/profile') })
  const [selected, setSelected] = useState<string[]>([])
  const [anchors, setAnchors] = useState<string[]>([])
  const [block, setBlock] = useState(false)
  const [result, setResult] = useState<ProposalDecisionResult|null>(null)
  const [stale, setStale] = useState(false)
  const frozen = useRef<{signature:string;body:ProposalDecision}|null>(null)
  const proposal = detail.data?.data
  const mutation = useMutation({
    mutationFn:(body:ProposalDecision)=>post<ProposalDecisionResult>(`/coach/proposals/${encodeURIComponent(proposalId)}/decision`,body),
    onSuccess: async response => {
      setResult(response.data)
      await qc.invalidateQueries({queryKey:['v2']})
    },
    onError: error => {
      if (error instanceof ApiError && ['proposal_stale','stale_evidence','knowledge_unavailable'].includes(error.code)) setStale(true)
    },
  })
  const authorityError = mutation.error instanceof ApiError && ['planning_not_active','legacy_write_disabled'].includes(mutation.error.code)
  const active = profile.data?.data.planning_authority === 'calendar' && !authorityError
  const decision = result ?? proposal?.decision_result
  const terminal = Boolean(decision || (proposal && !['pending','stale','invalid'].includes(proposal.status)))
  const isStale = stale || proposal?.status === 'stale' || (proposal?.status === 'pending' && !proposal.is_current)
  const disabled = mutation.isPending || terminal || !active || isStale || proposal?.status === 'invalid'
  const hasChanges = Boolean(proposal && (proposal.changes.length || proposal.block_change || proposal.anchor_changes.length))
  const toggle = (id:string, values:string[], update:(values:string[])=>void) => {
    update(values.includes(id)?values.filter(value=>value!==id):[...values,id]); mutation.reset(); frozen.current=null
  }
  const submit = (rejectAll:boolean) => {
    if (!proposal || disabled) return
    const selection = {expected_head:proposal.head, accept_change_ids:rejectAll?[]:selected,
      reject_change_ids:proposal.changes.filter(change=>rejectAll || !selected.includes(change.change_id)).map(change=>change.change_id),
      accept_block_change:!rejectAll && block, accept_anchor_changes:rejectAll?[]:anchors}
    const signature = JSON.stringify(selection)
    if (!frozen.current || frozen.current.signature!==signature) frozen.current={signature,body:{...selection,idempotency_key:crypto.randomUUID()}}
    mutation.mutate(frozen.current.body)
  }
  return <section className="page-content proposal-review">
    <div className="page-heading"><div><span className="eyebrow">COACHING</span><h1>Review proposal</h1><p>Choose the changes you want to apply.</p></div><a href="#calendar">Calendar</a></div>
    <QueryState loading={detail.isPending || profile.isPending} error={detail.error || profile.error} stale={!!proposal} retry={()=>{void detail.refetch();void profile.refetch()}}>
      {proposal && <>
        {(profile.data?.data.planning_authority === 'legacy' || authorityError) && <div className="notice warning" role="alert">Planning upgrade required</div>}
        {isStale && <div className="notice warning" role="alert">This proposal is stale. Ask the coach for a fresh review; the saved changes remain visible below.</div>}
        {proposal.status==='invalid' && <div className="notice warning" role="alert">This proposal did not pass validation.</div>}
        <div className="panel"><h2>{proposal.summary}</h2><p>{proposal.rationale}</p>
          <p>Status: {result?.status.replaceAll('_',' ') ?? proposal.status.replaceAll('_',' ')}</p>
          <dl className="proposal-confidence">{Object.entries(proposal.confidence).map(([key,value])=><div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
          {proposal.follow_up && <p>Follow-up: {proposal.follow_up}</p>}
          {proposal.escalation && <p>Suggested next review: {proposal.escalation.replaceAll('_',' ')}</p>}
          <details><summary>Evidence and policies</summary><p>{[...proposal.evidence_ids,...proposal.policy_ids,...proposal.recipe_ids].join(' · ') || 'No references supplied'}</p></details>
        </div>
        {proposal.changes.map(change=><article className="panel proposal-change" key={change.change_id}>
          <h2>{change.change_id}: {change.op}</h2><p>{change.reason}</p>
          {change.material_flags.length>0 && <p>Review carefully: {change.material_flags.map(flag=>flag.replaceAll('_',' ')).join(', ')}</p>}
          <div className="proposal-diff"><div><h3>Before</h3><SessionView value={change.before} empty="New session"/></div><div><h3>Proposed</h3><SessionView value={change.after} empty="Remove session"/></div></div>
          {isStale && <details><summary>Current session</summary><SessionView value={change.current} empty="No current session"/></details>}
          {terminal ? <p>Decision: {result && frozen.current ? (frozen.current.body.accept_change_ids.includes(change.change_id)?'accepted':'rejected') : change.decision}</p> : <label className="proposal-choice"><input type="checkbox" aria-label={`Accept change ${change.change_id}`} checked={selected.includes(change.change_id)} disabled={disabled} onChange={()=>toggle(change.change_id,selected,setSelected)}/>Accept change {change.change_id}</label>}
        </article>)}
        {proposal.block_change && <div className="panel"><h2>Training block: {proposal.block_change.decision}</h2>
          <p>{proposal.block_change.version_fields.objective}</p><p>{proposal.block_change.version_fields.rationale}</p>
          <p>{proposal.block_change.version_fields.start_date} · Review {proposal.block_change.version_fields.review_date ?? 'Not specified'}</p>
          <p>Status: {proposal.block_change.version_fields.status} · Objective: {proposal.block_change.version_fields.objective_status?.replaceAll('_',' ')}</p>
          <p>Progression: {proposal.block_change.version_fields.progression_dimension?.replaceAll('_',' ')}</p>
          <p>Eligible sessions: {proposal.block_change.version_fields.eligible_recipe_ids?.join(', ') || 'Not specified'}</p>
          <p>Maintained qualities: {proposal.block_change.version_fields.maintained_qualities?.join(', ') || 'Not specified'}</p>
          <p>Outside this block: {proposal.block_change.version_fields.non_goals?.join(', ') || 'Not specified'}</p>
          <ul>{proposal.block_change.version_fields.constraints?.map((constraint,index)=><li key={index}>{constraint.kind}: {constraint.text}</li>)}</ul>
          <p>Completion indicators: {proposal.block_change.version_fields.completion_indicators?.join('; ') || 'Not specified'}</p>
          <p>Earlier review: {proposal.block_change.version_fields.early_review_triggers?.join('; ') || 'Not specified'}</p>
          {terminal ? <p>Block decision: {decision ? decision.block_version_id ? 'accepted' : 'rejected' : 'Unavailable'}</p> : <label className="proposal-choice"><input type="checkbox" checked={block} disabled={disabled} onChange={event=>{setBlock(event.target.checked);mutation.reset();frozen.current=null}}/>Accept block change</label>}
        </div>}
        {proposal.anchor_changes.map(anchor=><div className="panel" key={anchor.anchor_key}><h2>{anchor.kind.replaceAll('_',' ')}</h2>
          <p>{anchor.value_low}{anchor.value_high!=null?`–${anchor.value_high}`:''} {anchor.unit} · {anchor.protocol.replaceAll('_',' ')} · {anchor.confidence} confidence</p>
          <p>Calibrated {anchor.calibrated_at.slice(0,10)}{anchor.supersedes_key?` · Replaces ${anchor.supersedes_key}`:''}</p>
          {terminal ? <p>Anchor decision: {decision ? decision.anchor_keys.includes(anchor.anchor_key) ? 'accepted' : 'rejected' : 'Unavailable'}</p> : <label className="proposal-choice"><input type="checkbox" checked={anchors.includes(anchor.anchor_key)} disabled={disabled} onChange={()=>toggle(anchor.anchor_key,anchors,setAnchors)}/>Accept anchor {anchor.anchor_key}</label>}
        </div>)}
        {mutation.error && <div className="notice warning" role="alert"><p>{mutation.error.message}</p>
          {mutation.error instanceof ApiError && mutation.error.fields.length>0 && <ul>{mutation.error.fields.map((field,index)=><li key={index}>{field.path || field.field}: {field.message}</li>)}</ul>}
          {!isStale && !authorityError && <p>Your selections are preserved. Review the issue before trying again.</p>}
        </div>}
        {proposal.validation_errors && proposal.validation_errors.length>0 && <ul>{proposal.validation_errors.map((issue,index)=><li key={index}>{issue.path}: {issue.message}</li>)}</ul>}
        {decision && <div className="notice" role="status">{decision.calendar_version!=null?`Accepted — calendar version ${decision.calendar_version}`:'Decision recorded — calendar unchanged'}</div>}
        {!terminal && <div className="proposal-actions"><button className="button primary" disabled={disabled || (hasChanges && selected.length===0 && anchors.length===0 && !block)} onClick={()=>submit(false)}>{hasChanges?'Accept selected':'Accept (no changes)'}</button>
          {hasChanges && <button className="button" disabled={disabled} onClick={()=>submit(true)}>Reject all</button>}</div>}
        <p><a href="#coach">Legacy coaching history</a> · <a href="#calendar">Calendar history and protected undo</a></p>
      </>}
    </QueryState>
  </section>
}
