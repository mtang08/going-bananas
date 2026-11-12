import {
  Button,
  Card,
  Disclosure,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  MISSING,
  addDays,
  api,
  dateLabel,
  fmtDistance,
  fmtDuration,
  fmtPercent,
  qk,
  query,
  statusText,
} from '../api'
import type {
  HardClass,
  MetricResult,
  MetricWindows,
  RecoveryNight,
  RecoveryNights,
  Unit,
  WindowMetrics,
  ZoneDistribution,
} from '../api'
import { QueryState } from '../components/QueryState'
import './TrainingDesign.css'
const DAYS = [7, 14, 28, 56] as const
const CLASS: Record<HardClass, string> = {
  quality: 'Quality',
  long: 'Long run',
  lower_body_strength: 'Lower-body strength',
}
const SOURCE = { plan_link: 'the plan', manual: 'your label', long_rule: 'the duration rule' }
const DELAYED = {
  reported: 'reported',
  none_reported: 'none reported',
  unknown: 'unknown (no follow-up)',
}
function missingResult<V>(title: string, result: MetricResult<V> | null): string | null {
  if (result === null) return `${title}: missing`
  if (result.value === null)
    return `${title}: ${statusText(result.status)}${
      result.reason_codes.length ? ` (${result.reason_codes.join(', ')})` : ''
    }`
  return null
}
function coverage<V>(result: MetricResult<V> | null) {
  return result?.quality_status === 'limited' || result?.quality_status === 'insufficient' ? (
    <small>Data coverage: {result.quality_status}</small>
  ) : null
}
function partialContext<V>(result: MetricResult<V> | null) {
  if (result?.status !== 'partial' || result.value === null) return null
  const details = [...result.reason_codes, ...result.quality_flags]
  return <small>Partial data{details.length ? `: ${details.join(', ')}` : ''}</small>
}
function intensityText(zone: ZoneDistribution, label: string): string {
  if (zone.status === 'available' || zone.status === 'partial') {
    return `${label}: Easy ${fmtDuration(zone.easy_s)} · Moderate ${fmtDuration(zone.moderate_s)} · High ${fmtDuration(zone.high_s)} · Unknown ${fmtDuration(zone.unknown_s)} · Coverage ${fmtPercent(zone.coverage)}${zone.confidence === 'low' ? ' · low-confidence anchor' : ''}`
  }
  if (zone.reason_codes.includes('ANCHOR_MISSING')) {
    return `${label}: No anchor — add aerobic-upper and threshold-lower anchors in Settings.`
  }
  return `${label}: ${statusText(zone.status)}${zone.reason_codes.length ? ` (${zone.reason_codes.join(', ')})` : ''}`
}
function IntensityBar({ zone, label }: { zone: ZoneDistribution; label: string }) {
  const values = [zone.easy_s, zone.moderate_s, zone.high_s, zone.unknown_s]
  const labels = ['Easy', 'Moderate', 'High', 'Unknown']
  const colors = ['green', 'amber', 'rose', 'slate']
  const total = values.reduce<number>((sum, value) => sum + (value ?? 0), 0)
  const available = zone.status === 'available' || zone.status === 'partial'
  return (
    <div className="intensity-distribution">
      <p data-testid={label === 'Heart rate' ? 'intensity-hr' : 'intensity-speed'}>
        {available ? (
          <>
            <strong>{label}</strong> · Coverage {fmtPercent(zone.coverage)}
            {zone.status === 'partial' ? ' · Partial data' : ''}
            {zone.confidence === 'low' ? ' · low-confidence anchor' : ''}
          </>
        ) : (
          intensityText(zone, label)
        )}
      </p>
      {available && (
        <>
          {total > 0 && (
            <div
              className="intensity-time-bar"
              role="img"
              aria-label={`${label} intensity time distribution; durations listed below`}
            >
              {values.map((value, i) =>
                value !== null && value > 0 ? (
                  <span
                    key={labels[i]}
                    className={`zone-${colors[i]}`}
                    style={{ flexGrow: value }}
                  />
                ) : null,
              )}
            </div>
          )}
          <ul className="intensity-key">
            {values.map((value, i) => (
              <li key={labels[i]}>
                <span className={`zone-swatch zone-${colors[i]}`} aria-hidden="true" />
                {labels[i]} · {fmtDuration(value)}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
function hours(min: number | null, max: number | null): string {
  if (min === null && max === null) return MISSING
  if (min === null || max === null || min === max) return `${Math.round(min ?? max!)} h`
  return `${Math.round(min)}–${Math.round(max)} h`
}
function nightFlags(night: RecoveryNight): string[] {
  const flags = []
  if (night.hrv.adverse) flags.push('Low HRV')
  if (night.resting_hr.adverse) flags.push('High resting HR')
  if (night.sleep.adverse) flags.push('Short sleep')
  if (night.subjective_poor) flags.push('Poor subjective')
  if (night.discordance) flags.push('Signals disagree')
  return flags
}
function Recovery({ nights }: { nights: RecoveryNight[] }) {
  if (!nights.length) return <p>No recovery nights in this range.</p>
  const chronological = [...nights].sort((a, b) => a.local_date.localeCompare(b.local_date))
  const latest = chronological[chronological.length - 1]
  const latestFlags = nightFlags(latest)
  const chartData = chronological.map((night) => ({
    date: night.local_date,
    hrv: night.hrv.value,
    rhr: night.resting_hr.value,
  }))
  return (
    <>
      <div className="recovery-chart-key">
        <span>HRV (ms) · left axis</span>
        <span>Resting HR (bpm) · right axis</span>
      </div>
      <div className="chart" role="img" aria-label="Overnight HRV and resting HR by night">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData}>
            <CartesianGrid vertical={false} stroke="#e9e7df" />
            <XAxis
              dataKey="date"
              tickFormatter={(value: string) => dateLabel(value)}
              fontSize={11}
            />
            <YAxis yAxisId="hrv" fontSize={11} width={35} />
            <YAxis yAxisId="rhr" orientation="right" fontSize={11} width={35} />
            <Tooltip />
            <Line
              yAxisId="hrv"
              dataKey="hrv"
              name="HRV (ms)"
              stroke="#5b754d"
              dot={false}
              connectNulls={false}
            />
            <Line
              yAxisId="rhr"
              dataKey="rhr"
              name="Resting HR (bpm)"
              stroke="#9b704c"
              dot={false}
              connectNulls={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="recovery-latest" aria-label="Latest recovery night">
        <strong>Latest night · {dateLabel(latest.local_date)}</strong>
        <dl>
          <div>
            <dt>Sleep</dt>
            <dd>
              {latest.sleep.value !== null
                ? fmtDuration(latest.sleep.value)
                : statusText(latest.sleep.status)}
            </dd>
          </div>
          <div>
            <dt>HRV</dt>
            <dd>
              {latest.hrv.value !== null
                ? `${Math.round(latest.hrv.value)} ms`
                : statusText(latest.hrv.status)}
            </dd>
          </div>
          <div>
            <dt>Resting HR</dt>
            <dd>
              {latest.resting_hr.value !== null
                ? `${Math.round(latest.resting_hr.value)} bpm`
                : statusText(latest.resting_hr.status)}
            </dd>
          </div>
        </dl>
        <small>Flags: {latestFlags.length ? latestFlags.join(', ') : 'None reported'}</small>
      </div>
      <Disclosure className="training-disclosure">
        <summary>Nightly details ({nights.length} nights)</summary>
        <div className="table-scroll">
          <Table aria-label="Recovery nights">
            <TableHeader>
              <TableRow>
                <TableHead>Night</TableHead>
                <TableHead>Sleep</TableHead>
                <TableHead>HRV</TableHead>
                <TableHead>Resting HR</TableHead>
                <TableHead>Baseline</TableHead>
                <TableHead>Flags</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {[...nights]
                .sort((a, b) => b.local_date.localeCompare(a.local_date))
                .map((night) => {
                  const allMissing = [night.sleep, night.hrv, night.resting_hr].every(
                    (signal) => signal.status === 'missing',
                  )
                  const flags = nightFlags(night)
                  const baseline = {
                    none: 'No baseline',
                    provisional: 'Provisional',
                    established: 'Established',
                  }
                  return (
                    <TableRow
                      key={night.local_date}
                      data-testid="recovery-night"
                      data-date={night.local_date}
                      className={allMissing ? 'recovery-night missing' : 'recovery-night'}
                    >
                      <TableCell>
                        {dateLabel(night.local_date, {
                          weekday: 'short',
                          month: 'short',
                          day: 'numeric',
                        })}
                      </TableCell>
                      <TableCell>
                        {night.sleep.value !== null
                          ? fmtDuration(night.sleep.value)
                          : statusText(night.sleep.status)}
                      </TableCell>
                      <TableCell>
                        {night.hrv.value !== null
                          ? `${Math.round(night.hrv.value)} ms`
                          : statusText(night.hrv.status)}
                      </TableCell>
                      <TableCell>
                        {night.resting_hr.value !== null
                          ? `${Math.round(night.resting_hr.value)} bpm`
                          : statusText(night.resting_hr.status)}
                      </TableCell>
                      <TableCell>{baseline[night.hrv.baseline_state]}</TableCell>
                      <TableCell>{flags.length ? flags.join(', ') : 'None'}</TableCell>
                    </TableRow>
                  )
                })}
            </TableBody>
          </Table>
        </div>
      </Disclosure>
    </>
  )
}
export function Trends({ unit }: { unit: Unit }) {
  const [days, setDays] = useState<WindowMetrics['days']>(28)
  const windows = useQuery({
    queryKey: qk.metricsWindows,
    queryFn: () => api<MetricWindows>('/metrics/windows'),
  })
  const asOf = windows.data?.data.as_of
  const start = asOf ? addDays(asOf, -27) : ''
  const end = asOf ?? ''
  const recovery = useQuery({
    queryKey: qk.metricsRecovery(start, end),
    enabled: Boolean(asOf),
    queryFn: () => api<RecoveryNights>(`/metrics/recovery${query({ start, end })}`),
  })
  const data = windows.data?.data
  const selected = data?.windows.find((window) => window.days === days) ?? null
  const volume = selected?.volume ?? null
  const longRun = selected?.long_run ?? null
  const srpe = selected?.srpe ?? null
  const intensity = selected?.intensity ?? null
  const spacing = data?.spacing ?? null
  return (
    <section className="page-content">
      <div className="page-heading">
        <div>
          <div className="eyebrow">TRENDS</div>
          <h1>Trends.</h1>
          <p>Rolling totals and signals. Missing data is shown as missing, never as zero.</p>
        </div>
      </div>
      <div className="segmented" aria-label="Trend window">
        {DAYS.map((count) => (
          <Button
            variant="ghost"
            key={count}
            className={
              days === count ? 'active bg-card text-foreground shadow-sm' : 'text-muted-foreground'
            }
            onClick={() => setDays(count)}
          >
            {count} days
          </Button>
        ))}
      </div>
      <QueryState
        loading={windows.isPending}
        error={windows.error}
        stale={Boolean(data)}
        retry={() => void windows.refetch()}
      >
        {data && (
          <div className="trend-grid">
            <Card data-testid="trend-volume">
              <h2>Running volume</h2>
              {missingResult('Volume', volume) ??
                (volume?.value && (
                  <>
                    <strong>{fmtDistance(volume.value.distance_m, unit)}</strong>
                    <p>
                      {volume.value.run_count} {volume.value.run_count === 1 ? 'run' : 'runs'} ·{' '}
                      {fmtDuration(volume.value.timer_duration_s)} timer time
                    </p>
                    <p>
                      {volume.value.previous
                        ? `Previous ${days} days${volume.value.previous.coverage_complete ? '' : ' (incomplete)'}: ${fmtDistance(volume.value.previous.distance_m, unit)} · ${volume.value.previous.run_count} ${volume.value.previous.run_count === 1 ? 'run' : 'runs'}`
                        : 'Previous window: missing'}
                    </p>
                  </>
                ))}
              {coverage(volume)}
              {partialContext(volume)}
            </Card>
            <Card data-testid="trend-long-run">
              <h2>Long-run exposure</h2>
              {missingResult('Long-run exposure', longRun) ??
                (longRun?.value && (
                  <>
                    {longRun.value.latest ? (
                      <>
                        <p>
                          Latest long run {dateLabel(longRun.value.latest.local_date)} ·{' '}
                          {fmtDuration(longRun.value.latest.timer_s)} ·{' '}
                          {fmtDistance(longRun.value.latest.distance_m, unit)}
                        </p>
                        <p>
                          Vs recent max: duration{' '}
                          {fmtPercent(longRun.value.latest.duration_ratio_to_recent_max)} · distance{' '}
                          {fmtPercent(longRun.value.latest.distance_ratio_to_recent_max)}
                        </p>
                        <p>
                          Share of 7-day running:{' '}
                          {fmtPercent(longRun.value.latest.weekly_share_duration)}
                        </p>
                        <p>
                          Classified from {SOURCE[longRun.value.latest.classification_source]} (
                          {longRun.value.latest.classification_confidence} confidence)
                        </p>
                        <p>
                          Delayed symptoms: {DELAYED[longRun.value.latest.delayed_symptom_status]}
                        </p>
                      </>
                    ) : (
                      <p>
                        {longRun.status === 'partial'
                          ? 'No confirmed long run in available data.'
                          : 'No long run in this window.'}
                      </p>
                    )}
                    <p>
                      {longRun.value.long_run_count} long{' '}
                      {longRun.value.long_run_count === 1 ? 'run' : 'runs'} in {days} days
                      {longRun.status === 'partial' ? ' (partial)' : ''}
                    </p>
                  </>
                ))}
              {coverage(longRun)}
              {partialContext(longRun)}
            </Card>
            <Card data-testid="trend-srpe">
              <h2>Session RPE load</h2>
              {missingResult('Session RPE load', srpe) ??
                (srpe?.value && (
                  <>
                    <strong>
                      {srpe.value.load_au == null
                        ? MISSING
                        : `${Math.round(srpe.value.load_au)} AU`}
                    </strong>
                    <p>
                      RPE on {srpe.value.sessions_with_rpe} of {srpe.value.sessions_total} runs
                    </p>
                    <p>Duration coverage {fmtPercent(srpe.value.coverage_duration)}</p>
                    <small>Runs without RPE are left out, not estimated.</small>
                  </>
                ))}
              {coverage(srpe)}
              {partialContext(srpe)}
            </Card>
            <Card data-testid="trend-intensity">
              <h2>Intensity time</h2>
              {missingResult('Intensity', intensity) ??
                (intensity?.value && (
                  <>
                    <IntensityBar zone={intensity.value.hr} label="Heart rate" />
                    <IntensityBar zone={intensity.value.speed} label="Pace" />
                  </>
                ))}
              {coverage(intensity)}
              {partialContext(intensity)}
            </Card>
            <Card data-testid="trend-spacing">
              <h2>Hard-session spacing</h2>
              <small>Rolling 14-day calendar</small>
              {missingResult('Hard-session spacing', spacing) ??
                (spacing?.value &&
                  (spacing.value.sequence.length === 0 ? (
                    <p>No hard sessions in the 14-day calendar.</p>
                  ) : (
                    <>
                      <ol>
                        {spacing.value.sequence.map((exposure, index) => (
                          <li key={exposure.subject_key + ':' + index}>
                            {dateLabel(exposure.local_date)} ·{' '}
                            {exposure.classes.map((kind) => CLASS[kind]).join(' + ')}
                          </li>
                        ))}
                      </ol>
                      <ul>
                        {spacing.value.gaps.map((gap, index) => (
                          <li key={gap.from_date + ':' + gap.to_date + ':' + index}>
                            {CLASS[gap.from_class]} → {CLASS[gap.to_class]}:{' '}
                            {hours(gap.hours_min, gap.hours_max)}
                            {gap.confidence === 'low' ? ' (low confidence)' : ''}
                          </li>
                        ))}
                      </ul>
                    </>
                  )))}
              {coverage(spacing)}
              {partialContext(spacing)}
            </Card>
          </div>
        )}
      </QueryState>
      <Card data-testid="trend-recovery">
        <h2>Recovery</h2>
        <p>Sleep, overnight HRV, and resting HR per night. Missing nights stay missing.</p>
        <QueryState
          loading={Boolean(asOf) && recovery.isPending}
          error={recovery.error}
          stale={Boolean(recovery.data)}
          retry={() => void recovery.refetch()}
        >
          {recovery.data && <Recovery nights={recovery.data.data.nights} />}
        </QueryState>
      </Card>
    </section>
  )
}
