import { useState, type FormEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ApiError, api, post } from '../api/client'
import { qk } from '../api/queryKeys'
import type { TreadmillReview } from '../api/types/sync'
import {
  clockToSeconds,
  dateLabel,
  fmtClock,
  fmtDistance,
  statusText,
  type Unit,
} from '../lib/format'
import { Modal } from './Modal'
import { QueryState } from './QueryState'
import { Button, Input } from './ui'

const KM_PER_MILE = 1.609344

export function TreadmillReviewDialog({
  id,
  unit,
  close,
  onImported,
}: {
  id: string
  unit: Unit
  close: () => void
  onImported: () => void
}) {
  const [edits, setEdits] = useState<Record<number, string>>({})
  const endpoint = `/sync/treadmill-review/${encodeURIComponent(id)}`
  const preview = useQuery({
    queryKey: qk.treadmillReview(id),
    queryFn: () => api<TreadmillReview>(endpoint),
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    gcTime: 0,
  })
  const confirm = useMutation({
    mutationFn: (body: {
      preview_token: string
      paces: { lap_index: number; pace_seconds_per_mile: number }[]
    }) => post<{ activity_id: string }>(endpoint, body),
    onSuccess: onImported,
  })
  const run = preview.data?.data
  const needsReload =
    confirm.error instanceof ApiError && confirm.error.code === 'treadmill_review_reload_required'
  const paceEdits =
    run?.intervals.flatMap(({ lap_index }) => {
      const text = edits[lap_index]?.trim()
      if (!text) return []
      return [
        { lap_index, seconds: /^\d+:\d{2}$/.test(text) ? clockToSeconds(text) || null : null },
      ]
    }) ?? []
  const invalidPace = paceEdits.some(({ seconds }) => seconds === null)

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!run || invalidPace || confirm.isPending || preview.isFetching || needsReload) return
    confirm.mutate({
      preview_token: run.preview_token,
      paces: paceEdits.flatMap(({ lap_index, seconds }) =>
        seconds === null
          ? []
          : [{ lap_index, pace_seconds_per_mile: unit === 'mi' ? seconds : seconds * KM_PER_MILE }],
      ),
    })
  }

  return (
    <Modal
      label="Review treadmill run"
      description="Check the recorded paces before importing this run."
      className="sm:max-w-xl"
      close={() => {
        if (!confirm.isPending) close()
      }}
    >
      <QueryState
        loading={preview.isPending}
        error={preview.error}
        stale={!!run}
        retry={() => void preview.refetch()}
      >
        {run && (
          <form className="mt-4 grid gap-4" onSubmit={submit}>
            <div>
              <h2>{run.title || 'Treadmill run'}</h2>
              <p className="text-sm text-muted-foreground">
                {dateLabel(run.local_date)} · {fmtClock(run.timer_s)} ·{' '}
                {fmtDistance(run.distance_m, unit)}
              </p>
            </div>
            {run.intervals.length ? (
              <fieldset disabled={confirm.isPending} className="grid gap-3">
                <legend className="mb-2 font-semibold">Intervals</legend>
                <p className="text-sm text-muted-foreground">
                  Enter a pace in minutes and seconds per {unit} for any lap you want to correct.
                  Leave an entry blank to keep Garmin’s pace.
                </p>
                {run.intervals.map((lap) => {
                  const pace = lap.recorded_pace_seconds_per_mile
                  const recorded = pace === null ? null : unit === 'mi' ? pace : pace / KM_PER_MILE
                  const invalid = paceEdits.some(
                    ({ lap_index, seconds }) => lap_index === lap.lap_index && seconds === null,
                  )
                  return (
                    <label key={lap.lap_index} className="grid gap-1 border-t border-border pt-3">
                      <span className="text-sm font-medium">
                        Lap {lap.lap_index + 1}
                        {lap.intensity && ` · ${statusText(lap.intensity)}`} ·{' '}
                        {fmtClock(lap.timer_s)}
                      </span>
                      <span className="text-sm text-muted-foreground">
                        {recorded === null
                          ? 'Garmin pace unavailable'
                          : `Garmin pace ${fmtClock(recorded)} /${unit}`}
                      </span>
                      <Input
                        className="max-w-32"
                        type="text"
                        aria-label={`Lap ${lap.lap_index + 1} corrected pace per ${unit}`}
                        aria-invalid={invalid}
                        placeholder="m:ss"
                        value={edits[lap.lap_index] ?? ''}
                        onChange={(event) =>
                          setEdits({ ...edits, [lap.lap_index]: event.target.value })
                        }
                      />
                    </label>
                  )
                })}
              </fieldset>
            ) : (
              <p>No interval paces to review. Confirm to import the recorded run.</p>
            )}
            {invalidPace && (
              <p className="error-text" role="alert">
                Enter each corrected pace as minutes and two-digit seconds, for example 8:30.
              </p>
            )}
            {confirm.error && (
              <p className="error-text" role="alert">
                {confirm.error.message}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button variant="outline" type="button" disabled={confirm.isPending} onClick={close}>
                Review later
              </Button>
              {needsReload && (
                <Button
                  variant="outline"
                  type="button"
                  disabled={preview.isFetching}
                  onClick={async () => {
                    const result = await preview.refetch()
                    if (result.isSuccess) {
                      setEdits({})
                      confirm.reset()
                    }
                  }}
                >
                  Reload run
                </Button>
              )}
              <Button
                type="submit"
                disabled={invalidPace || confirm.isPending || preview.isFetching || needsReload}
              >
                {confirm.isPending ? 'Importing…' : 'Confirm and import'}
              </Button>
            </div>
          </form>
        )}
      </QueryState>
    </Modal>
  )
}
