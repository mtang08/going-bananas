import { saveInterruption } from '../api/planning'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api } from '../api/client'
import { invalidateKeys, qk } from '../api/queryKeys'
import { RECIPE_LABELS } from '../api/types/calendar'
import type { ProposalSummary } from '../api/types/coach'
import type {
  InterruptionRun,
  RunningInterruption as Episode,
  RunningInterruptionView,
} from '../api/types/runningInterruption'
import { INTERRUPTION_PROMPT } from '../coachPrompts'
import { CopyPrompt } from '../components/CopyPrompt'
import { Modal } from '../components/Modal'
import { Badge, Button, Disclosure, Input, NativeSelect } from '../components/ui'
import { addDays, dateLabel, fmtDistance, fmtDuration, type Unit } from '../lib/format'
import { pageHref } from '../lib/routes'

const ENDPOINT = '/running-interruption'
const REASON: Record<Episode['reason'], string> = {
  schedule: 'Schedule',
  travel: 'Travel',
  illness: 'Illness',
  other: 'Other',
}
const PHASE = {
  planned: 'Planned',
  paused: 'Paused',
  review_due: 'Review due',
  returning: 'Return to review',
}
const displayDay = (date: string) =>
  dateLabel(date, { weekday: 'short', month: 'short', day: 'numeric' })

function RunPreview({ run, unit }: { run: InterruptionRun; unit: Unit }) {
  const name = (run.recipe_id && RECIPE_LABELS[run.recipe_id]) || run.intent || 'Planned run'
  return (
    <>
      {displayDay(run.local_date)} · {name}
      {run.planned_duration_s != null && ` · ${fmtDuration(run.planned_duration_s)}`}
      {run.planned_distance_m != null && ` · ${fmtDistance(run.planned_distance_m, unit)}`}
    </>
  )
}

export function useRunningInterruption() {
  return useQuery({
    queryKey: qk.runningInterruption,
    queryFn: () => api<RunningInterruptionView>(ENDPOINT),
  })
}

export function RunningInterruption({
  unit,
  draft,
  state,
}: {
  unit: Unit
  draft: ProposalSummary | undefined
  state: ReturnType<typeof useRunningInterruption>
}) {
  const qc = useQueryClient()
  const data = state.data?.data
  const [editor, setEditor] = useState<{ end: boolean; initial: RunningInterruptionView } | null>(
    null,
  )
  const persist = async (expectedVersion: number, interruption: Episode | null) => {
    const saved = await saveInterruption({
      expected_version: expectedVersion,
      interruption,
    })
    await qc.cancelQueries({ queryKey: qk.runningInterruption, exact: true })
    qc.setQueryData(qk.runningInterruption, saved)
    invalidateKeys(qc, [qk.profile, qk.proposals])
    setEditor(null)
  }
  return (
    <>
      {state.error && (
        <div role="alert" className="notice warning">
          Could not load the running interruption.{' '}
          <Button variant="link" size="sm" onClick={() => void state.refetch()}>
            Retry interruption
          </Button>
        </div>
      )}
      {data && (
        <>
          {data.interruption ? (
            <section className="notice warning space-y-2" aria-label="Running interruption">
              <div className="flex flex-wrap items-center gap-2">
                <h3>Running interruption</h3>
                {data.phase && <Badge variant="outline">{PHASE[data.phase]}</Badge>}
              </div>
              <p>
                {REASON[data.interruption.reason]} · Starts{' '}
                {displayDay(data.interruption.starts_on)}
                {data.interruption.return_on
                  ? ` · Next availability ${displayDay(data.interruption.return_on)}`
                  : ' · Return date open'}
              </p>
              {data.interruption.review_on && (
                <p>
                  Reassess {displayDay(data.interruption.review_on)}. Use that date to check in
                  before deciding when to run.
                </p>
              )}
              {data.affected_runs.length > 0 && (
                <div>
                  <strong>Accepted runs to leave behind or review</strong>
                  <ul className="list-disc pl-5">
                    {data.affected_runs.map((run) => (
                      <li key={run.session_uid}>
                        <RunPreview run={run} unit={unit} />
                      </li>
                    ))}
                  </ul>
                  {data.affected_runs_omitted > 0 && (
                    <p>{data.affected_runs_omitted} more in the available plan.</p>
                  )}
                </div>
              )}
              {data.first_run && (
                <p>
                  <strong>First run to review</strong>{' '}
                  <a href={pageHref.calendarWeek(data.first_run.local_date)}>
                    <RunPreview run={data.first_run} unit={unit} />
                  </a>
                </p>
              )}
              {data.recorded_return && (
                <p>
                  <strong>First recorded run back</strong>
                  {' · '}
                  <a href={pageHref.activity(data.recorded_return.activity_id)}>
                    Review feedback for {displayDay(data.recorded_return.local_date)}
                  </a>
                </p>
              )}
              {data.review_reason && <p>{data.review_reason}</p>}
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setEditor({ end: false, initial: data })}
                >
                  Edit interruption
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setEditor({ end: true, initial: data })}
                >
                  End interruption
                </Button>
                {draft && (
                  <Button size="sm" variant="outline" asChild>
                    <a href={`#proposal/${encodeURIComponent(draft.id)}`}>
                      Open current coach draft
                    </a>
                  </Button>
                )}
              </div>
              <Disclosure>
                <summary>Discuss with the coach</summary>
                <CopyPrompt text={INTERRUPTION_PROMPT} />
              </Disclosure>
            </section>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setEditor({ end: false, initial: data })}
            >
              Record a running interruption
            </Button>
          )}
        </>
      )}
      {editor && (
        <InterruptionEditor
          end={editor.end}
          initial={editor.initial}
          close={() => setEditor(null)}
          persist={persist}
          reload={async () => {
            const refreshed = await state.refetch()
            if (refreshed.error) throw refreshed.error
            if (!refreshed.data?.data)
              throw new Error('The latest interruption could not be loaded.')
            return refreshed.data.data
          }}
        />
      )}
    </>
  )
}

function InterruptionEditor({
  end,
  initial,
  persist,
  reload,
  close,
}: {
  end: boolean
  initial: RunningInterruptionView
  persist: (expectedVersion: number, episode: Episode | null) => Promise<void>
  reload: () => Promise<RunningInterruptionView>
  close: () => void
}) {
  const latest = initial.interruption
  const [current, setCurrent] = useState<RunningInterruptionView | null>(null)
  const [reason, setReason] = useState<Episode['reason']>(latest?.reason ?? 'schedule')
  const [starts, setStarts] = useState(latest?.starts_on ?? initial.today)
  const [dateKnown, setDateKnown] = useState(latest?.review_on == null)
  const [returnOn, setReturnOn] = useState(latest?.return_on ?? '')
  const [reviewOn, setReviewOn] = useState(latest?.review_on ?? '')
  const save = useMutation({
    mutationFn: () =>
      persist(
        current?.profile_version ?? initial.profile_version,
        end
          ? null
          : {
              reason,
              starts_on: starts,
              return_on: dateKnown ? returnOn : null,
              review_on: dateKnown ? null : reviewOn,
            },
      ),
  })
  const refetch = useMutation({
    mutationFn: reload,
    onSuccess: (response) => {
      setCurrent(response)
      save.reset()
    },
  })
  const conflict = save.error instanceof ApiError && save.error.code === 'version_conflict'
  const title = end
    ? 'End running interruption'
    : latest
      ? 'Edit running interruption'
      : 'Record a running interruption'
  const alreadyEnded = end && current !== null && current.interruption === null
  return (
    <Modal
      label={title}
      close={() => {
        if (!save.isPending) close()
      }}
    >
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault()
          if (!save.isPending && !conflict && !refetch.isPending && !alreadyEnded) save.mutate()
        }}
      >
        <h2>{title}</h2>
        <p>
          {end
            ? 'Clear this interruption from Today. Your accepted workouts and training history will stay as they are.'
            : 'Record when you are unavailable. Your accepted workouts and training history will stay as they are.'}
        </p>
        {!end && (
          <fieldset
            disabled={save.isPending || refetch.isPending}
            className="grid gap-3 sm:grid-cols-2"
          >
            <label className="grid gap-1" htmlFor="interruption-reason">
              Reason
              <NativeSelect
                id="interruption-reason"
                value={reason}
                onChange={(event) => setReason(event.target.value as Episode['reason'])}
              >
                {Object.entries(REASON).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </NativeSelect>
            </label>
            <label className="grid gap-1" htmlFor="interruption-start">
              First day unavailable
              <Input
                id="interruption-start"
                type="date"
                required
                value={starts}
                onChange={(event) => setStarts(event.target.value)}
              />
            </label>
            <label className="grid gap-1" htmlFor="interruption-return-timing">
              Return timing
              <NativeSelect
                id="interruption-return-timing"
                value={dateKnown ? 'dated' : 'open'}
                onChange={(event) => setDateKnown(event.target.value === 'dated')}
              >
                <option value="dated">I know my first available day</option>
                <option value="open">My return date is open</option>
              </NativeSelect>
            </label>
            {dateKnown ? (
              <label className="grid gap-1" htmlFor="interruption-return">
                First day available
                <Input
                  id="interruption-return"
                  type="date"
                  required
                  min={starts ? addDays(starts, 1) : undefined}
                  value={returnOn}
                  onChange={(event) => setReturnOn(event.target.value)}
                />
              </label>
            ) : (
              <label className="grid gap-1" htmlFor="interruption-review">
                Reassess on
                <Input
                  id="interruption-review"
                  type="date"
                  required
                  min={starts || undefined}
                  value={reviewOn}
                  onChange={(event) => setReviewOn(event.target.value)}
                />
              </label>
            )}
          </fieldset>
        )}
        {!end && !dateKnown && <p>Reassess on this date before deciding when to run.</p>}
        {save.error && (
          <div role="alert" className="notice warning">
            <p>
              {conflict
                ? 'The profile changed while this form was open. Your entries are still here.'
                : save.error.message}
            </p>
            {conflict && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={refetch.isPending}
                onClick={() => refetch.mutate()}
              >
                Review latest before saving
              </Button>
            )}
          </div>
        )}
        {refetch.error && <p role="alert">{refetch.error.message}</p>}
        {current && (
          <p role="status">
            {current.interruption
              ? `Currently saved: ${REASON[current.interruption.reason]}, starts ${displayDay(current.interruption.starts_on)}, ${
                  current.interruption.return_on
                    ? `available ${displayDay(current.interruption.return_on)}`
                    : current.interruption.review_on
                      ? `return date open, reassess ${displayDay(current.interruption.review_on)}`
                      : 'return date open'
                }.`
              : 'No interruption is currently saved.'}{' '}
            {!alreadyEnded && 'Review your entries before saving again.'}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          {!alreadyEnded && (
            <Button type="submit" disabled={save.isPending || conflict || refetch.isPending}>
              {save.isPending ? 'Saving…' : end ? 'Confirm end' : 'Save interruption'}
            </Button>
          )}
          <Button type="button" variant="ghost" disabled={save.isPending} onClick={close}>
            {alreadyEnded ? 'Done' : 'Cancel'}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
