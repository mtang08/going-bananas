import { useEffect, useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { ApiError, api, post } from '../api/client'
import { dateLabel, type Unit } from '../lib/format'
import { invalidateKeys, qk, refreshAfterSync } from '../api/queryKeys'
import type { SyncJob, SyncStatus } from '../api/types/sync'
import { QueryState } from './QueryState'
import { TreadmillReviewDialog } from './TreadmillReviewDialog'
import { relativeTime, stateLabel } from './shared'
import { Badge, Button, Card } from './ui'

function useCached<T>(key: readonly unknown[], fallback: T): T {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: key,
    queryFn: () => qc.getQueryData<T>(key) ?? fallback,
    initialData: fallback,
    staleTime: Infinity,
    gcTime: Infinity,
  })
  return data === undefined ? fallback : data
}

async function loadStatus(ids: string[]) {
  const status = await api<SyncStatus>('/sync/status')
  const active = status.data.active_jobs
  if (!ids.length || active.some((job) => ids.includes(job.id))) {
    return { status, results: null }
  }
  const results = await Promise.all(
    ids.map(async (id) => {
      try {
        return (await api<SyncJob>(`/sync/jobs/${id}`)).data.status
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return 'unavailable'
        throw error
      }
    }),
  )
  return { status, results }
}

export function SyncCard({ compact = false, unit = 'mi' }: { compact?: boolean; unit?: Unit }) {
  const qc = useQueryClient()
  const [reviewId, setReviewId] = useState<string | null>(null)
  const pending = useCached<string[]>(qk.syncPending, [])
  const outcome = useCached<string | null>(qk.syncOutcome, null)
  const statusKey = pending.length ? qk.syncBatch(pending) : qk.sync
  const status = useQuery({
    queryKey: statusKey,
    queryFn: () => loadStatus(pending),
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
    refetchInterval: ({ state }) =>
      !state.error && !state.data?.results && state.data?.status.data.active_jobs.length
        ? 3000
        : false,
  })
  const start = useMutation({
    mutationFn: () => post<{ jobs: SyncJob[] }>('/sync', {}),
    onSuccess: (r) => {
      qc.setQueryData(qk.syncOutcome, null)
      qc.setQueryData(
        qk.syncPending,
        r.data.jobs.map((j) => j.id),
      )
    },
  })
  const completed = status.isPlaceholderData ? null : status.data
  useEffect(() => {
    const results = completed?.results
    if (!pending.length || !results) return
    const failed = results.includes('failed')
    const partial = results.includes('partial')
    const unavailable = results.includes('unavailable')
    qc.setQueryData(qk.sync, { status: completed.status, results: null })
    qc.setQueryData(qk.syncPending, [])
    qc.setQueryData(
      qk.syncOutcome,
      failed
        ? 'One or more datasets failed. Check the dataset status and retry.'
        : unavailable
          ? 'A sync job is unavailable. Check the dataset status.'
          : partial
            ? 'Sync finished with incomplete data. Check the dataset status.'
            : completed.status.data.pending_treadmill_runs?.length
              ? 'Sync finished. Review treadmill runs to import them.'
              : 'Sync finished. Training data has been refreshed.',
    )
    invalidateKeys(qc, refreshAfterSync)
  }, [pending.length, completed, qc])

  const real = status.data?.status.mode === 'real'
  const datasets = status.data?.status.data.datasets ?? []
  const activeJobs = status.data?.status.data.active_jobs ?? []
  const pendingRuns = status.data?.status.data.pending_treadmill_runs ?? []
  const lastSuccess = datasets.reduce<string | null>(
    (latest, d) =>
      d.last_success_at && (!latest || Date.parse(d.last_success_at) > Date.parse(latest))
        ? d.last_success_at
        : latest,
    null,
  )
  const lastText = lastSuccess ? `Last sync ${relativeTime(lastSuccess)}` : 'Not synced yet'
  const busy = start.isPending || pending.length > 0 || activeJobs.length > 0
  const button = real && (
    <Button variant="outline" size="sm" onClick={() => start.mutate()} disabled={busy}>
      <RefreshCw size={15} /> {busy ? 'Sync in progress' : 'Sync now'}
    </Button>
  )
  const messages = (
    <>
      {start.error && (
        <p className="error-text" role="alert">
          {start.error.message}
        </p>
      )}
      {outcome && (
        <p role="status" className={outcome.startsWith('One') ? 'error-text' : 'success-text'}>
          {outcome}
        </p>
      )}
    </>
  )
  const reviews = (
    <>
      {pendingRuns.length > 0 && (
        <div
          className="flex w-full flex-wrap gap-2"
          role="group"
          aria-label="Treadmill runs awaiting review"
        >
          {pendingRuns.map((run) => (
            <Button
              key={run.id}
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setReviewId(run.id)}
            >
              Review treadmill run · {dateLabel(run.local_date)}
            </Button>
          ))}
        </div>
      )}
      {reviewId && (
        <TreadmillReviewDialog
          key={reviewId}
          id={reviewId}
          unit={unit}
          close={() => setReviewId(null)}
          onImported={() => {
            qc.setQueryData(qk.syncOutcome, 'Treadmill run imported.')
            qc.setQueryData<Awaited<ReturnType<typeof loadStatus>>>(statusKey, (current) => {
              if (!current) return current
              const { status } = current
              return {
                ...current,
                status: {
                  ...status,
                  data: {
                    ...status.data,
                    pending_treadmill_runs: status.data.pending_treadmill_runs.filter(
                      (run) => run.id !== reviewId,
                    ),
                  },
                },
              }
            })
            void status.refetch()
            invalidateKeys(qc, refreshAfterSync)
            setReviewId(null)
          }}
        />
      )}
    </>
  )

  if (compact)
    return (
      <div className="flex flex-wrap items-center gap-3 text-sm" data-testid="sync-compact">
        {status.error ? (
          <>
            <span className="error-text">Sync status unavailable</span>
            <Button type="button" variant="outline" size="sm" onClick={() => void status.refetch()}>
              Retry status
            </Button>
          </>
        ) : (
          <span>{lastText}</span>
        )}
        {button}
        {messages}
        {reviews}
      </div>
    )

  return (
    <Card data-testid="sync-card">
      <h2>Sync</h2>
      <QueryState
        loading={status.isPending}
        error={status.error}
        stale={!!status.data}
        retry={() => void status.refetch()}
      >
        <p>{lastText}</p>
        {button}
        {status.error && (
          <Button type="button" variant="outline" size="sm" onClick={() => void status.refetch()}>
            Retry status
          </Button>
        )}
        {messages}
        {reviews}
        {activeJobs.length > 0 && (
          <div className="sync-jobs">
            {activeJobs.map((job) => (
              <small key={job.id}>
                {job.dataset}: {stateLabel(job.status)}
              </small>
            ))}
          </div>
        )}
        {datasets.length ? (
          <div className="sync-list">
            {datasets.map((d) => (
              <div className="sync-row" key={d.dataset}>
                <strong>{d.dataset.replaceAll('_', ' ')}</strong>
                <Badge className="status-chip">{stateLabel(d.status)}</Badge>
                <small>
                  Last success:{' '}
                  {d.last_success_at ? new Date(d.last_success_at).toLocaleString() : 'never'} ·
                  Newest observation:{' '}
                  {d.newest_observation_at
                    ? dateLabel(d.newest_observation_at.slice(0, 10))
                    : 'unknown'}
                </small>
              </div>
            ))}
          </div>
        ) : (
          <p>No dataset has a completed local sync.</p>
        )}
      </QueryState>
    </Card>
  )
}
