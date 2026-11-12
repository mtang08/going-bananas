import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addDays, api, dateLabel, DECISION_LABELS, fetchDailyGuidance, flattenStructure,
  fmtDistance, fmtDuration, formatStep, invalidateKeys, MARKER_LABELS, pageHref,
  post, qk, sessionMarker, sessionTitle, statusText,
  type Activity, type BlockVersion, type CalendarView, type CheckinRequest,
  type PromptList, type SessionState, type Unit,
} from '../api'
import { QueryState } from '../components/QueryState'

export function Home({ unit, onCheckin }: { unit: Unit; onCheckin: (req: CheckinRequest) => void }) {
  const qc = useQueryClient()
  const calendar = useQuery({ queryKey: qk.calendarView('head'), queryFn: () => api<CalendarView>('/calendar') })
  const prompts = useQuery({ queryKey: qk.prompts, queryFn: () => api<PromptList>('/prompts') })
  const guidance = useQuery({ queryKey: qk.coachDaily, queryFn: fetchDailyGuidance })
  const block = useQuery({ queryKey: qk.blocksActive, queryFn: () => api<BlockVersion | null>('/blocks/active') })
  const open = prompts.data?.data.items.filter(p => p.status === 'open') ?? []
  const ids = [...new Set(open.filter(p => p.kind === 'rpe' || p.kind === 'delayed_symptom').flatMap(p => p.activity_id ? [p.activity_id] : []))]
  const activities = useQueries({ queries: ids.map(id => ({ queryKey: qk.activity(id), queryFn: () => api<Activity>(`/activities/${encodeURIComponent(id)}`) })) })
  const dismiss = useMutation({ mutationFn: (id: string) => post<unknown>(`/prompts/${encodeURIComponent(id)}/dismiss`, {}), onSuccess: () => invalidateKeys(qc, [qk.prompts]) })
  const view = calendar.data?.data
  const today = view?.today
  const sessionsOn = (day: string) => (view?.sessions ?? []).filter(s => s.local_date === day).sort((a, b) => a.slot - b.slot)
  const last = view?.last_planned_date ?? view?.sessions.map(s => s.local_date).sort().at(-1)
  const title = (s: SessionState) => s.legacy_unstructured ? 'Imported run' : sessionTitle(s)
  const g = guidance.data
  const b = block.data?.data

  return <section className="page-content home-page">
    <div className="page-heading"><div><span className="eyebrow">TODAY</span>
      <h1>{today ? dateLabel(today, { weekday: 'long', month: 'long', day: 'numeric' }) : 'Today'}</h1>
      <p>Planned training, open prompts, and the next two weeks.</p></div>
      <button className="button primary" onClick={() => onCheckin({ kind: 'exception', prompt: null, activityId: null })}>Record check-in</button>
    </div>
    <QueryState loading={calendar.isPending} error={calendar.error} stale={!!calendar.data} retry={() => { void calendar.refetch() }}>
      {view?.head === 0 && <div className="notice warning"><strong>No calendar yet.</strong> Finish setup to fill the next 14 days. <a href={pageHref.settings}>Open setup</a></div>}
      {view && view.head !== 0 && today && <>
        {(!last || last <= addDays(today, 6)) && <div className="notice warning" role="status" data-testid="plan-end-banner">{last ? `Plan ends on ${dateLabel(last)} — run the weekly review` : 'No planned sessions — run the weekly review'}</div>}
        <div className="panel today-card" data-testid="today-card"><h2>Today's plan</h2>
          {sessionsOn(today).length === 0 && <p>No session</p>}
          {sessionsOn(today).map(s => <div className="planned-session" key={s.session_uid}>
            <strong>{title(s)}</strong><p>{s.intent}</p>
            {s.planned_duration_s !== null && <span>{fmtDuration(s.planned_duration_s)}</span>}{' '}
            {s.planned_distance_m !== null && <span>{fmtDistance(s.planned_distance_m, unit)}</span>}
            {s.structure && <ol>{flattenStructure(s.structure).map(step => <li key={`${step.step_path}:${step.repeat_index ?? 'single'}`}>{formatStep(step, unit)}</li>)}</ol>}
            <span className="status-chip">{s.certainty === 'committed' ? 'Committed' : 'Provisional'}</span>
            {s.legacy_unstructured ? <><p>{s.notes}</p><small>Structured comparison unavailable</small></> : s.recipe_id === null && s.kind === 'run' && !s.custom && <small>Effort-based until the first review picks a session.</small>}
          </div>)}
        </div>
      </>}
    </QueryState>
    <div className="panel"><h2>Prompts</h2>
      <QueryState loading={prompts.isPending} error={prompts.error} stale={!!prompts.data} retry={() => { void prompts.refetch() }}>
        {open.length === 0 && <p className="muted-text">No open prompts.</p>}
        {open.map(prompt => {
          const activity = activities[ids.indexOf(prompt.activity_id ?? '')]?.data?.data
          const session = view?.sessions.find(s => s.session_uid === prompt.session_uid)
          return <div className="prompt-item" data-testid="prompt-item" data-kind={prompt.kind} key={prompt.id}>
            {prompt.kind === 'rpe' && <><strong>Rate your run{activity ? ` on ${dateLabel(activity.local_date)} · ${fmtDistance(activity.distance_m, unit)}` : ''}</strong><p>How hard was the entire session?</p>
              <button className="button" onClick={() => onCheckin({ kind: 'post_run', prompt, activityId: prompt.activity_id })}>Add RPE</button></>}
            {prompt.kind === 'delayed_symptom' && <><strong>Delayed-response check{activity ? ` for your run on ${dateLabel(activity.local_date)}` : ''}</strong><p>Any pain or gait change since this run?</p>
              <button className="button" onClick={() => onCheckin({ kind: 'delayed_followup', prompt, activityId: prompt.activity_id })}>Answer check</button></>}
            {prompt.kind === 'unmatched_session' && <><strong>A run needs matching to a planned session</strong><p>Pick the session on the Calendar page.</p><a href={pageHref.calendar}>Open calendar</a></>}
            {prompt.kind === 'missing_activity' && <><strong>No activity found for {session ? `${title(session)} on ${dateLabel(session.local_date)}` : 'a planned session'}</strong><p>Mark it skipped, moved, or not recorded on the Calendar page.</p><a href={pageHref.calendar}>Open calendar</a></>}
            <button className="text-button" disabled={dismiss.isPending} onClick={() => dismiss.mutate(prompt.id)}>Dismiss</button>
          </div>
        })}
        {dismiss.error && <p className="error-text" role="alert">{dismiss.error.message}</p>}
      </QueryState>
    </div>
    <div className="panel"><h2>Daily guidance</h2>
      <QueryState loading={guidance.isPending} error={guidance.error} stale={guidance.data !== undefined} retry={() => { void guidance.refetch() }}>
        {g === null && <p>No guidance today. Guidance appears after you record a check-in; without one, the planned session stands.</p>}
        {g && <><span className={`status-chip ${g.decision}`}>{DECISION_LABELS[g.decision]}</span><p>{g.rationale}</p>
          {g.coach_review_suggested && <div className="notice warning">Coach review suggested. Run the running-coach skill (daily review) before training.</div>}
          {g.missing_inputs.length > 0 && <small>Missing inputs: {g.missing_inputs.map(statusText).join(', ')}</small>}</>}
      </QueryState>
    </div>
    <div className="panel"><h2>Training block</h2>
      <QueryState loading={block.isPending} error={block.error} stale={!!block.data} retry={() => { void block.refetch() }}>
        {b === null && <p>No active block. The calendar runs without one until the first block review.</p>}
        {b && <><p>{b.objective}</p><small>Next review {dateLabel(b.review_date)}</small></>}
      </QueryState>
    </div>
    {view && view.head !== 0 && today && <div className="panel"><h2>Next 14 days</h2><div className="strip-grid">
      {Array.from({ length: 14 }, (_, i) => {
        const day = addDays(today, i), sessions = sessionsOn(day)
        return <div className={`strip-day${i === 0 ? ' today' : ''}`} data-testid="strip-day" data-date={day} key={day}>
          <div>{dateLabel(day, { weekday: 'short' })} {day.slice(-2)}</div>
          {sessions.length === 0 && <span className="day-empty">No session</span>}
          {sessions.map(s => {
            const marker = sessionMarker(s, view.completions.find(c => c.session_uid === s.session_uid), today)
            return <div className={`session-tag kind-${s.kind} certainty-${s.certainty}`} data-testid="session-tag" key={s.session_uid}>
              {title(s)} <span className={`marker marker-${marker}`}>{MARKER_LABELS[marker]}</span>
              {!s.is_original && <span className="marker marker-changed">Changed</span>}
            </div>
          })}
        </div>
      })}
    </div></div>}
  </section>
}
