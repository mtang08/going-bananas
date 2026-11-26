import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight,
  CalendarDays,
  Footprints,
  MessageCircle,
  Plus,
  Send,
  Square,
} from 'lucide-react'
import { api, post, type Mode } from '../api/client'
import { invalidateKeys, qk } from '../api/queryKeys'
import type { CalendarView } from '../api/types/calendar'
import type { ProposalDetail, ProposalStatus } from '../api/types/coach'
import type {
  CoachChat,
  CoachChatIntent,
  CoachChatMessage,
  CoachChatSend,
} from '../api/types/coachChat'
import { CoachText } from '../components/CoachText'
import { Modal } from '../components/Modal'
import { Badge, Button, Card, Label, Textarea } from '../components/ui'
import { dateLabel } from '../lib/format'
import { pageHref } from '../lib/routes'
import { sessionTitle } from '../lib/session'
import { CoachConnection } from './coach/CoachConnection'

const chatPath = '/coach/chat'
const noMessages: CoachChatMessage[] = []
const starters = {
  sunday_review: {
    label: 'Start Sunday review',
    text: 'Let’s do my Sunday review and talk through the next week of training.',
    icon: CalendarDays,
  },
  today_run: {
    label: 'Discuss today’s run',
    text: 'Can we talk through today’s run and adjust it if needed?',
    icon: Footprints,
  },
}

type Draft = { text: string; intent?: CoachChatIntent; attempt?: CoachChatSend }

function starterDraft(intent?: CoachChatIntent): Draft {
  return intent ? { text: starters[intent].text, intent } : { text: '' }
}

function readDraft(key: string, starter?: CoachChatIntent): Draft {
  try {
    const stored = sessionStorage.getItem(key)
    if (stored) {
      const draft = JSON.parse(stored) as Draft | null
      if (draft && typeof draft.text === 'string') return draft
    }
  } catch {
    // The conversation still works when browser storage is unavailable.
  }
  return starterDraft(starter)
}

const proposalLabels: Record<ProposalStatus, string> = {
  pending: 'Pending review',
  stale: 'Needs refresh',
  accepted: 'Accepted',
  partially_accepted: 'Partially accepted',
  rejected: 'Rejected',
  discarded: 'Discarded',
  invalid: 'Needs correction',
}

export function Coach({ mode, starter }: { mode: Mode; starter?: CoachChatIntent }) {
  const qc = useQueryClient()
  const draftKey = `gb-coach-draft-${mode}`
  const [draft, setDraft] = useState(() => readDraft(draftKey, starter))
  const [confirmNew, setConfirmNew] = useState(false)
  const [atLatest, setAtLatest] = useState(true)
  const heading = useRef<HTMLHeadingElement>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const transcript = useRef<HTMLDivElement>(null)
  const chat = useQuery({
    queryKey: qk.coachChat,
    queryFn: ({ signal }) => api<CoachChat>(chatPath, { signal }),
    staleTime: 0,
    retry: false,
    refetchInterval: (query) => (query.state.data?.data.status === 'running' ? 650 : false),
  })
  const thread = chat.data?.data
  const running = thread?.status === 'running'
  const messages = thread?.messages ?? noMessages
  const lastMessage = messages.at(-1)
  const lastUser = messages.filter((message) => message.role === 'user').at(-1)
  const linkedProposal = thread?.proposal_id
  const revision = thread?.proposal_revision
  const needsSignIn = thread?.error?.code === 'auth_required'
  const acceptedDraft = Boolean(
    draft.attempt &&
    messages.some((message) => message.client_message_id === draft.attempt?.client_message_id),
  )
  const composed = acceptedDraft ? '' : draft.text

  useEffect(() => {
    heading.current?.focus({ preventScroll: true })
    if (starter && window.location.hash === pageHref.coachStart(starter)) {
      window.history.replaceState(window.history.state, '', pageHref.coach)
    }
  }, [starter])
  useEffect(() => {
    try {
      if (composed) sessionStorage.setItem(draftKey, JSON.stringify(draft))
      else sessionStorage.removeItem(draftKey)
    } catch {
      // Continue with the draft held in memory.
    }
  }, [composed, draft, draftKey])
  useEffect(() => {
    if (linkedProposal) invalidateKeys(qc, [qk.proposalsOpen, qk.proposal(linkedProposal)])
  }, [qc, linkedProposal, revision])
  useEffect(() => {
    if (needsSignIn) invalidateKeys(qc, [qk.coachAuth])
  }, [qc, needsSignIn])

  const cancelRead = () => qc.cancelQueries({ queryKey: qk.coachChat })
  const syncThread = (response: NonNullable<typeof chat.data>) => {
    qc.setQueryData(qk.coachChat, response)
  }
  const refreshThread = () => invalidateKeys(qc, [qk.coachChat])
  const send = useMutation({
    mutationFn: (body: CoachChatSend) => post<CoachChat>(`${chatPath}/messages`, body),
    networkMode: 'always',
    onMutate: cancelRead,
    onSuccess: (response, body) => {
      syncThread(response)
      setDraft((current) =>
        current.attempt?.client_message_id === body.client_message_id ? { text: '' } : current,
      )
    },
    onError: refreshThread,
  })
  const cancel = useMutation({
    mutationFn: (id: string) => post<CoachChat>(`${chatPath}/cancel`, { thread_id: id }),
    networkMode: 'always',
    onMutate: cancelRead,
    onSuccess: syncThread,
    onError: refreshThread,
  })
  const fresh = useMutation({
    mutationFn: (id: string) => post<CoachChat>(`${chatPath}/new`, { thread_id: id }),
    networkMode: 'always',
    onMutate: cancelRead,
    onSuccess: (response) => {
      syncThread(response)
      send.reset()
      cancel.reset()
      setDraft(starterDraft('sunday_review'))
      setConfirmNew(false)
      setAtLatest(true)
      requestAnimationFrame(() => textarea.current?.focus())
    },
    onError: refreshThread,
  })
  const busy = send.isPending || cancel.isPending || fresh.isPending
  const disconnected = chat.isError || chat.fetchStatus === 'paused'
  const canSend = Boolean(thread && !running && !busy && !disconnected && composed.trim())

  const goToLatest = () => {
    if (transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight
  }
  useLayoutEffect(() => {
    if (atLatest) goToLatest()
  }, [atLatest, messages, running])

  const chooseStarter = (intent: CoachChatIntent) => {
    send.reset()
    setDraft(starterDraft(intent))
    textarea.current?.focus()
  }
  const submit = () => {
    if (!thread || !canSend) return
    const text = composed.trim()
    const prior = draft.attempt
    const body =
      prior && prior.thread_id === thread.id
        ? prior
        : {
            text,
            intent: draft.intent,
            thread_id: thread.id,
            client_message_id: crypto.randomUUID(),
          }
    setDraft({ ...draft, attempt: body })
    setAtLatest(true)
    goToLatest()
    send.mutate(body)
  }
  const resumeLastMessage = () => {
    if (!lastUser) return
    send.reset()
    setDraft({ text: lastUser.text })
    textarea.current?.focus()
  }
  const status = send.isPending
    ? 'Sending message…'
    : cancel.isPending
      ? 'Stopping reply…'
      : running
        ? 'Coach is replying…'
        : thread?.status === 'cancelled'
          ? 'Reply stopped.'
          : thread?.status === 'idle' && lastMessage?.role === 'assistant'
            ? 'Coach replied.'
            : ''

  return (
    <section className="page-content space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 ref={heading} tabIndex={-1} className="outline-none">
            Running coach
          </h1>
          <p className="m-0 mt-1 text-sm text-muted-foreground">
            Review your training, talk through a workout, or plan the next week.
          </p>
        </div>
        {thread?.id && messages.length > 0 && (
          <Button
            type="button"
            variant="outline"
            disabled={running || busy || disconnected}
            onClick={() => setConfirmNew(true)}
          >
            <Plus size={17} /> New Sunday review
          </Button>
        )}
      </div>
      <CoachConnection
        chatError={thread?.error ?? null}
        hasCoachReply={messages.some((message) => message.role === 'assistant')}
      />
      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_17.5rem]">
        <Card className="p-0">
          <header className="flex min-h-14 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b px-4 py-3 sm:px-6">
            <h2 className="m-0 flex items-center gap-2 text-sm font-semibold">
              <MessageCircle size={17} aria-hidden="true" /> Conversation
            </h2>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span role="status">{!disconnected && status}</span>
              {!atLatest && messages.length > 0 && (
                <Button type="button" variant="ghost" size="sm" onClick={goToLatest}>
                  Jump to latest
                </Button>
              )}
            </div>
          </header>
          {disconnected && (
            <div
              className="flex flex-wrap items-center justify-between gap-3 border-b bg-muted px-4 py-3 text-sm sm:px-6"
              role="alert"
            >
              <span>
                {chat.error?.message ??
                  'The local app is offline. Reconnect to refresh the conversation.'}
              </span>
              <Button type="button" variant="outline" size="sm" onClick={() => void chat.refetch()}>
                Reconnect
              </Button>
            </div>
          )}
          {chat.isPending && !disconnected && (
            <p role="status" className="px-4 py-6 text-sm text-muted-foreground sm:px-6">
              Loading conversation…
            </p>
          )}
          {messages.length > 0 ? (
            <div
              ref={transcript}
              className="max-h-[52dvh] min-h-44 overflow-y-auto overscroll-contain px-4 py-4 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:px-6"
              role="region"
              aria-label="Conversation history"
              tabIndex={0}
              onScroll={(event) => {
                const { scrollTop, scrollHeight, clientHeight } = event.currentTarget
                setAtLatest(scrollHeight - scrollTop - clientHeight < 48)
              }}
            >
              <ol className="m-0 grid list-none gap-4 p-0">
                {messages.map((message) => (
                  <li
                    key={message.id}
                    className={
                      message.role === 'user'
                        ? 'ml-auto w-fit max-w-[95%] rounded-xl border border-primary/15 bg-primary/10 px-4 py-3 sm:max-w-[84%]'
                        : 'w-fit max-w-full rounded-xl border bg-muted/50 px-4 py-3'
                    }
                  >
                    <p className="m-0 mb-1 text-xs font-semibold">
                      {message.role === 'user' ? 'You' : 'Coach'}
                    </p>
                    <div className="text-sm leading-relaxed whitespace-pre-wrap wrap-anywhere [&_p]:my-0 [&_p+p]:mt-2 [&_ul]:my-2">
                      {message.role === 'assistant' ? (
                        <CoachText text={message.text} />
                      ) : (
                        message.text
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          ) : (
            thread && (
              <div className="grid gap-4 px-4 py-7 sm:px-6 sm:py-9">
                <div>
                  <h3 className="m-0 text-base font-semibold">What’s on your mind?</h3>
                  <p className="m-0 mt-1 text-sm text-muted-foreground">
                    Bring a question, a schedule change, or feedback from your last run.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {(Object.keys(starters) as CoachChatIntent[]).map((intent) => {
                    const { label, icon: Icon } = starters[intent]
                    return (
                      <Button
                        key={intent}
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={Boolean(
                          composed && composed !== starters[draft.intent ?? intent].text,
                        )}
                        onClick={() => chooseStarter(intent)}
                      >
                        <Icon size={16} /> {label}
                      </Button>
                    )
                  })}
                </div>
              </div>
            )
          )}
          {(thread?.status === 'failed' || send.error || cancel.error) && (
            <div className="border-t bg-muted/50 px-4 py-3 text-sm sm:px-6" role="alert">
              <p className="m-0">
                {send.error?.message ??
                  cancel.error?.message ??
                  thread?.error?.message ??
                  'The coach could not finish the reply.'}
              </p>
              {lastUser && thread?.status === 'failed' && !composed && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="mt-2"
                  onClick={resumeLastMessage}
                >
                  Use last message again
                </Button>
              )}
            </div>
          )}
          <form
            className="grid gap-2 border-t px-4 py-4 sm:px-6"
            onSubmit={(event) => {
              event.preventDefault()
              submit()
            }}
          >
            <Label htmlFor="coach-message">Message your coach</Label>
            <Textarea
              id="coach-message"
              ref={textarea}
              value={composed}
              placeholder="Ask about your training or share an update…"
              maxLength={8000}
              readOnly={send.isPending}
              onChange={(event) => {
                send.reset()
                setDraft({
                  text: event.target.value,
                  intent: acceptedDraft ? undefined : draft.intent,
                })
              }}
              aria-describedby="coach-compose-hint"
              onKeyDown={(event) => {
                if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
                if (!canSend) return
                event.preventDefault()
                submit()
              }}
            />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p id="coach-compose-hint" className="m-0 text-xs text-muted-foreground">
                {draft.intent === 'sunday_review' && !acceptedDraft && messages.length > 0
                  ? 'This message continues the current conversation.'
                  : 'Enter to send · Shift+Enter for a new line'}
              </p>
              {running && thread?.id ? (
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy || disconnected}
                  onClick={() => cancel.mutate(thread.id!)}
                >
                  <Square size={15} /> Stop reply
                </Button>
              ) : (
                <Button type="submit" disabled={!canSend}>
                  <Send size={15} /> {send.error ? 'Retry sending' : 'Send message'}
                </Button>
              )}
            </div>
          </form>
        </Card>
        <aside aria-label="Training context" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
          <ChatProposal id={linkedProposal} />
          <TodayContext />
        </aside>
      </div>
      {confirmNew && thread?.id && (
        <Modal
          label="Start a new Sunday review?"
          close={() => {
            if (!fresh.isPending) {
              fresh.reset()
              setConfirmNew(false)
            }
          }}
        >
          <h2 className="m-0 text-lg">Start a new Sunday review?</h2>
          <p className="m-0 my-3 text-sm text-muted-foreground">
            This opens a blank conversation. Saved proposals and calendar decisions stay available
            in Going Bananas.
          </p>
          {fresh.error && <p role="alert">{fresh.error.message}</p>}
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={fresh.isPending}
              onClick={() => setConfirmNew(false)}
            >
              Keep talking
            </Button>
            <Button
              type="button"
              disabled={busy || running || disconnected}
              onClick={() => fresh.mutate(thread.id!)}
            >
              {fresh.isPending ? 'Starting…' : 'Start new review'}
            </Button>
          </div>
        </Modal>
      )}
    </section>
  )
}

function ChatProposal({ id }: { id?: string | null }) {
  const detail = useQuery({
    queryKey: qk.proposal(id ?? ''),
    queryFn: () => api<ProposalDetail>(`/coach/proposals/${encodeURIComponent(id ?? '')}`),
    enabled: Boolean(id),
  })
  const proposal = detail.data?.data
  const status = proposal?.status === 'pending' && !proposal.is_current ? 'stale' : proposal?.status
  return (
    <Card>
      <h2 className="m-0 text-base font-semibold">Plan proposal</h2>
      {id && detail.isPending && (
        <p className="mb-0 mt-2 text-sm text-muted-foreground" role="status">
          Loading proposal…
        </p>
      )}
      {detail.error && (
        <p className="mb-0 mt-2 text-sm text-muted-foreground" role="status">
          Could not refresh the proposal.
        </p>
      )}
      {!id && (
        <p className="mb-0 mt-2 text-sm text-muted-foreground">
          When you and the coach agree on changes, the coach can save a proposal for you to review.
        </p>
      )}
      {proposal && status && (
        <div className="mt-3 space-y-3">
          <Badge variant="secondary">{proposalLabels[status]}</Badge>
          <p className="m-0 wrap-anywhere text-sm">{proposal.headline}</p>
          {status === 'pending' && (
            <p className="m-0 text-xs text-muted-foreground">
              Your calendar updates after you accept changes.
            </p>
          )}
          {proposal.decision_result?.calendar_version != null && (
            <p className="m-0 text-xs text-muted-foreground">
              Applied in calendar version {proposal.decision_result.calendar_version}.
            </p>
          )}
        </div>
      )}
      {id && (
        <Button variant="outline" size="sm" className="mt-4" asChild>
          <a href={pageHref.proposal(id)}>
            {status && status !== 'pending' && status !== 'stale'
              ? 'View proposal'
              : 'Review proposal'}
            <ArrowRight size={15} aria-hidden="true" />
          </a>
        </Button>
      )}
    </Card>
  )
}

function TodayContext() {
  const calendar = useQuery({
    queryKey: qk.calendarView('head'),
    queryFn: () => api<CalendarView>('/calendar'),
  })
  const view = calendar.data?.data
  if (!view?.head || calendar.isError) return null
  const runs = view.sessions.filter(
    (session) => session.local_date === view.today && session.kind === 'run' && !session.deleted,
  )
  return (
    <Card>
      <h2 className="m-0 text-base font-semibold">Today on your calendar</h2>
      <p className="mb-0 mt-2 text-sm text-muted-foreground">
        {dateLabel(view.today, { weekday: 'long', month: 'short', day: 'numeric' })}
      </p>
      {runs.length > 0 ? (
        <ul className="m-0 mt-2 grid list-none gap-1 p-0 text-sm">
          {runs.map((run) => (
            <li key={run.session_uid}>
              {run.legacy_unstructured ? 'Imported run' : sessionTitle(run)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-0 mt-2 text-sm">No run on the calendar.</p>
      )}
      <Button asChild variant="link" size="sm" className="mt-2 h-auto px-0">
        <a href={pageHref.calendarWeek(view.today)}>
          Open calendar <ArrowRight size={15} aria-hidden="true" />
        </a>
      </Button>
    </Card>
  )
}
