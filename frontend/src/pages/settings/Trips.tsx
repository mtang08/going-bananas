import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, patch, query } from '../../api/client'
import { invalidateKeys, qk } from '../../api/queryKeys'
import type { Trip, TripPatch, TripStatus } from '../../api/types/travel'
import { QueryState } from '../../components/QueryState'
import { Badge, Button } from '../../components/ui'
import { dateLabel, localDate } from '../../lib/format'
import { TripForm, tripWriteError } from './TripForm'

const ALL_STATUSES = 'pending,needs_review,confirmed,dismissed'
const STATUS_BADGE: Record<TripStatus, string> = {
  pending: 'Possible trip',
  needs_review: 'Calendar changed',
  confirmed: 'Confirmed',
  dismissed: 'Dismissed',
}
const range = (start: string, end: string | null | undefined) =>
  end ? `${dateLabel(start)}–${dateLabel(end)}` : `${dateLabel(start)} (end unknown)`
const localTime = (iso: string | null) =>
  iso ? `${dateLabel(iso.slice(0, 10))} ${iso.slice(11, 16)}` : 'Time unavailable'

type TripChange = Omit<TripPatch, 'expected_version'>

function actions(trip: Trip): [string, TripChange][] {
  const dismiss: [string, TripChange] = ['Dismiss', { status: 'dismissed' }]
  switch (trip.status) {
    case 'pending':
      return [['Confirm', { status: 'confirmed' }], dismiss]
    case 'needs_review':
      return [
        ['Use calendar version', { accept_detected: true, status: 'confirmed' }],
        ['Keep mine', { status: 'confirmed' }],
        dismiss,
      ]
    case 'confirmed':
      return [dismiss]
    case 'dismissed':
      return [['Restore', { status: trip.source === 'manual' ? 'confirmed' : 'pending' }]]
  }
}

export function Trips({ homeTimezone }: { homeTimezone: string }) {
  const qc = useQueryClient()
  const [showDismissed, setShowDismissed] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const trips = useQuery({
    queryKey: qk.trips('default', 'default'),
    queryFn: () => api<{ items: Trip[] }>(`/trips${query({ status: ALL_STATUSES })}`),
  })
  const update = useMutation({
    mutationFn: ({ trip, change }: { trip: Trip; change: TripChange }) =>
      patch<Trip>(`/trips/${encodeURIComponent(trip.id)}`, {
        expected_version: trip.version,
        ...change,
      }),
    onSettled: () => invalidateKeys(qc, [qk.tripsAll, qk.proposals]),
  })

  const today = localDate()
  const items = [...(trips.data?.data?.items ?? [])].sort((a, b) =>
    a.start_date.localeCompare(b.start_date),
  )
  const review = items.filter((trip) => trip.status === 'pending' || trip.status === 'needs_review')
  const confirmed = items.filter((trip) => trip.status === 'confirmed')
  const upcoming = confirmed.filter((trip) => (trip.end_date ?? trip.start_date) >= today)
  const recent = confirmed.filter((trip) => (trip.end_date ?? trip.start_date) < today).reverse()
  const dismissed = items.filter((trip) => trip.status === 'dismissed')
  const groups = [
    { name: 'To review', items: review },
    { name: 'Upcoming', items: upcoming },
    { name: 'Recent', items: recent },
    { name: 'Dismissed', items: showDismissed ? dismissed : [] },
  ]
  const edit = (id: string) => {
    setSaved(false)
    setEditing(id)
  }
  const onSaved = () => {
    setEditing(null)
    setSaved(true)
  }
  const onCancel = () => setEditing(null)

  return (
    <section className="space-y-3">
      <h3>Trips</h3>
      <QueryState
        loading={trips.isPending}
        error={trips.error}
        stale={!!trips.data}
        retry={() => void trips.refetch()}
      >
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="add-trip-button"
          onClick={() => edit('new')}
        >
          Add trip
        </Button>
        {editing === 'new' && (
          <TripForm trip={null} homeTimezone={homeTimezone} onSaved={onSaved} onCancel={onCancel} />
        )}
        {!review.length && !confirmed.length && (
          <p>No trips yet. Sync your calendar or add a trip. App dates use {homeTimezone}.</p>
        )}
        {groups.map(
          ({ name, items }) =>
            items.length > 0 && (
              <section key={name}>
                <h4>{name}</h4>
                <ul className="space-y-3">
                  {items.map((trip) => (
                    <li
                      className="space-y-2"
                      data-testid="trip-row"
                      data-status={trip.status}
                      key={trip.id}
                    >
                      <p>
                        <strong>{trip.destination_label ?? 'Unnamed destination'}</strong> ·{' '}
                        {range(trip.start_date, trip.end_date)} · {trip.destination_tz}
                      </p>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant={trip.status === 'pending' ? 'outline' : 'secondary'}>
                          {STATUS_BADGE[trip.status]}
                        </Badge>
                        {trip.source === 'manual' ? (
                          <Badge variant="secondary">Added by you</Badge>
                        ) : (
                          <Badge variant="outline">Confidence: {trip.confidence}</Badge>
                        )}
                      </div>
                      {trip.status === 'needs_review' &&
                        trip.review_reason === 'source_changed' && (
                          <p>
                            Calendar changed: now{' '}
                            {range(
                              trip.detected.start_date ?? trip.start_date,
                              trip.detected.end_date,
                            )}{' '}
                            · {trip.detected.destination_label ?? trip.detected.destination_tz}
                          </p>
                        )}
                      {trip.status === 'needs_review' &&
                        trip.review_reason === 'source_removed' && (
                          <p>Calendar changed: its flights were removed or recategorized.</p>
                        )}
                      {trip.legs.length > 0 && (
                        <ul>
                          {trip.legs.map((leg) => (
                            <li key={leg.event_id}>
                              Departs {localTime(leg.depart_local)} ({leg.depart_tz}) → arrives{' '}
                              {localTime(leg.arrive_local)} ({leg.arrive_tz})
                              {leg.flight_code && ` · ${leg.flight_code}`}
                              {leg.removed && ' · removed from calendar'}
                            </li>
                          ))}
                        </ul>
                      )}
                      <div className="flex flex-wrap gap-2">
                        {trip.status !== 'dismissed' && (
                          <Button variant="link" type="button" onClick={() => edit(trip.id)}>
                            Edit
                          </Button>
                        )}
                        {actions(trip).map(([label, change]) => (
                          <Button
                            key={label}
                            variant="outline"
                            size="sm"
                            type="button"
                            disabled={update.isPending}
                            onClick={() => update.mutate({ trip, change })}
                          >
                            {label}
                          </Button>
                        ))}
                      </div>
                      {editing === trip.id && (
                        <TripForm
                          trip={trip}
                          homeTimezone={homeTimezone}
                          onSaved={onSaved}
                          onCancel={onCancel}
                        />
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            ),
        )}
        {dismissed.length > 0 && (
          <Button variant="link" type="button" onClick={() => setShowDismissed((value) => !value)}>
            {showDismissed ? 'Hide dismissed' : 'Show dismissed'}
          </Button>
        )}
        {update.error && (
          <p className="error-text" role="alert">
            {tripWriteError(update.error)}
          </p>
        )}
        {saved && (
          <p className="success-text" role="status">
            Trip saved.
          </p>
        )}
      </QueryState>
    </section>
  )
}
