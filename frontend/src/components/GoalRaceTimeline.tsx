import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { qk } from '../api/queryKeys'
import {
  EVENT_PURPOSE_LABELS,
  type BlockVersion,
  type EventBlock,
  type RaceEvent,
} from '../api/types/blocks'
import { addDays, dateLabel, fmtClock, fmtDistance, type Unit } from '../lib/format'
import { Card } from './ui'

function timeUntil(date: string, today: string | undefined) {
  if (!today) return null
  const days = (Date.parse(date) - Date.parse(today)) / 86400000
  if (days < 0) return 'race date passed'
  if (days === 0) return 'race day is today'
  if (days < 14) return `${days} ${days === 1 ? 'day' : 'days'} away`
  return `${Math.floor(days / 7)} weeks away`
}

const dateRange = (start: string, end: string) => `${dateLabel(start)}–${dateLabel(end)}`

export function GoalRaceTimeline({
  block,
  today,
  unit,
}: {
  block: BlockVersion
  today: string | undefined
  unit: Unit
}) {
  const target = block.target_event
  const targetId = target?.id
  const outline = block.build_outline ?? []
  const events = useQuery({
    queryKey: qk.events,
    queryFn: () => api<{ items: RaceEvent[] }>('/events'),
  })
  const related = useQuery({
    queryKey: qk.eventBlocks(targetId ?? ''),
    enabled: Boolean(targetId),
    queryFn: () =>
      api<{ items: EventBlock[] }>(`/events/${encodeURIComponent(targetId ?? '')}/blocks`),
  })
  const earlier = (related.data?.data?.items ?? []).filter(
    (item) => item.block_uid !== block.block_uid,
  )
  const others = (events.data?.data?.items ?? []).filter(
    (event) => event.rank !== null && event.id !== targetId,
  )
  let weeksBefore = 0
  const later = outline.map((step, index) => {
    const from = addDays(block.review_date, weeksBefore * 7 + 1)
    weeksBefore += step.weeks
    const to = addDays(block.review_date, weeksBefore * 7)
    return {
      key: `outline-${index}`,
      kind: 'outline',
      date: from,
      text: `≈${dateRange(from, to)} · ${step.emphasis} · provisional`,
    }
  })
  for (const event of others) {
    const goal = event.goal_time_s === null ? '' : ` · goal ${fmtClock(event.goal_time_s)}`
    later.push({
      key: event.id,
      kind: 'event',
      date: event.event_date,
      text: `${dateLabel(event.event_date)} · ${event.name} · ${EVENT_PURPOSE_LABELS[event.purpose]}${goal}`,
    })
  }
  if (target) {
    later.push({
      key: target.id,
      kind: 'race',
      date: target.event_date,
      text: `${dateLabel(target.event_date)} · ${target.name} · Race day`,
    })
  }
  later.sort((a, b) => a.date.localeCompare(b.date))
  const title = target
    ? [
        target.name,
        dateLabel(target.event_date, { month: 'short', day: 'numeric', year: 'numeric' }),
        target.distance_m === null ? null : fmtDistance(target.distance_m, unit),
        EVENT_PURPOSE_LABELS[target.purpose],
        target.goal_time_s === null ? null : `goal ${fmtClock(target.goal_time_s)}`,
        timeUntil(target.event_date, today),
      ]
        .filter(Boolean)
        .join(' · ')
    : 'No goal race for this block'
  return (
    <Card className="goal-timeline" data-testid="goal-race-timeline">
      <span className="eyebrow">GOAL RACE</span>
      <h2>{title}</h2>
      {block.target_event_status === 'changed' && (
        <p className="goal-timeline-note" role="status">
          Your goal race changed. The next Sunday review will run a block review.
        </p>
      )}
      {block.target_event_status === 'unset' && (
        <p className="goal-timeline-note" role="status">
          This block was planned before you ranked events. The next Sunday review sets its goal
          race.
        </p>
      )}
      {block.target_event_status === 'none' && (
        <p className="goal-timeline-note" role="status">
          No upcoming events. Add one in <a href="#settings">Settings → Events</a>.
        </p>
      )}
      <ol className="goal-timeline-list" aria-label="Build-up to the goal race">
        {earlier.map((item) => (
          <li key={item.block_uid} data-testid="timeline-row" data-kind="earlier">
            {dateRange(item.start_date, item.review_date)} · {item.objective} · Done
          </li>
        ))}
        <li
          data-testid="timeline-row"
          data-kind="current"
          className="is-current"
          aria-current="step"
        >
          {dateRange(block.start_date, block.review_date)} · {block.objective} · Current block
        </li>
        {later.map((row) => (
          <li key={row.key} data-testid="timeline-row" data-kind={row.kind}>
            {row.text}
          </li>
        ))}
      </ol>
      {outline.length > 0 && <p className="fineprint">Direction only; set at each block review</p>}
    </Card>
  )
}
