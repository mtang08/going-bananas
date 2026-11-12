import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, dateLabel, post, type AgentRevisions, type PlanSession, type Prescription } from './api'

export function plannedSessionLabel(session: PlanSession): string {
  const target = typeof session.target === 'object' ? session.target : null
  if (session.kind === 'strength') return 'Full-body strength'
  if (session.kind === 'mobility') return target?.optional ? 'Mobility · optional' : 'Gym mobility'
  if (target?.intent === 'rest') return 'Rest · running slot'
  return target?.intent ? `${target.intent} run` : `Dated ${session.kind}`
}

export function prescriptionLabel(target: PlanSession['target']): string {
  if (typeof target === 'string') return target
  if (!target) return ''
  return [target.duration_minutes != null ? `${target.duration_minutes} min` : null, target.distance_km != null ? `${target.distance_km} km` : null, target.prescription].filter(Boolean).join(' · ')
}

export function SessionPrescription({target, compact = false}: {target: PlanSession['target']; compact?: boolean}) {
  if (!target) return null
  if (typeof target === 'string') return <span className="prescription">{target}</span>
  const label = prescriptionLabel(target)
  if (compact) return <span className="prescription">{label}{target.intensity && <span>{target.intensity}</span>}</span>
  return <div className="session-prescription">
    {target.purpose && <p><strong>Purpose:</strong> {target.purpose}</p>}
    {label && <p><strong>Session:</strong> {label}</p>}
    {target.intensity && <p><strong>Effort:</strong> {target.intensity}</p>}
    {!!target.steps?.length && <ul>{target.steps.map((step, i) => <li key={i}>{step}</li>)}</ul>}
    {target.reason && <p><strong>Why:</strong> {target.reason}</p>}
    {target.locked && <small>Locked session · protected from automatic changes</small>}
    {target.provenance === 'codex_skill.v1' && <small>Saved by the Codex research coach</small>}
  </div>
}

function diffLabel(value: Prescription | null) {
  return value ? [value.intent, prescriptionLabel(value), value.intensity].filter(Boolean).join(' · ') || 'Dated session' : 'No dated prescription'
}

export function AgentPlanHistory({readOnly=false}: {readOnly?:boolean}) {
  const qc = useQueryClient()
  const [selected, setSelected] = useState<{id: string; expectedRevision: string | null} | null>(null)
  const [reason, setReason] = useState('')
  const history = useQuery({queryKey: ['agent-revisions'], queryFn: () => api<AgentRevisions>('/coach/agent/revisions'), refetchInterval: 15000})
  const currentRevision = history.data?.data.current_revision_id
  useEffect(() => {if (currentRevision) qc.invalidateQueries({queryKey: ['plans']})}, [currentRevision, qc])
  const rollback = useMutation({
    mutationFn: (selection: {id: string; expectedRevision: string | null}) => post(`/coach/agent/revisions/${selection.id}/rollback`, {expected_revision_id: selection.expectedRevision, reason}),
    onSuccess: () => {
      setSelected(null); setReason('')
      for (const key of ['agent-revisions', 'plans', 'coach']) qc.invalidateQueries({queryKey: [key]})
    },
  })
  const data = history.data?.data
  return <div className="panel agent-history"><div className="panel-head"><div><h2>Coach plan history</h2><p>Saved running prescriptions and daily decisions · Codex research coach</p></div><button className="text-button" disabled={history.isFetching} onClick={() => {history.refetch(); qc.invalidateQueries({queryKey: ['plans']})}}>Refresh plans</button></div>
    {history.isPending && <p role="status">Loading coach decisions…</p>}
    {history.error && <p className="error-text" role="alert">Could not load coach decisions: {history.error.message}</p>}
    {data && !data.items.length && <p>No research-coach plan saved yet. Invoke the coach in Codex to plan the next 14 days.</p>}
    {data?.items.map(item => <details className="agent-revision" key={item.id}>
      <summary>{dateLabel(item.as_of)} · {item.workflow === 'weekly' ? '14-day plan' : item.workflow === 'daily' ? 'Daily decision' : 'Rollback'} · {item.summary}{item.id === data.current_revision_id ? ' · Current' : ''}</summary>
      <p>{item.rationale}</p>
      {item.review && <details><summary>Training review & follow-up</summary><p><strong>Weekly strategy:</strong> {item.review.weekly_strategy}</p><p><strong>Actual vs planned:</strong> {item.review.actual_vs_plan}</p><p><strong>Progression:</strong> {item.review.progression}</p><p><strong>Recovery:</strong> {item.review.recovery}</p><p><strong>Symptoms:</strong> {item.review.symptoms}</p><p><strong>Strength:</strong> {item.review.strength}</p>{item.review.uncertainty.length > 0 && <p><strong>Unknowns:</strong> {item.review.uncertainty.join(' ')}</p>}{item.review.follow_up.length > 0 && <p><strong>Follow-up:</strong> {item.review.follow_up.join(' ')}</p>}</details>}
      {!!item.warnings?.length && <div className="notice warning">{item.warnings.join(' ')}</div>}
      {!!item.diff.length && <ul className="coach-lines">{item.diff.map((change, i) => <li key={i}><strong>{dateLabel(change.date)} · {change.kind}</strong><div>Before: {diffLabel(change.before)}</div><div>After: {diffLabel(change.after)}</div><div>{change.reason}</div></li>)}</ul>}
      {!item.diff.length && <p>Existing prescription confirmed; no session changes.</p>}
      {item.source_ids.length > 0 && <p className="fineprint">Research records: {item.source_ids.join(', ')}</p>}
      <p className="fineprint">Saved {new Date(item.created_at).toLocaleString()} · {item.engine || 'codex_skill.v1'}</p>
      {!readOnly && item.id === (data.revertible_revision_id === undefined ? data.current_revision_id : data.revertible_revision_id) && item.diff.length > 0 && <button className="button" disabled={rollback.isPending} onClick={() => {setSelected({id: item.id, expectedRevision: data.current_revision_id}); setReason(''); rollback.reset()}}>Undo this revision</button>}
      {!readOnly && selected?.id === item.id && <div className="link-box"><p>Restore the previous future prescription. Completed and locked sessions remain protected. This creates a new revision.</p>{selected.expectedRevision !== data.current_revision_id && <p role="alert" className="error-text">The plan changed. Review the latest decisions and reopen undo before continuing.</p>}<label className="field">Reason for undoing<textarea value={reason} onChange={e => setReason(e.target.value)} minLength={5} maxLength={2000}/></label><div className="coach-actions"><button className="button" disabled={rollback.isPending || reason.trim().length < 5 || selected.expectedRevision !== data.current_revision_id} onClick={() => rollback.mutate(selected)}>Confirm rollback</button><button className="text-button" onClick={() => setSelected(null)}>Cancel</button></div>{rollback.error && <p role="alert" className="error-text">{rollback.error.message}</p>}</div>}
    </details>)}
  </div>
}
