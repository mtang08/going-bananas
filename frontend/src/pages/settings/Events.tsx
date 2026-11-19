import { Button, Card, Input, NativeSelect } from '../../components/ui'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  api,
  post,
  patch,
  qk,
  invalidateKeys,
  dateLabel,
  fmtDistance,
  fmtClock,
  clockToSeconds,
  EVENT_PRIORITY_LABELS,
  type RaceEvent,
  type EventPriority,
  type EventStatus,
  type Unit,
} from '../../api'
import { QueryState } from '../../components/QueryState'
import { ErrorText, Select } from './shared'

const RACE_DISTANCES: Record<string, string> = {
  '1609.344': '1 mile',
  '5000': '5K',
  '8000': '8K',
  '10000': '10K',
  '15000': '15K',
  '16093.44': '10 miles',
  '21097.5': 'Half marathon',
  '42195': 'Marathon',
}
export function Events({ unit }: { unit: Unit }) {
  const qc = useQueryClient(),
    query = useQuery({ queryKey: qk.events, queryFn: () => api<{ items: RaceEvent[] }>('/events') })
  const [editing, setEditing] = useState<RaceEvent | null>(null),
    [name, setName] = useState(''),
    [day, setDay] = useState(''),
    [distance, setDistance] = useState(''),
    [distanceEdited, setDistanceEdited] = useState(false)
  const [priority, setPriority] = useState<EventPriority>('optional'),
    [status, setStatus] = useState<EventStatus>('planned'),
    [result, setResult] = useState(''),
    [resultEdited, setResultEdited] = useState(false)
  const reset = () => {
    setEditing(null)
    setName('')
    setDay('')
    setDistance('')
    setDistanceEdited(false)
    setResult('')
    setResultEdited(false)
    setPriority('optional')
    setStatus('planned')
  }
  const save = useMutation({
    mutationFn: () => {
      const result_s =
        status !== 'completed'
          ? null
          : editing && !resultEdited
            ? editing.result_s
            : clockToSeconds(result)
      if (status === 'completed' && result.trim() && result_s === null)
        throw new Error('Enter the result as h:mm:ss or m:ss.')
      const distance_m =
        editing && !distanceEdited ? editing.distance_m : distance === '' ? null : Number(distance)
      if (distance_m !== null && (!Number.isFinite(distance_m) || distance_m <= 0))
        throw new Error('Enter a positive distance.')
      const body = { name: name.trim(), event_date: day, distance_m, priority, status, result_s }
      return editing
        ? patch(`/events/${encodeURIComponent(editing.id)}`, {
            expected_version: editing.version,
            ...body,
          })
        : post('/events', body)
    },
    onSuccess: () => {
      invalidateKeys(qc, [qk.events, qk.proposals])
      reset()
    },
  })
  return (
    <Card>
      <h2>Events</h2>
      <p>Events feed the next coach review; the calendar does not change automatically.</p>
      <QueryState
        loading={query.isPending}
        error={query.error}
        stale={!!query.data}
        retry={() => {
          void query.refetch()
        }}
      >
        {!query.data?.data.items.length && <p>No events yet.</p>}
        {query.data?.data.items.map((event) => (
          <div key={event.id}>
            {event.name} ·{' '}
            {dateLabel(event.event_date, { month: 'short', day: 'numeric', year: 'numeric' })} ·{' '}
            {event.distance_m === null ? 'distance not set' : fmtDistance(event.distance_m, unit)} ·{' '}
            {EVENT_PRIORITY_LABELS[event.priority]} · {event.status}
            {event.result_s !== null && ` · result ${fmtClock(event.result_s)}`}{' '}
            <Button
              variant="link"
              onClick={() => {
                setEditing(event)
                setName(event.name)
                setDay(event.event_date)
                setDistance(event.distance_m === null ? '' : String(event.distance_m))
                setDistanceEdited(false)
                setPriority(event.priority)
                setStatus(event.status)
                setResult(event.result_s === null ? '' : fmtClock(event.result_s))
                setResultEdited(false)
                save.reset()
              }}
            >
              Edit
            </Button>
          </div>
        ))}
        <form
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <fieldset disabled={save.isPending}>
            <label htmlFor="event-name">Event</label>
            <Input
              id="event-name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <label htmlFor="event-date">Date</label>
            <Input
              id="event-date"
              type="date"
              required
              value={day}
              onChange={(e) => setDay(e.target.value)}
            />
            <label htmlFor="event-distance">Distance</label>
            <NativeSelect
              id="event-distance"
              value={distance}
              onChange={(e) => {
                setDistance(e.target.value)
                setDistanceEdited(true)
              }}
            >
              <option value="">Distance not set</option>
              {Object.entries(RACE_DISTANCES)
                .sort(([a], [b]) => Number(a) - Number(b))
                .map(([meters, label]) => (
                  <option key={meters} value={meters}>
                    {label}
                  </option>
                ))}
              {editing?.distance_m != null && !RACE_DISTANCES[String(editing.distance_m)] && (
                <option value={String(editing.distance_m)}>
                  Existing distance ({fmtDistance(editing.distance_m, unit)})
                </option>
              )}
            </NativeSelect>
            <Select
              id="event-priority"
              label="Priority"
              value={priority}
              options={EVENT_PRIORITY_LABELS}
              onChange={(v) => setPriority(v as EventPriority)}
            />
            <Select
              id="event-status"
              label="Status"
              value={status}
              options={{
                planned: 'Planned',
                registered: 'Registered',
                completed: 'Completed',
                cancelled: 'Cancelled',
              }}
              onChange={(v) => setStatus(v as EventStatus)}
            />
            {status === 'completed' && (
              <>
                <label htmlFor="event-result">Result (h:mm:ss or m:ss)</label>
                <Input
                  id="event-result"
                  value={result}
                  onChange={(e) => {
                    setResult(e.target.value)
                    setResultEdited(true)
                  }}
                />
              </>
            )}
            <Button type="submit">{editing ? 'Save event' : 'Add event'}</Button>
            {editing && (
              <Button variant="link" type="button" onClick={reset}>
                Cancel
              </Button>
            )}
          </fieldset>
        </form>
        <ErrorText error={save.error} />
        {save.isSuccess && (
          <p className="success-text" role="status">
            Event saved.
          </p>
        )}
      </QueryState>
    </Card>
  )
}
