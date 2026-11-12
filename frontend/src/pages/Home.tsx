import { Badge, Button, Card } from '../components/ui'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addDays,
  api,
  dateLabel,
  DECISION_LABELS,
  fetchDailyGuidance,
  fmtDistance,
  invalidateKeys,
  pageHref,
  post,
  qk,
  sessionTitle,
  statusText,
  type Activity,
  type BlockVersion,
  type CalendarView,
  type CheckinRequest,
  type PromptList,
  type SessionState,
  type Unit,
} from '../api'
import type { ProposalSummary } from '../api/types/coach'
import { QueryState } from '../components/QueryState'
import { SessionSummary, WeekOverview } from '../components/PlanOverview'
import { WeeklyMileage } from '../components/WeeklyMileage'
import type { WeeklyProjection } from '../api/types/calendar'

export function Home({
  unit,
  onCheckin,
}: {
  unit: Unit
  onCheckin: (req: CheckinRequest) => void
}) {
  const qc = useQueryClient()
  const pending = useQuery({
    queryKey: ['v2', 'proposals', 'open'],
    queryFn: () => api<{ items: ProposalSummary[] }>('/coach/proposals?status=open'),
  })
  const calendar = useQuery({
    queryKey: qk.calendarView('head'),
    queryFn: () => api<CalendarView>('/calendar'),
  })
  const projection = useQuery({
    queryKey: ['v2', 'calendar', 'weekly-projection'],
    queryFn: () => api<WeeklyProjection>('/calendar/weekly-projection'),
  })
  const prompts = useQuery({ queryKey: qk.prompts, queryFn: () => api<PromptList>('/prompts') })
  const guidance = useQuery({ queryKey: qk.coachDaily, queryFn: fetchDailyGuidance })
  const block = useQuery({
    queryKey: qk.blocksActive,
    queryFn: () => api<BlockVersion | null>('/blocks/active'),
  })
  const open = prompts.data?.data.items.filter((p) => p.status === 'open') ?? []
  const ids = [
    ...new Set(
      open
        .filter((p) => p.kind === 'rpe' || p.kind === 'delayed_symptom')
        .flatMap((p) => (p.activity_id ? [p.activity_id] : [])),
    ),
  ]
  const activities = useQueries({
    queries: ids.map((id) => ({
      queryKey: qk.activity(id),
      queryFn: () => api<Activity>(`/activities/${encodeURIComponent(id)}`),
    })),
  })
  const dismiss = useMutation({
    mutationFn: (id: string) => post<unknown>(`/prompts/${encodeURIComponent(id)}/dismiss`, {}),
    onSuccess: () => invalidateKeys(qc, [qk.prompts]),
  })
  const view = calendar.data?.data
  const today = view?.today
  const sessionsOn = (day: string) =>
    (view?.sessions ?? []).filter((s) => s.local_date === day).sort((a, b) => a.slot - b.slot)
  const last =
    view?.last_planned_date ??
    view?.sessions
      .map((s) => s.local_date)
      .sort()
      .at(-1)
  const title = (s: SessionState) => (s.legacy_unstructured ? 'Imported run' : sessionTitle(s))
  const g = guidance.data
  const b = block.data?.data

  return (
    <section className="page-content home-page space-y-5">
      <div className="page-heading">
        <div>
          <span className="eyebrow">TODAY</span>
          <h1>
            {today ? dateLabel(today, { weekday: 'long', month: 'long', day: 'numeric' }) : 'Today'}
          </h1>
          <p>Planned training, open prompts, and the next two weeks.</p>
        </div>
        <Button onClick={() => onCheckin({ kind: 'exception', prompt: null, activityId: null })}>
          Record check-in
        </Button>
      </div>
      <QueryState
        loading={projection.isPending}
        error={projection.error}
        stale={!!projection.data}
        retry={() => {
          void projection.refetch()
        }}
      >
        {projection.data?.data && <WeeklyMileage projection={projection.data.data} unit={unit} />}
      </QueryState>
      {(pending.data?.data?.items?.length ?? 0) > 0 && (
        <Card className="pending-proposals">
          <h2>Open proposal</h2>
          {pending.data!.data.items.map((proposal) => (
            <article key={proposal.id}>
              <p>{proposal.summary}</p>
              <Button variant="outline" asChild>
                <a href={`#proposal/${encodeURIComponent(proposal.id)}`}>Review proposal</a>
              </Button>
            </article>
          ))}
        </Card>
      )}
      <Card
        className={
          prompts.isSuccess && !prompts.error && open.length === 0
            ? 'home-quiet-state rounded-none border-0 bg-transparent px-0 py-1 shadow-none'
            : undefined
        }
      >
        <h2>Prompts</h2>
        <QueryState
          loading={prompts.isPending}
          error={prompts.error}
          stale={!!prompts.data}
          retry={() => {
            void prompts.refetch()
          }}
        >
          {open.length === 0 && <p className="muted-text">No open prompts.</p>}
          {open.map((prompt) => {
            const activity = activities[ids.indexOf(prompt.activity_id ?? '')]?.data?.data
            const session = view?.sessions.find((s) => s.session_uid === prompt.session_uid)
            return (
              <div
                className="prompt-item"
                data-testid="prompt-item"
                data-kind={prompt.kind}
                key={prompt.id}
              >
                {prompt.kind === 'rpe' && (
                  <>
                    <strong>
                      Rate your run
                      {activity
                        ? ` on ${dateLabel(activity.local_date)} · ${fmtDistance(activity.distance_m, unit)}`
                        : ''}
                    </strong>
                    <p>How hard was the entire session?</p>
                    <Button
                      variant="outline"
                      onClick={() =>
                        onCheckin({ kind: 'post_run', prompt, activityId: prompt.activity_id })
                      }
                    >
                      Add RPE
                    </Button>
                  </>
                )}
                {prompt.kind === 'delayed_symptom' && (
                  <>
                    <strong>
                      Delayed-response check
                      {activity ? ` for your run on ${dateLabel(activity.local_date)}` : ''}
                    </strong>
                    <p>Any pain or gait change since this run?</p>
                    <Button
                      variant="outline"
                      onClick={() =>
                        onCheckin({
                          kind: 'delayed_followup',
                          prompt,
                          activityId: prompt.activity_id,
                        })
                      }
                    >
                      Answer check
                    </Button>
                  </>
                )}
                {prompt.kind === 'unmatched_session' && (
                  <>
                    <strong>A run needs matching to a planned session</strong>
                    <p>Pick the session on the Calendar page.</p>
                    <a href={pageHref.calendar}>Open calendar</a>
                  </>
                )}
                {prompt.kind === 'missing_activity' && (
                  <>
                    <strong>
                      No activity found for{' '}
                      {session
                        ? `${title(session)} on ${dateLabel(session.local_date)}`
                        : 'a planned session'}
                    </strong>
                    <p>Mark it skipped, moved, or not recorded on the Calendar page.</p>
                    <a href={pageHref.calendar}>Open calendar</a>
                  </>
                )}
                <Button
                  variant="link"
                  disabled={dismiss.isPending}
                  onClick={() => dismiss.mutate(prompt.id)}
                >
                  Dismiss
                </Button>
              </div>
            )
          })}
          {dismiss.error && (
            <p className="error-text" role="alert">
              {dismiss.error.message}
            </p>
          )}
        </QueryState>
      </Card>
      <Card
        className={
          guidance.isSuccess && !guidance.error && g === null
            ? 'home-quiet-state rounded-none border-0 bg-transparent px-0 py-1 shadow-none'
            : undefined
        }
      >
        <h2>Daily guidance</h2>
        <QueryState
          loading={guidance.isPending}
          error={guidance.error}
          stale={guidance.data !== undefined}
          retry={() => {
            void guidance.refetch()
          }}
        >
          {g === null && <p>No guidance today. The planned session stands.</p>}
          {g && (
            <>
              <Badge className={`status-chip ${g.decision}`}>{DECISION_LABELS[g.decision]}</Badge>
              <p>{g.rationale}</p>
              {g.coach_review_suggested && (
                <div className="notice warning">
                  Coach review suggested. Run the running-coach skill (daily review) before
                  training.
                </div>
              )}
              {g.missing_inputs.length > 0 && (
                <small>Missing inputs: {g.missing_inputs.map(statusText).join(', ')}</small>
              )}
            </>
          )}
        </QueryState>
      </Card>
      <QueryState
        loading={calendar.isPending}
        error={calendar.error}
        stale={!!calendar.data}
        retry={() => {
          void calendar.refetch()
        }}
      >
        {view?.head === 0 && (
          <div className="notice warning">
            <strong>No calendar yet.</strong> Finish setup to fill the next 14 days.{' '}
            <a href={pageHref.settings}>Open setup</a>
          </div>
        )}
        {view && view.head !== 0 && today && (
          <>
            {(!last || last <= addDays(today, 6)) && (
              <div className="notice warning" role="status" data-testid="plan-end-banner">
                {last
                  ? `Plan ends on ${dateLabel(last)} — run the weekly review`
                  : 'No planned sessions — run the weekly review'}
              </div>
            )}
            <Card className="today-card" data-testid="today-card">
              <h2>Today's plan</h2>
              {sessionsOn(today).length === 0 && <p>No session</p>}
              {sessionsOn(today).map((s) => (
                <SessionSummary
                  key={s.session_uid}
                  session={s}
                  completion={view.completions.find((c) => c.session_uid === s.session_uid)}
                  today={today}
                  unit={unit}
                  showWorkout
                />
              ))}
            </Card>
          </>
        )}
      </QueryState>
      {view && view.head !== 0 && today && <WeekOverview view={view} unit={unit} />}
      <Card>
        <h2>Training block</h2>
        <QueryState
          loading={block.isPending}
          error={block.error}
          stale={!!block.data}
          retry={() => {
            void block.refetch()
          }}
        >
          {b === null && (
            <p>
              No active block. The calendar runs without one until the first block review.{' '}
              <a href="#guide">Training guide</a>
            </p>
          )}
          {b && (
            <>
              <p>{b.objective}</p>
              <small>Next review {dateLabel(b.review_date)}</small>
              <p>Maintaining: {b.maintained_qualities?.join(', ') || 'Not specified'}</p>
              <a href="#block">View training block</a> · <a href="#guide">Training guide</a>
            </>
          )}
        </QueryState>
      </Card>
    </section>
  )
}
