import { Disclosure, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { dateLabel, type Recovery } from '../api'
export function RecoveryPanel({ data }: { data: Recovery }) {
  const labels = { sleep: 'Sleep', hrv: 'HRV', resting_hr: 'Resting HR' }
  const hrv = data.series.hrv || []
  return (
    <>
      <div className="recovery-list">
        {(['sleep', 'hrv', 'resting_hr'] as const).map((key) => {
          const points = data.series[key] || []
          const recent = points.slice(-7)
          const trailing = data.trailing_7[key]
          return (
            <div className="recovery-row" key={key}>
              <div>
                <strong>{labels[key]}</strong>
                <small>
                  {recent.length ? `${recent.length} observations shown` : 'No observations'}
                </small>
              </div>
              <div className="recovery-values">
                {recent.length ? (
                  <span>
                    {recent.map((p) => `${dateLabel(p.date)}: ${p.value} ${p.unit}`).join(' · ')}
                  </span>
                ) : (
                  <span className="muted-text">Unavailable</span>
                )}
                {trailing?.mean != null && (
                  <small>
                    7-date mean {trailing.mean.toFixed(1)} · {trailing.n}/{trailing.days} observed
                  </small>
                )}
              </div>
            </div>
          )
        })}
      </div>
      {hrv.length > 1 && (
        <>
          <div
            className="recovery-chart"
            role="img"
            aria-label="Observed HRV values by date; gaps are unfilled"
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={hrv}>
                <CartesianGrid vertical={false} stroke="#e9e7df" />
                <XAxis
                  dataKey="date"
                  tickFormatter={(x) => dateLabel(x)}
                  tickLine={false}
                  axisLine={false}
                  fontSize={10}
                />
                <YAxis tickLine={false} axisLine={false} fontSize={10} unit=" ms" />
                <Tooltip formatter={(v) => `${v} ms`} />
                <Line
                  type="linear"
                  dataKey="value"
                  stroke="#798eac"
                  strokeWidth={2}
                  connectNulls={false}
                  dot={{ r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <Disclosure className="chart-table">
            <summary>View HRV data table</summary>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead>HRV</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {hrv.map((p) => (
                  <TableRow key={p.date}>
                    <TableCell>{dateLabel(p.date)}</TableCell>
                    <TableCell>
                      {p.value} {p.unit}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Disclosure>
        </>
      )}
    </>
  )
}
