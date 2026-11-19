import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui'
import { MISSING, dateLabel, fmtPaceFromSpeed, fmtPercent, signatureLabel } from '../api'
import type { ProgressionPoint, Unit } from '../api'
import { reasonText } from '../lib/reasonLabels'

const signed = (value: number | null) =>
  value == null ? MISSING : `${value > 0 ? '+' : ''}${value.toFixed(1)}%`
const reasons = (point: ProgressionPoint) => point.reason_codes.map(reasonText).join(', ')

export function progressionStatus(point: ProgressionPoint): string {
  if (point.status === 'available') return 'Full'
  if (point.status === 'partial') return `Partial: ${reasons(point)}`
  if (point.status === 'not_assessable') return `Not assessable: ${reasons(point)}`
  if (point.reason_codes.includes('NO_LINKED_ACTIVITY'))
    return point.completion_status === 'skipped' ? 'Skipped' : 'Not recorded'
  return reasons(point) || 'Missing'
}

export function WorkoutProgressionChart({
  points,
  unit,
}: {
  points: ProgressionPoint[]
  unit: Unit
}) {
  const data = points
    .filter((p) => (p.status === 'available' || p.status === 'partial') && p.work_speed_mps != null)
    .map((p) => ({ date: p.local_date, speed: p.work_speed_mps, hr: p.work_hr_bpm }))
  if (data.length < 2) return <p>Two or more assessed sessions are needed for a chart.</p>
  return (
    <div className="chart" role="img" aria-label="Work pace and heart rate by session">
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data}>
          <CartesianGrid vertical={false} stroke="#e9e7df" />
          <XAxis dataKey="date" tickFormatter={(value: string) => dateLabel(value)} fontSize={11} />
          <YAxis
            yAxisId="speed"
            domain={['auto', 'auto']}
            tickFormatter={(v: number) => fmtPaceFromSpeed(v, unit)}
          />
          <YAxis yAxisId="hr" orientation="right" />
          <Tooltip />
          <Line
            yAxisId="speed"
            dataKey="speed"
            name="Work pace"
            stroke="#5b754d"
            dot={false}
            connectNulls={false}
          />
          <Line
            yAxisId="hr"
            dataKey="hr"
            name="Work HR (bpm)"
            stroke="#9b704c"
            dot={false}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function WorkoutProgressionTable({
  points,
  unit,
  showSignature = false,
  currentActivityId = null,
}: {
  points: ProgressionPoint[]
  unit: Unit
  showSignature?: boolean
  currentActivityId?: string | null
}) {
  return (
    <>
      <Table aria-label="Workout sessions">
        <TableHeader>
          <TableRow>
            <TableHead>Date</TableHead>
            {showSignature && <TableHead>Work steps</TableHead>}
            <TableHead>Reps</TableHead>
            <TableHead>Work pace</TableHead>
            <TableHead>Work HR</TableHead>
            <TableHead>m/beat</TableHead>
            <TableHead>Pace CV</TableHead>
            <TableHead>Last vs first</TableHead>
            <TableHead>Time in target</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {[...points].reverse().map((p) => {
            const current = currentActivityId !== null && p.activity_id === currentActivityId
            return (
              <TableRow
                key={p.session_uid}
                data-testid="progression-row"
                aria-current={current ? 'true' : undefined}
              >
                <TableCell>
                  {dateLabel(p.local_date)}
                  {current ? ' (this run)' : ''}
                </TableCell>
                {showSignature && <TableCell>{signatureLabel(p.signature)}</TableCell>}
                <TableCell>
                  {p.n_completed == null ? MISSING : `${p.n_completed}/${p.n_planned}`}
                </TableCell>
                <TableCell>{fmtPaceFromSpeed(p.work_speed_mps, unit)}</TableCell>
                <TableCell>
                  {p.work_hr_bpm == null ? MISSING : `${Math.round(p.work_hr_bpm)} bpm`}
                </TableCell>
                <TableCell>
                  {p.work_m_per_beat == null ? MISSING : p.work_m_per_beat.toFixed(2)}
                </TableCell>
                <TableCell>{p.cv_speed == null ? MISSING : `${p.cv_speed.toFixed(1)}%`}</TableCell>
                <TableCell>{signed(p.last_first_change_pct)}</TableCell>
                <TableCell>{fmtPercent(p.target_coverage)}</TableCell>
                <TableCell>
                  {progressionStatus(p)}
                  {p.quality_flags.length ? ` · ${p.quality_flags.map(reasonText).join(', ')}` : ''}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
      <p className="fineprint">
        Pace and HR use completed reps with good pace data. HR is reported only for reps of 3
        minutes or longer.
      </p>
    </>
  )
}
