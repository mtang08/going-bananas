import { useState } from 'react'
import { MessageCircle } from 'lucide-react'
import type {
  DismissFinding,
  ExceptionsView,
  Finding,
  Patch,
  ResolvePatch,
} from '../api/types/exceptions'
import type { CoachChat } from '../api/types/coachChat'
import { CopyPrompt } from '../components/CopyPrompt'
import { SyncCard } from '../components/SyncCard'
import { relativeTime } from '../components/shared'
import {
  CATEGORY_LABELS,
  benchmarkStatusLabel,
  operationLabel,
  PROPOSAL_CHIP_LABELS,
  SEVERITY_LABELS,
} from '../coachLabels'
import { Badge, Button, Card, Disclosure } from '../components/ui'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { addDays, dateLabel, fmtDistance, type Unit } from '../lib/format'
import {
  getCalendar,
  getWeeklyDigest,
  getWeeklyProjection,
  api,
  listProposals,
  post,
} from '../api/client'
import { invalidateKeys, qk } from '../api/queryKeys'
import { pageHref } from '../lib/routes'
import { sessionTitle } from '../lib/session'
import type { Activity } from '../api/types/activity'
import type { ActiveBlock } from '../api/types/blocks'
import type { SessionState } from '../api/types/calendar'
import type { CheckinRequest, PromptList } from '../api/types/checkins'
import { QueryState } from '../components/QueryState'
import { mondayOfWeek, SessionSummary } from '../components/PlanOverview'
import { WeekSessions } from '../components/WeekSessions'
import { WeeklyMileage } from '../components/WeeklyMileage'
import { WeeklyDigest, type DigestWeek } from '../components/WeeklyDigest'
import { RunningInterruption, useRunningInterruption } from './RunningInterruption'

export function Home({
  unit,
  onCheckin,
}: {
  unit: Unit
  onCheckin: (req: CheckinRequest) => void
}) {
  const qc = useQueryClient()
  const chat = useQuery({
    queryKey: qk.coachChat,
    queryFn: ({ signal }) => api<CoachChat>('/coach/chat', { signal }),
    retry: false,
  })
  const pending = useQuery({
    queryKey: qk.proposalsOpen,
    queryFn: () => listProposals({ status: 'open' }),
  })
  const calendar = useQuery({
    queryKey: qk.calendarView('head'),
    queryFn: () => getCalendar(),
  })
  const projection = useQuery({
    queryKey: qk.weeklyProjection,
    queryFn: () => getWeeklyProjection(),
  })
  const [digestWeek, setDigestWeek] = useState<DigestWeek>('this')
  const digestNow = useQuery({
    queryKey: qk.weeklyDigest('current'),
    queryFn: () => getWeeklyDigest(),
  })
  const lastWeekStart = digestNow.data?.data
    ? addDays(mondayOfWeek(digestNow.data.data.today), -7)
    : null
  const digestLast = useQuery({
    queryKey: qk.weeklyDigest(lastWeekStart ?? 'pending'),
    queryFn: () => getWeeklyDigest({ week_start: lastWeekStart ?? undefined }),
    enabled: digestWeek === 'last' && lastWeekStart !== null,
  })
  const digest = digestWeek === 'last' ? digestLast : digestNow
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
      } satisfies DismissFinding),
    onSettled: () => invalidateKeys(qc, [qk.exceptions]),
  })
  const resolvePatch = useMutation({
    mutationFn: ({ patch, status }: { patch: Patch; status: 'resolved' | 'escalated' }) =>
      post<Patch>(`/exception-patches/${encodeURIComponent(patch.id)}/resolve`, {
        expected_version: patch.version,
        status,
        note: null,
      } satisfies ResolvePatch),
    onSettled: () => invalidateKeys(qc, [qk.exceptions, qk.calendar]),
  })
  const block = useQuery({
    queryKey: qk.blocksActive,
    queryFn: () => api<ActiveBlock | null>('/blocks/active'),
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
  const interruption = useRunningInterruption()
  const view = calendar.data?.data
  const today = view?.today
  const episode = interruption.data?.data?.interruption
  const runningUnavailable = Boolean(
    today &&
    episode &&
    episode.starts_on <= today &&
    (!episode.return_on || today < episode.return_on),
  )
  const sessionsOn = (day: string) =>
    (view?.sessions ?? [])
      .filter((s) => !s.deleted && s.local_date === day)
      .sort((a, b) => a.slot - b.slot)
  const last =
    view?.last_planned_date ??
    view?.sessions
      .map((s) => s.local_date)
      .sort()
      .at(-1)
  const title = (s: SessionState) => (s.legacy_unstructured ? 'Imported run' : sessionTitle(s))
  const b = block.data?.data
  const bm = b?.benchmark ?? null
  const daysTo =
    bm && today
      ? Math.round(
          (Date.parse(`${bm.planned_date}T12:00:00Z`) - Date.parse(`${today}T12:00:00Z`)) /
            86400000,
        )
      : null
  const target = b?.target_event
  const targetDays =
    target && today ? (Date.parse(target.event_date) - Date.parse(today)) / 86400000 : null
  const targetWhen =
    targetDays === null
      ? ''
      : targetDays < 14
        ? `, ${Math.max(targetDays, 0)} d`
        : `, ${Math.floor(targetDays / 7)} wk`
  const openProposals = pending.data?.data.items ?? []
  const activeDraft = openProposals.find(
    (proposal) => proposal.status === 'pending' || proposal.status === 'stale',
  )
  const hasConversation = Boolean(chat.data?.data?.messages?.length)
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
          <p>Planned training and open prompts.</p>
        </div>
      </div>
      <Card className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
        <div className="flex min-w-0 items-start gap-3">
          <div className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
            <MessageCircle size={20} aria-hidden="true" />
          </div>
          <div>
            <h2 className="mb-1 text-base">Running coach</h2>
            <p className="m-0 text-sm text-muted-foreground">
              Talk through today’s run or plan the next week of training.
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild>
            <a href={pageHref.coach}>{hasConversation ? 'Continue review' : 'Talk to coach'}</a>
          </Button>
          <Button variant="outline" asChild>
            <a href={pageHref.coachStart('sunday_review')}>Start Sunday review</a>
          </Button>
          <Button variant="outline" asChild>
            <a href={pageHref.coachStart('today_run')}>Discuss today’s run</a>
          </Button>
        </div>
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
          <>
            <div className="notice warning">
              <strong>No calendar yet.</strong> Finish setup to fill the next 14 days.{' '}
              <a href={pageHref.settings}>Open setup</a>
            </div>
            <RunningInterruption unit={unit} draft={activeDraft} state={interruption} />
          </>
        )}
        {view && view.head !== 0 && today && (
          <>
            <Card className="today-card" data-testid="today-card">
              <h2>Today's plan</h2>
              <RunningInterruption unit={unit} draft={activeDraft} state={interruption} />
              {sessionsOn(today).length === 0 && <p>No session</p>}
              {sessionsOn(today).map((s) => {
                const completion = view.completions.find((c) => c.session_uid === s.session_uid)
                const unavailable =
                  runningUnavailable &&
                  s.kind === 'run' &&
                  !completion?.activity_id &&
                  completion?.status !== 'completed_as_planned'
                return (
                  <SessionSummary
                    key={s.session_uid}
                    session={s}
                    completion={completion}
                    today={today}
                    unit={unit}
                    showWorkout
                    unavailable={unavailable}
                  >
                    {completion?.activity_id ? (
                      <Button asChild variant="outline" size="sm">
                        <a href={pageHref.activity(completion.activity_id)}>
                          Open run and feedback
                        </a>
                      </Button>
                    ) : s.kind === 'run' && !s.placeholder ? (
                      <Button asChild variant="outline" size="sm">
                        <a href={pageHref.calendarWeek(s.local_date)}>
                          {unavailable ? 'Review workout on Calendar' : 'Open workout on Calendar'}
                        </a>
                      </Button>
                    ) : null}
                  </SessionSummary>
                )
              })}
            </Card>
            {(!last || last <= addDays(today, 6)) && (
              <div className="notice warning" role="status" data-testid="plan-end-banner">
                {last ? `Plan ends on ${dateLabel(last)}` : 'No planned sessions'}
                {' — '}
                <a href={pageHref.coachStart('sunday_review')}>run the weekly review</a>
              </div>
            )}
          </>
        )}
      </QueryState>
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
                    <p>Link the recording to its planned session.</p>
                    <a
                      href={session ? pageHref.calendarWeek(session.local_date) : pageHref.calendar}
                    >
                      Find the session on Calendar
                    </a>
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
                    <p>Link the recording if you ran on another day, or record the outcome.</p>
                    <a
                      href={session ? pageHref.calendarWeek(session.local_date) : pageHref.calendar}
                    >
                      Find the session on Calendar
                    </a>
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
      <div className="home-status" data-testid="home-status">
        <SyncCard compact unit={unit} />
      </div>
      <div className="home-gauges">
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
          loading={digest.isPending}
          error={digest.error}
          stale={!!digest.data}
          retry={() => {
            void digest.refetch()
          }}
        >
          {digest.data?.data && (
            <WeeklyDigest
              digest={digest.data.data}
              unit={unit}
              week={digestWeek}
              onWeekChange={setDigestWeek}
            />
          )}
        </QueryState>
        {digestWeek === 'last' && !digestLast.data && (
          <Button variant="outline" size="sm" onClick={() => setDigestWeek('this')}>
            Back to this week
          </Button>
        )}
      </div>
      {digest.data?.data && (
        <WeekSessions digest={digest.data.data} unit={unit} week={digestWeek} />
      )}
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
              Block: {b.objective} ·{' '}
              {bm ? (
                <>
                  Ends with {bm.protocol} on {dateLabel(bm.planned_date)}
                  {daysTo !== null && daysTo > 0
                    ? ` (${daysTo} ${daysTo === 1 ? 'day' : 'days'})`
                    : ''}{' '}
                  · {benchmarkStatusLabel(b.benchmark_status, null)}
                </>
              ) : (
                'No benchmark this block · judged on training indicators'
              )}
              {b.target_event_status === 'current' &&
                target &&
                ` · Building toward ${target.name} (${dateLabel(target.event_date)}${targetWhen})`}
              {(b.target_event_status === 'changed' || b.target_event_status === 'unset') &&
                ' · Goal race changed; next review re-targets'}{' '}
              · <a href="#block">View training block</a>
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
