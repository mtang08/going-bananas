import { Badge, Button, Card, Input, NativeSelect } from '../../components/ui'
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post, patch, put } from '../../api/client'
import { qk, invalidateKeys } from '../../api/queryKeys'
import { dateLabel, fmtDistance, fmtClock, clockToSeconds, type Unit } from '../../lib/format'
import {
  EVENT_PURPOSE_LABELS,
  type RaceEvent,
  type EventPurpose,
  type EventStatus,
} from '../../api/types/blocks'
import { QueryState } from '../../components/QueryState'
import { ErrorText, Select } from './shared'

const RACE_DISTANCES: Record<string, string> = {
  '1609': '1 mile',
  '5000': '5K',
  '8000': '8K',
  '10000': '10K',
  '15000': '15K',
  '16093': '10 miles',
  '21098': 'Half marathon',
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
  const [purpose, setPurpose] = useState<EventPurpose>('training'),
    [goalTime, setGoalTime] = useState(''),
    [goalEdited, setGoalEdited] = useState(false),
    [status, setStatus] = useState<EventStatus>('planned'),
    [result, setResult] = useState(''),
    [resultEdited, setResultEdited] = useState(false)
  const items = query.data?.data.items ?? []
  const upcoming = items
    .filter((event) => event.rank !== null)
    .sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0))
  const past = items
    .filter((event) => event.rank === null)
    .sort((a, b) => b.event_date.localeCompare(a.event_date))
  const rankList = useRef<HTMLOListElement>(null)
  const focusTarget = useRef<{ id: string; direction: 'up' | 'down' } | null>(null)
  const [moved, setMoved] = useState('')
  const move = useMutation({
    mutationFn: ({ event, to }: { event: RaceEvent; direction: 'up' | 'down'; to: number }) => {
      const next = upcoming.filter((item) => item.id !== event.id)
      next.splice(to, 0, event)
      return put('/events/order', {
        items: next.map((item) => ({ id: item.id, expected_version: item.version })),
      })
    },
    onMutate: ({ event, direction }) => {
      setMoved('')
      focusTarget.current = { id: event.id, direction }
    },
    onSuccess: (_result, { event, to }) => setMoved(`${event.name} moved to rank ${to + 1}`),
    onSettled: () =>
      Promise.all(
        [qk.events, qk.blocks, qk.proposals].map((queryKey) => qc.invalidateQueries({ queryKey })),
      ),
  })
  const busy = move.isPending || query.isFetching
  useEffect(() => {
    const target = focusTarget.current
    if (!target || busy) return
    const row = Array.from(rankList.current?.children ?? []).find(
      (child) => child.getAttribute('data-event-id') === target.id,
    )
    const buttons = Array.from(
      row?.querySelectorAll<HTMLButtonElement>('button[data-move]:enabled') ?? [],
    )
    const button = buttons.find((item) => item.dataset.move === target.direction) ?? buttons[0]
    button?.focus()
    focusTarget.current = null
  }, [busy])
  const reset = () => {
    setEditing(null)
    setName('')
    setDay('')
    setDistance('')
    setDistanceEdited(false)
    setResult('')
    setResultEdited(false)
    setPurpose('training')
    setGoalTime('')
    setGoalEdited(false)
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
      const goal_time_s =
        editing && !goalEdited ? editing.goal_time_s : clockToSeconds(goalTime.trim())
      if (goalEdited && goalTime.trim() && goal_time_s === null)
        throw new Error('Enter the goal time as h:mm:ss or m:ss.')
      const body = {
        name: name.trim(),
        event_date: day,
        distance_m,
        purpose,
        goal_time_s,
        status,
        result_s,
      }
      return editing
        ? patch(`/events/${encodeURIComponent(editing.id)}`, {
            expected_version: editing.version,
            ...body,
          })
        : post('/events', body)
    },
    onSuccess: () => {
      invalidateKeys(qc, [qk.events, qk.blocks, qk.proposals])
      reset()
    },
  })
  const summary = (event: RaceEvent) => (
    <>
      {event.name} ·{' '}
      {dateLabel(event.event_date, { month: 'short', day: 'numeric', year: 'numeric' })} ·{' '}
      {event.distance_m === null ? 'distance not set' : fmtDistance(event.distance_m, unit)} ·{' '}
      {EVENT_PURPOSE_LABELS[event.purpose]} · {event.status}
      {event.goal_time_s !== null && ` · goal ${fmtClock(event.goal_time_s)}`}
      {event.result_s !== null && ` · result ${fmtClock(event.result_s)}`}{' '}
    </>
  )
  const editButton = (event: RaceEvent) => (
    <Button
      variant="link"
      onClick={() => {
        setEditing(event)
        setName(event.name)
        setDay(event.event_date)
        setDistance(event.distance_m === null ? '' : String(event.distance_m))
        setDistanceEdited(false)
        setPurpose(event.purpose)
        setGoalTime(event.goal_time_s === null ? '' : fmtClock(event.goal_time_s))
        setGoalEdited(false)
        setStatus(event.status)
        setResult(event.result_s === null ? '' : fmtClock(event.result_s))
        setResultEdited(false)
        save.reset()
      }}
    >
      Edit
    </Button>
  )
  return (
    <Card>
      <h2>Events</h2>
      <p>
        Rank 1 is your goal race. Every training block builds toward it. Each event’s purpose guides
        how you prepare for and run it. Changes feed the next coach review. The calendar updates
        when you accept a proposal.
      </p>
      <QueryState
        loading={query.isPending}
        error={query.error}
        stale={!!query.data}
        retry={() => {
          void query.refetch()
        }}
      >
        {!items.length && <p>No events yet.</p>}
        {upcoming.length > 0 && (
          <>
            <h3>Upcoming, in priority order</h3>
            <ol
              ref={rankList}
              className="event-rank-list"
              aria-label="Upcoming events in priority order"
            >
              {upcoming.map((event, index) => (
                <li key={event.id} data-testid="event-row" data-event-id={event.id}>
                  <strong>#{index + 1}</strong> {index === 0 && <Badge>Goal race</Badge>}{' '}
                  {summary(event)}{' '}
                  <Button
                    variant="outline"
                    size="sm"
                    data-move="up"
                    aria-label={`Move ${event.name} up`}
                    disabled={busy || save.isPending || index === 0}
                    onClick={() => move.mutate({ event, direction: 'up', to: index - 1 })}
                  >
                    Up
                  </Button>{' '}
                  <Button
                    variant="outline"
                    size="sm"
                    data-move="down"
                    aria-label={`Move ${event.name} down`}
                    disabled={busy || save.isPending || index === upcoming.length - 1}
                    onClick={() => move.mutate({ event, direction: 'down', to: index + 1 })}
                  >
                    Down
                  </Button>{' '}
                  {editButton(event)}
                </li>
              ))}
            </ol>
          </>
        )}
        <p role="status">{moved}</p>
        <ErrorText error={move.error} />
        {past.length > 0 && (
          <>
            <h3>Past and cancelled</h3>
            <ul className="event-past-list">
              {past.map((event) => (
                <li key={event.id} data-testid="event-row-past">
                  {summary(event)} {editButton(event)}
                </li>
              ))}
            </ul>
          </>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <fieldset disabled={save.isPending || move.isPending}>
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
              id="event-purpose"
              label="Purpose"
              value={purpose}
              options={EVENT_PURPOSE_LABELS}
              onChange={(v) => setPurpose(v as EventPurpose)}
            />
            <label htmlFor="event-goal-time">Goal time (h:mm:ss or m:ss, optional)</label>
            <Input
              id="event-goal-time"
              value={goalTime}
              onChange={(e) => {
                setGoalTime(e.target.value)
                setGoalEdited(true)
              }}
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
