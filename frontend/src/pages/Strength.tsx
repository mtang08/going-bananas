import {
  Button,
  Card,
  Disclosure,
  NativeSelect,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, dateLabel, duration, localDate, query } from '../api'
type Workout = {
  id: string
  date: string
  local_start: string
  duration_s: number | null
  exercise_count: number
}
type History = {
  session_count: number
  known_duration_s: number
  unknown_duration_count: number
  latest_imported_workout_date: string | null
  imported_at: string | null
  ambiguous_overlap_count: number
  next_offset: number | null
  sessions: Workout[]
}
type Detail = {
  workout_name: string
  date: string
  sets: Record<string, string>[]
  resolution_state: string
}
type Years = {
  years: {
    year: number
    session_count: number
  }[]
}
export function Strength() {
  const [year, setYear] = useState(String(new Date().getFullYear())),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<string | null>(null)
  const thisYear = String(new Date().getFullYear()),
    end = year === thisYear ? localDate() : `${year}-12-31`,
    start = `${year}-01-01`
  const years = useQuery({
    queryKey: ['strength-years'],
    queryFn: () => api<Years>('/strength/years'),
  })
  const history = useQuery({
    queryKey: ['strength', year, offset],
    queryFn: () =>
      api<History>(
        `/strength/history${query({ start_date: start, end_date: end, offset, limit: 50 })}`,
      ),
  })
  const detail = useQuery({
    queryKey: ['strength-detail', selected],
    queryFn: () => api<Detail>(`/strength/history/${selected}`),
    enabled: !!selected,
  })
  const data = history.data?.data
  const availableYears = Array.from(
    new Set([Number(thisYear), ...(years.data?.data.years.map((item) => item.year) || [])]),
  ).sort((a, b) => b - a)
  return (
    <section className="page-content">
      <div className="page-heading">
        <div>
          <div className="eyebrow">THE OTHER HALF</div>
          <h1>Strength history.</h1>
          <p>Your Strong records, alongside your running.</p>
        </div>
        <label className="select-label">
          Year
          <NativeSelect
            value={year}
            onChange={(e) => {
              setYear(e.target.value)
              setOffset(0)
              setSelected(null)
            }}
          >
            {availableYears.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </NativeSelect>
        </label>
      </div>
      <div className="notice muted">
        Running recommendations use the preceding 18 calendar months. Older workouts are available
        here for historical review.
      </div>
      <div className="notice warning">
        Weights are shown exactly as recorded. The export does not specify units, and the date of
        the change from combined to single-dumbbell weight is unknown. Compare sets within a known
        convention; no cross-period weight records or training targets are inferred.
      </div>
      {history.isPending && <div className="state-card">Loading Strong history…</div>}
      {history.error && (
        <p role="alert" className="error-text">
          {history.error.message}
        </p>
      )}
      {years.error && (
        <p role="alert" className="error-text">
          Available years could not be loaded: {years.error.message}
        </p>
      )}
      {data && (
        <>
          <Card>
            <div className="panel-head">
              <div>
                <h2>
                  {data.session_count} recorded workouts in {year}
                </h2>
                <p>
                  {duration(data.known_duration_s)} known time · {data.unknown_duration_count}{' '}
                  unknown durations
                </p>
              </div>
            </div>
            <p className="fineprint">
              Latest imported workout:{' '}
              {data.latest_imported_workout_date
                ? dateLabel(data.latest_imported_workout_date, {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                  })
                : 'None'}
              . Strong remains your recording app; import a new CSV to refresh this view. Missing
              entries do not mean skipped lifting.
            </p>
            {data.ambiguous_overlap_count > 0 && (
              <div className="notice warning">
                {data.ambiguous_overlap_count} same-day overlaps with other strength sources are
                withheld from combined totals pending review.
              </div>
            )}
            {data.sessions.length ? (
              <div className="table-scroll">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Date</TableHead>
                      <TableHead>Exercises</TableHead>
                      <TableHead>Duration</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.sessions.map((w) => (
                      <TableRow key={w.id}>
                        <TableCell>
                          <Button
                            onClick={() => setSelected(w.id)}
                            variant="link"
                            className="table-link h-auto p-0"
                          >
                            {dateLabel(w.date, { year: 'numeric', month: 'short', day: 'numeric' })}
                          </Button>
                        </TableCell>
                        <TableCell>{w.exercise_count}</TableCell>
                        <TableCell>{duration(w.duration_s)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <p>No Strong workouts recorded in this window.</p>
            )}
            <div className="coach-actions">
              <Button
                disabled={!offset}
                onClick={() => {
                  setOffset(Math.max(0, offset - 50))
                  setSelected(null)
                }}
                variant="outline"
              >
                Previous page
              </Button>
              <span>Page {Math.floor(offset / 50) + 1} · oldest first</span>
              <Button
                disabled={data.next_offset === null}
                onClick={() => {
                  setOffset(data.next_offset || 0)
                  setSelected(null)
                }}
                variant="outline"
              >
                Next page
              </Button>
            </div>
          </Card>
          {selected && (
            <Card>
              <Button onClick={() => setSelected(null)} variant="link">
                Close workout
              </Button>
              {detail.isPending && <p>Loading sets…</p>}
              {detail.error && <p role="alert">{detail.error.message}</p>}
              {detail.data && (
                <>
                  <h2>{detail.data.data.workout_name}</h2>
                  <p>{detail.data.data.date} · Recorded set values · units unconfirmed</p>
                  <div className="table-scroll">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Exercise</TableHead>
                          <TableHead>Set</TableHead>
                          <TableHead>Recorded weight</TableHead>
                          <TableHead>Reps</TableHead>
                          <TableHead>Seconds</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {detail.data.data.sets.map((row, i) => (
                          <TableRow key={i}>
                            <TableCell>{row['Exercise Name']}</TableCell>
                            <TableCell>{row['Set Order']}</TableCell>
                            <TableCell>{row.Weight || '—'}</TableCell>
                            <TableCell>{row.Reps || '—'}</TableCell>
                            <TableCell>{row.Seconds || '—'}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </>
              )}
            </Card>
          )}
        </>
      )}
      <Disclosure>
        <summary>How historical records are interpreted</summary>
        <p className="fineprint">
          Timers longer than 24 hours are retained in the original export but omitted from duration
          totals. CSV timestamps have no timezone; local dates are preserved. This view does not
          estimate strength capacity from old weights.
        </p>
      </Disclosure>
    </section>
  )
}
