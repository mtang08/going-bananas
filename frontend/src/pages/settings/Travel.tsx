import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { api, post } from '../../api/client'
import { invalidateKeys, qk } from '../../api/queryKeys'
import type { GcalStatus, GcalSyncResult } from '../../api/types/travel'
import { QueryState } from '../../components/QueryState'
import { relativeTime } from '../../components/shared'
import { Button, Disclosure } from '../../components/ui'
import { CalendarEvents } from './CalendarEvents'
import { Trips } from './Trips'

export function syncSummary(result: GcalSyncResult): string {
  const c = result.sync.counters
  const review = result.trips.created + result.trips.flagged
  const trips =
    review === 0
      ? 'No trips to review.'
      : review === 1
        ? '1 trip to review.'
        : `${review} trips to review.`
  return `Synced: ${c.created} new, ${c.changed} changed, ${c.removed} removed. ${trips}`
}

export function Travel({ homeTimezone }: { homeTimezone: string }) {
  const qc = useQueryClient()
  const status = useQuery({
    queryKey: qk.gcalStatus,
    queryFn: () => api<GcalStatus>('/google-calendar/status'),
  })
  const sync = useMutation({
    mutationFn: () => post<GcalSyncResult>('/google-calendar/sync', {}),
    onSettled: () =>
      invalidateKeys(qc, [qk.gcal, qk.tripsAll, qk.proposals, qk.runningInterruption]),
  })
  const real = status.data?.mode === 'real'
  const s = status.data?.data
  const line = !s?.connected
    ? 'Not connected — see the setup runbook.'
    : s.last_success_at
      ? `Last calendar sync ${relativeTime(s.last_success_at)}`
      : 'Connected, not synced yet.'
  return (
    <Disclosure variant="card" className="training-disclosure" data-testid="travel-section">
      <summary>Travel and Google Calendar</summary>
      <QueryState
        loading={status.isPending}
        error={status.error}
        stale={!!status.data}
        retry={() => void status.refetch()}
      >
        <p>{line}</p>
        {s?.last_sync?.status === 'failed' && (
          <p className="error-text">The last calendar sync attempt failed.</p>
        )}
        <p className="notice muted">
          Dates in the app use your home timezone, {homeTimezone}. Flight times use the timezones
          available from your calendar.
        </p>
        {real ? (
          <Button
            variant="outline"
            size="sm"
            type="button"
            data-testid="gcal-sync-button"
            disabled={sync.isPending}
            onClick={() => sync.mutate()}
          >
            <RefreshCw size={15} /> {sync.isPending ? 'Syncing calendar…' : 'Sync calendar'}
          </Button>
        ) : (
          <p className="notice muted">Calendar sync runs in real mode only.</p>
        )}
        {sync.error && (
          <p className="error-text" role="alert">
            {sync.error.message}
          </p>
        )}
        {sync.data && (
          <p className="success-text" role="status">
            {syncSummary(sync.data.data)}
          </p>
        )}
        <Trips homeTimezone={homeTimezone} />
        <Disclosure className="mt-4">
          <summary>Calendar events</summary>
          <CalendarEvents homeTimezone={homeTimezone} />
        </Disclosure>
      </QueryState>
    </Disclosure>
  )
}
