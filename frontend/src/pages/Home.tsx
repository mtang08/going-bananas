import type { ExceptionsView, Finding, Patch } from '../api/types/exceptions'
import { CopyPrompt } from '../components/CopyPrompt'
import { SyncCard } from '../components/SyncCard'
import { relativeTime } from '../components/shared'
import {
  CATEGORY_LABELS,
  operationLabel,
  PROPOSAL_CHIP_LABELS,
  SEVERITY_LABELS,
} from '../coachLabels'
import { Badge, Button, Card, Disclosure } from '../components/ui'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addDays,
  api,
  dateLabel,
  fmtDistance,
  invalidateKeys,
  pageHref,
  post,
  qk,
  sessionTitle,
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
  const exceptions = useQuery({
    queryKey: qk.exceptions,
    queryFn: () => api<ExceptionsView>('/exceptions'),
  })
  const findings = exceptions.data?.data?.findings ?? []
  const logged = findings.filter((f) => f.status === 'open' && f.severity === 'observe')
  const recommended = exceptions.data?.data?.review_recommended ?? []
  const flagged = findings.filter((f) => f.status === 'open' && f.severity !== 'observe')
  const due = (exceptions.data?.data?.patches ?? []).filter((p) => p.reassess_due)
  const dismissFinding = useMutation({
    mutationFn: (f: Finding) =>
      post<Finding>(`/exceptions/${encodeURIComponent(f.id)}/dismiss`, {
        expected_version: f.version,
        note: null,
      }),
    onSettled: () => invalidateKeys(qc, [qk.exceptions]),
  })
  const resolvePatch = useMutation({
    mutationFn: ({ patch, status }: { patch: Patch; status: 'resolved' | 'escalated' }) =>
      post<Patch>(`/exception-patches/${encodeURIComponent(patch.id)}/resolve`, {
        expected_version: patch.version,
        status,
        note: null,
      }),
    onSettled: () => invalidateKeys(qc, [qk.exceptions, qk.calendar]),
  })
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
  const b = block.data?.data
  const openProposals = pending.data?.data.items ?? []
  const attentionCount =
    openProposals.length + recommended.length + flagged.length + due.length + open.length
  const showAttention =
    attentionCount > 0 ||
    Boolean(prompts.error) ||
    Boolean(pending.error) ||
    Boolean(exceptions.error)

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
      </div>
      <div className="home-status" data-testid="home-status">
        <SyncCard compact />
      </div>
      {showAttention && (
        <Card className="needs-attention" data-testid="needs-attention">
          <h2>Needs attention</h2>
          {openProposals.map((p) => (
            <div
              className="attention-row"
              data-testid="attention-row"
              data-kind="proposal"
              key={p.id}
            >
              <Badge className={`status-chip ${p.status}`}>
                {PROPOSAL_CHIP_LABELS[p.status] ?? p.status}
              </Badge>{' '}
              <strong>{operationLabel(p.operation)}</strong>{' '}
              <small>
                {relativeTime(p.submitted_at)} · {p.change_count}{' '}
                {p.change_count === 1 ? 'change' : 'changes'}
              </small>{' '}
              <Button variant="outline" size="sm" asChild>
                <a href={`#proposal/${encodeURIComponent(p.id)}`}>Review</a>
              </Button>
            </div>
          ))}
          {recommended.map((r) => (
            <div
              className="attention-row"
              data-testid="attention-row"
              data-kind="recommendation"
              key={`${r.operation}:${r.reason}`}
            >
              <strong>{operationLabel(r.operation)}</strong> <span>{r.reason}</span>
              <CopyPrompt text={r.prompt} className="attention-prompt" />
            </div>
          ))}
          {flagged.map((f) => (
            <div
              className="attention-row"
              data-testid="attention-row"
              data-kind="finding"
              key={f.id}
            >
              <Badge className={`severity-chip ${f.severity}`}>{SEVERITY_LABELS[f.severity]}</Badge>{' '}
              <strong>{CATEGORY_LABELS[f.category]}</strong> <span>{f.summary}</span>{' '}
              <Button
                variant="link"
                disabled={dismissFinding.isPending}
                onClick={() => dismissFinding.mutate(f)}
              >
                Dismiss
              </Button>
            </div>
          ))}
          {due.map((p) => (
            <div className="attention-row" data-testid="attention-row" data-kind="patch" key={p.id}>
              <strong>
                Reassess due · {dateLabel(p.window_start)}–{dateLabel(p.window_end)}
              </strong>{' '}
              <Button
                variant="outline"
                size="sm"
                disabled={resolvePatch.isPending}
                onClick={() => resolvePatch.mutate({ patch: p, status: 'resolved' })}
              >
                Mark resolved
              </Button>{' '}
              <Button
                variant="ghost"
                size="sm"
                disabled={resolvePatch.isPending}
                onClick={() => resolvePatch.mutate({ patch: p, status: 'escalated' })}
              >
                Still not right
              </Button>
            </div>
          ))}
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
          {exceptions.error && (
            <p className="error-text" role="alert">
              Could not load findings: {exceptions.error.message}
            </p>
          )}
          {(dismissFinding.error ?? resolvePatch.error) && (
            <p className="error-text" role="alert">
              {(dismissFinding.error ?? resolvePatch.error)!.message}
            </p>
          )}
          {pending.error && (
            <p className="error-text" role="alert">
              Could not load proposals: {pending.error.message}
            </p>
          )}
          {prompts.error && (
            <p className="error-text" role="alert">
              Could not load prompts: {prompts.error.message}
            </p>
          )}
        </Card>
      )}
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
      <QueryState
        loading={block.isPending}
        error={block.error}
        stale={!!block.data}
        retry={() => {
          void block.refetch()
        }}
      >
        <p className="home-block-line" data-testid="block-line">
          {b ? (
            <>
              Block: {b.objective} · Next review {dateLabel(b.review_date)} ·{' '}
              <a href="#block">View training block</a>
            </>
          ) : (
            <>
              No active training block. <a href="#block">Training block</a>
            </>
          )}
        </p>
      </QueryState>
      {logged.length > 0 && (
        <Disclosure variant="card" className="training-disclosure" data-testid="logged-findings">
          <summary>Logged for Sunday review ({logged.length})</summary>
          <ul>
            {logged.map((f) => (
              <li key={f.id}>
                <Badge className="severity-chip observe">{SEVERITY_LABELS.observe}</Badge>{' '}
                {CATEGORY_LABELS[f.category]} · {f.summary}
              </li>
            ))}
          </ul>
        </Disclosure>
      )}
    </section>
  )
}
