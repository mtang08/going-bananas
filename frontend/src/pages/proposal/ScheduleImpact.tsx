import { useQuery } from '@tanstack/react-query'
import { api, query } from '../../api/client'
import { qk } from '../../api/queryKeys'
import type { StrengthRoutine } from '../../api/types/blocks'
import type { CalendarView } from '../../api/types/calendar'
import type { ProposalChange, ProposalSession } from '../../api/types/coach'
import {
  Button,
  Card,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui'
import { addDays, dateLabel, fmtDistance, fmtDuration, type Unit } from '../../lib/format'
import { ACTION_LABELS, sessionDate, sessionName } from './helpers'
import { firstImpactWeek, NEARBY_DAYS, scheduleImpact } from './scheduleImpactData'

function sessionTitle(session: ProposalSession | null) {
  return session?.custom && session.intent ? session.intent : sessionName(session)
}

function relativeDay(days: number): string {
  if (!days) return 'on the same day'
  if (days === 1) return 'the next day'
  if (days === -1) return 'the day before'
  return `${Math.abs(days)} days ${days > 0 ? 'after' : 'before'}`
}

function doseLabel(
  dose: { known: number; incomplete: boolean },
  format: (amount: number) => string,
) {
  if (dose.incomplete && !dose.known) return 'Unknown'
  const measured = `${dose.known < 0 ? '−' : dose.known > 0 ? '+' : ''}${format(Math.abs(dose.known))}`
  return dose.incomplete ? `${measured} known · some dose unknown` : measured
}

export function ScheduleImpact({
  head,
  expectedHead,
  changes,
  selected,
  unit,
}: {
  head: CalendarView | undefined
  expectedHead: number
  changes: ProposalChange[]
  selected: string[]
  unit: Unit
}) {
  const first = firstImpactWeek(changes)
  const start = first ? addDays(first, -NEARBY_DAYS) : ''
  const end = first ? addDays(first, 13 + NEARBY_DAYS) : ''
  const covered = head && head.head === expectedHead && head.start <= start && head.end >= end
  const range = useQuery({
    queryKey: qk.calendarRange(start, end),
    queryFn: () => api<CalendarView>(`/calendar${query({ start, end })}`),
    enabled: Boolean(first && !covered),
  })
  const calendar = covered ? head : range.data?.data
  const hasBaseline =
    calendar?.head === expectedHead && calendar.start <= start && calendar.end >= end
  const wantsStrengthContext = changes.some(
    (change) => selected.includes(change.change_id) && change.op === 'move',
  )
  const strength = useQuery({
    queryKey: qk.strengthRoutine,
    queryFn: () => api<StrengthRoutine>('/strength-routine'),
    enabled: wantsStrengthContext,
  })
  if (!first) return null
  const preview = scheduleImpact(
    hasBaseline ? calendar.sessions : [],
    changes,
    new Set(selected),
    first,
    strength.data?.data.slots ?? [],
  )

  const inWindow = preview.changes.filter((row) => row.touchesWeeks)
  const outsideWindow = preview.changes.filter((row) => !row.touchesWeeks)
  return (
    <Card aria-label="Two-week schedule impact" className="space-y-3">
      <h2>Two-week schedule impact</h2>
      <p>
        Changes to planned running between {dateLabel(first)} and {dateLabel(addDays(first, 13))} if
        you apply the checked changes.
      </p>
      {preview.changes.length === 0 ? (
        <p>No workout changes selected.</p>
      ) : (
        <>
          <Table aria-label="Weekly planned running changes">
            <TableHeader>
              <TableRow>
                <TableHead>Week</TableHead>
                <TableHead>Distance change</TableHead>
                <TableHead>Time change</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {preview.weeks.map((week) => (
                <TableRow key={week.start}>
                  <TableHead scope="row">
                    {dateLabel(week.start)}–{dateLabel(week.end)}
                  </TableHead>
                  <TableCell>
                    {doseLabel(week.distance, (value) => fmtDistance(value, unit))}
                  </TableCell>
                  <TableCell>
                    {doseLabel(week.duration, (value) =>
                      value > 0 && value < 60 ? `${Math.round(value)}s` : fmtDuration(value),
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {inWindow.length > 0 && (
            <ul className="space-y-2">
              {inWindow.map((row) => (
                <li key={row.change.change_id}>
                  <strong>
                    {ACTION_LABELS[row.change.op]}{' '}
                    {row.before && row.after && sessionTitle(row.before) !== sessionTitle(row.after)
                      ? `${sessionTitle(row.before)} → ${sessionTitle(row.after)}`
                      : sessionTitle(row.after ?? row.before)}
                  </strong>
                  {' · '}
                  {row.before?.local_date &&
                  row.after?.local_date &&
                  row.before.local_date !== row.after.local_date
                    ? `${sessionDate(row.before)} → ${sessionDate(row.after)}`
                    : sessionDate(row.after ?? row.before)}
                  {row.crossesWindow && <p>Part of this change falls outside these two weeks.</p>}
                  {row.movedRun && hasBaseline && row.nearby && (
                    <p>
                      Nearest demanding workout: {sessionTitle(row.nearby.session)} on{' '}
                      {sessionDate(row.nearby.session)} ({relativeDay(row.nearby.difference)}).
                    </p>
                  )}
                  {row.movedRun && hasBaseline && !row.nearby && !strength.isFetching && (
                    <p>
                      No demanding workout identified within {NEARBY_DAYS} days in the available
                      schedule.
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
          {outsideWindow.length > 0 && (
            <>
              <p>Selected changes outside this preview or without a date</p>
              <ul>
                {outsideWindow.map(({ change, before, after }) => (
                  <li key={change.change_id}>
                    {ACTION_LABELS[change.op]} {sessionTitle(after ?? before)} ·{' '}
                    {sessionDate(after ?? before)}
                  </li>
                ))}
              </ul>
            </>
          )}
          {!hasBaseline && inWindow.some((row) => row.movedRun) && (
            <p>
              {range.isFetching
                ? 'Loading the surrounding calendar…'
                : 'Surrounding workouts could not be checked against the current calendar.'}
              {range.error && (
                <Button variant="link" size="sm" onClick={() => void range.refetch()}>
                  Retry calendar
                </Button>
              )}
            </p>
          )}
          {strength.error && inWindow.some((row) => row.movedRun) && (
            <p>Strength session demand could not be checked.</p>
          )}
        </>
      )}
    </Card>
  )
}
