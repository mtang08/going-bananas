import { useEffect } from 'react'
import {
  keepPreviousData,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { api, dateLabel, post } from '../api'
import { invalidateKeys, qk, refreshAfterSync } from '../api/queryKeys'
import type { SyncJob, SyncStatus } from '../api/types/sync'
import { QueryState } from './QueryState'
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

export function SyncCard({ compact = false }: { compact?: boolean }) {
  const qc = useQueryClient()
  const status = useQuery({
    queryKey: qk.sync,
    queryFn: () => api<SyncStatus>('/sync/status'),
    placeholderData: keepPreviousData,
  })
  const pending = useCached<string[]>(qk.syncPending, [])
  const outcome = useCached<string | null>(qk.syncOutcome, null)
  const jobs = useQueries({
    queries: pending.map((id) => ({
      queryKey: qk.syncJob(id),
      queryFn: () => api<SyncJob>(`/sync/jobs/${id}`),
      refetchInterval: 2000,
    })),
  })
  const start = useMutation({
    mutationFn: () => post<{ jobs: SyncJob[] }>('/sync', {}),
    onSuccess: (r) => {
      qc.setQueryData(qk.syncOutcome, null)
      qc.setQueryData(
        qk.syncPending,
        r.data.jobs.map((j) => j.id),
      )
      void qc.invalidateQueries({ queryKey: qk.sync, exact: true })
    },
  })
  const finished =
    pending.length > 0 &&
    jobs.every((j) => j.data && ['succeeded', 'failed'].includes(j.data.data.status))
  useEffect(() => {
    if (!finished) return
    const failed = jobs.some((j) => j.data?.data.status === 'failed')
    qc.setQueryData(qk.syncPending, [])
    qc.setQueryData(
      qk.syncOutcome,
      failed
        ? 'One or more datasets failed. Check the dataset status and retry.'
        : 'Sync finished. Training data has been refreshed.',
    )
    void qc.invalidateQueries({ queryKey: qk.sync, exact: true })
    invalidateKeys(qc, refreshAfterSync)
  }, [finished, jobs, qc])

  const real = status.data?.mode === 'real'
  const datasets = status.data?.data.datasets ?? []
  const activeJobs = status.data?.data.active_jobs ?? []
  const lastSuccess = datasets.reduce<string | null>(
    (latest, d) =>
      d.last_success_at && (!latest || Date.parse(d.last_success_at) > Date.parse(latest))
        ? d.last_success_at
        : latest,
    null,
  )
  const lastText = lastSuccess ? `Last sync ${relativeTime(lastSuccess)}` : 'Not synced yet'
  const busy = start.isPending || pending.length > 0
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

  if (compact)
    return (
      <div className="flex flex-wrap items-center gap-3 text-sm" data-testid="sync-compact">
        {status.error ? (
          <span className="error-text">Sync status unavailable</span>
        ) : (
          <span>{lastText}</span>
        )}
        {button}
        {messages}
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
        {messages}
        {pending.length > 0 && (
          <div className="sync-jobs">
            {jobs.map((job, i) => (
              <small key={pending[i]}>
                {job.data?.data.dataset || 'Dataset'}:{' '}
                {stateLabel(job.data?.data.status || 'queued')}
              </small>
            ))}
          </div>
        )}
        {pending.length === 0 && activeJobs.length > 0 && (
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
