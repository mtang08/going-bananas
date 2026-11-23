import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, patch, query } from '../../api/client'
import { invalidateKeys, qk } from '../../api/queryKeys'
import {
  CATEGORY_LABELS,
  type CalendarEvent,
  type EventCategory,
  type EventPatchResult,
} from '../../api/types/travel'
import { QueryState } from '../../components/QueryState'
import { Badge, NativeSelect } from '../../components/ui'
import { dateLabel } from '../../lib/format'
import { Select } from './shared'

const FILTERS: Record<string, string> = { travel: 'Travel', all: 'All', ...CATEGORY_LABELS }

export function CalendarEvents({ homeTimezone }: { homeTimezone: string }) {
  const qc = useQueryClient()
  const [filter, setFilter] = useState('travel')
  const events = useQuery({
    queryKey: qk.gcalEvents('default', 'default', filter),
    queryFn: () =>
      api<{ items: CalendarEvent[] }>(
        `/google-calendar/events${query({ category: filter === 'all' ? undefined : filter, include_removed: 'true' })}`,
      ),
  })
  const update = useMutation({
    mutationFn: ({ event, category }: { event: CalendarEvent; category: EventCategory | null }) =>
      patch<EventPatchResult>(`/google-calendar/events/${encodeURIComponent(event.id)}`, {
        expected_version: event.version,
        category,
      }),
    onSettled: () => invalidateKeys(qc, [qk.gcal, qk.tripsAll, qk.proposals]),
  })

  const grouped = new Map<string, CalendarEvent[]>()
  for (const event of events.data?.data?.items ?? []) {
    const day = grouped.get(event.local_date)
    if (day) day.push(event)
    else grouped.set(event.local_date, [event])
  }
  const timeFormat = new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    timeZone: homeTimezone,
  })
  const changed = update.data && Object.values(update.data.data.trips).some((count) => count > 0)
  const error =
    update.error instanceof ApiError && update.error.code === 'version_conflict'
      ? 'This event changed since it loaded. The list was refreshed; try again.'
      : update.error?.message

  return (
    <div className="space-y-3">
      <Select id="gcal-filter" label="Show" value={filter} options={FILTERS} onChange={setFilter} />
      <QueryState
        loading={events.isPending}
        error={events.error}
        stale={!!events.data}
        retry={() => void events.refetch()}
      >
        {grouped.size === 0 && <p>No calendar events in this window.</p>}
        {[...grouped].map(([day, items]) => (
          <section key={day}>
            <h4>{dateLabel(day, { weekday: 'short', month: 'short', day: 'numeric' })}</h4>
            <ul className="space-y-3">
              {items.map((event) => (
                <li key={event.id} data-testid="gcal-event-row" data-category={event.category}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span>
                      {event.all_day || !event.start_at
                        ? 'All day'
                        : timeFormat.format(new Date(event.start_at))}{' '}
                      · {event.summary ?? '(no title)'}
                    </span>
                    <Badge variant="outline">{event.busy ? 'Busy' : 'Free'}</Badge>
                    {event.removed && <Badge variant="secondary">Removed</Badge>}
                    {event.trip_id && (
                      <small>
                        Trip leg{event.destination_label ? ` · ${event.destination_label}` : ''}
                      </small>
                    )}
                  </div>
                  <NativeSelect
                    aria-label={`Category for ${event.summary ?? 'untitled event'}`}
                    value={event.category_source === 'auto' ? '' : event.category}
                    disabled={update.isPending || event.removed}
                    onChange={(e) =>
                      update.mutate({
                        event,
                        category: (e.target.value || null) as EventCategory | null,
                      })
                    }
                  >
                    <option value="">Automatic ({CATEGORY_LABELS[event.auto_category]})</option>
                    {Object.entries(CATEGORY_LABELS).map(([category, label]) => (
                      <option key={category} value={category}>
                        {label}
                      </option>
                    ))}
                  </NativeSelect>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {update.data && (
          <p className="success-text" role="status">
            Category saved.{changed ? ' Trips changed; check the trip list.' : ''}
          </p>
        )}
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
      </QueryState>
    </div>
  )
}
