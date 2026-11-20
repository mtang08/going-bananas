import { reasonText } from '../lib/reasonLabels'
import { OUTCOME_LABELS } from '../coachLabels'
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
import { Fragment, useState } from 'react'
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
  dateLabel,
  fmtDistance,
  fmtDuration,
  fmtPaceFromSpeed,
  fmtPercent,
  signatureLabel,
  statusText,
  type Unit,
} from '../lib/format'
import { RECIPE_LABELS } from '../api/types/calendar'
import { api, query } from '../api/client'
import { qk } from '../api/queryKeys'
import type {
  AerobicPoint,
  AerobicWindowValue,
  HardClass,
  MetricResult,
  MetricWindows,
  RecoveryNight,
  RecoveryNights,
  ProgressionGroup,
  WorkoutProgression,
  WindowMetrics,
  ZoneDistribution,
} from '../api/types/metrics'
import type { BenchmarkRecord } from '../api/types/blocks'
import { QueryState } from '../components/QueryState'
import { WorkoutProgressionChart, WorkoutProgressionTable } from '../components/WorkoutProgression'
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
      result.reason_codes.length ? ` (${result.reason_codes.map(reasonText).join(', ')})` : ''
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
  const details = [...result.reason_codes, ...result.quality_flags].map(reasonText)
  return <small>Partial data{details.length ? `: ${details.join(', ')}` : ''}</small>
}
function intensityText(zone: ZoneDistribution, label: string): string {
  if (zone.status === 'available' || zone.status === 'partial') {
    return `${label}: Easy ${fmtDuration(zone.easy_s)} · Moderate ${fmtDuration(zone.moderate_s)} · High ${fmtDuration(zone.high_s)} · Unknown ${fmtDuration(zone.unknown_s)} · Coverage ${fmtPercent(zone.coverage)}${zone.confidence === 'low' ? ' · low-confidence anchor' : ''}`
  }
  if (zone.reason_codes.includes('ANCHOR_MISSING')) {
    return `${label}: No anchor — add aerobic-upper and threshold-lower anchors in Settings.`
  }
  return `${label}: ${statusText(zone.status)}${zone.reason_codes.length ? ` (${zone.reason_codes.map(reasonText).join(', ')})` : ''}`
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
function BenchmarkHistory({ items, unit }: { items: BenchmarkRecord[]; unit: Unit }) {
  if (!items.length)
    return <p>No benchmark results yet. A block review sets one about every 6 weeks.</p>
  const groups = new Map<number, BenchmarkRecord[]>()
  for (const item of items)
    if (item.distance_m != null && item.local_date && item.result_s != null)
      groups.set(item.distance_m, [...(groups.get(item.distance_m) ?? []), item])
  return (
    <>
      {[...groups.entries()]
        .filter(([, rows]) => rows.length >= 2)
        .map(([meters, rows]) => (
          <div
            className="chart"
            role="img"
            aria-label={`${fmtDistance(meters, unit)} benchmark results`}
            key={meters}
          >
            <ResponsiveContainer width="100%" height={180}>
              <LineChart
                data={[...rows]
                  .sort((a, b) => a.local_date!.localeCompare(b.local_date!))
                  .map((r) => ({ date: r.local_date, result_s: r.result_s }))}
              >
                <CartesianGrid vertical={false} stroke="#e9e7df" />
                <XAxis
                  dataKey="date"
                  tickFormatter={(value: string) => dateLabel(value)}
                  fontSize={11}
                />
                <YAxis
                  fontSize={11}
                  width={45}
                  tickFormatter={(value: number) => fmtDuration(value)}
                />
                <Tooltip />
                <Line dataKey="result_s" name="Result" stroke="#5b754d" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ))}
      <Table aria-label="Benchmark results">
        <TableHeader>
          <TableRow>
            <TableHead>Date</TableHead>
            <TableHead>Protocol</TableHead>
            <TableHead>Result</TableHead>
            <TableHead>Outcome</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.id}>
              <TableCell>{item.local_date ? dateLabel(item.local_date) : MISSING}</TableCell>
              <TableCell>{item.protocol}</TableCell>
              <TableCell>{fmtDuration(item.result_s)}</TableCell>
              <TableCell>{item.outcome ? OUTCOME_LABELS[item.outcome] : MISSING}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  )
}

const assessable = <V,>(result: MetricResult<V> | null): boolean =>
  result !== null && result.value !== null
const zoneShown = (zone: ZoneDistribution) =>
  zone.status === 'available' || zone.status === 'partial'

function WorkoutProgressionCard({ unit }: { unit: Unit }) {
  const [groupBy, setGroupBy] = useState<'signature' | 'recipe'>('signature')
  const [selected, setSelected] = useState<string | null>(null)
  const progression = useQuery({
    queryKey: qk.workoutProgression(groupBy),
    queryFn: () =>
      api<WorkoutProgression>(`/metrics/workout-progression${query({ group_by: groupBy })}`),
  })
  const groups = progression.data?.data.groups ?? []
  const group = groups.find((item) => item.group_key === selected) ?? groups[0] ?? null
  const label = (item: ProgressionGroup) =>
    item.signature
      ? signatureLabel(item.signature)
      : (RECIPE_LABELS[item.recipe_ids[0]] ?? item.recipe_ids[0])
  return (
    <Card data-testid="trend-workout-progression">
      <h2>Workout progression</h2>
      <p>
        Sessions with the same work steps, newest first. Partial sessions use completed reps only;
        missing data stays missing.
      </p>
      <div className="segmented" aria-label="Group workouts by">
        {(
          [
            ['signature', 'Same work steps'],
            ['recipe', 'Same session type'],
          ] as const
        ).map(([key, text]) => (
          <Button
            key={key}
            variant="ghost"
            type="button"
            className={
              groupBy === key ? 'active bg-card text-foreground shadow-sm' : 'text-muted-foreground'
            }
            onClick={() => {
              setGroupBy(key)
              setSelected(null)
            }}
          >
            {text}
          </Button>
        ))}
      </div>
      <QueryState
        loading={progression.isPending}
        error={progression.error}
        stale={Boolean(progression.data)}
        retry={() => void progression.refetch()}
      >
        {group ? (
          <>
            <label className="grid gap-2">
              Workout
              <NativeSelect
                value={group.group_key}
                onChange={(event) => setSelected(event.target.value)}
              >
                {groups.map((g) => (
                  <option key={g.group_key} value={g.group_key}>
                    {`${label(g)} · ${g.sessions_assessable}/${g.sessions_total} assessed`}
                  </option>
                ))}
              </NativeSelect>
            </label>
            <WorkoutProgressionChart points={group.points} unit={unit} />
            <WorkoutProgressionTable
              points={group.points}
              unit={unit}
              showSignature={group.group_by === 'recipe'}
            />
          </>
        ) : (
          <p>No structured workouts in the last 180 days.</p>
        )}
      </QueryState>
    </Card>
  )
}

function aerobicLine(result: MetricResult<AerobicWindowValue> | null, days: 28 | 84): string {
  if (result === null) return `${days} days: missing`
  if (result.value === null) return `${days} days: ${statusText(result.status)}`
  const v = result.value
  if (v.runs_counted === 0) {
    const why = Object.entries(v.not_counted)
      .map(([code, count]) => `${reasonText(code)} ${count}`)
      .join(', ')
    return `${days} days: no steady easy or long runs${why ? ` (${why})` : ''}`
  }
  const median = v.ef_median_m_per_beat
  const estimate = median === null ? 'median missing' : `median ${median.toFixed(2)} m/beat`
  const parts = [
    `${days} days: ${estimate} over ${v.runs_counted} ${v.runs_counted === 1 ? 'run' : 'runs'}`,
  ]
  if (v.ef_change_pct !== null) {
    parts.push(`${v.ef_change_pct > 0 ? '+' : ''}${v.ef_change_pct.toFixed(1)}% early → late`)
  }
  if (v.decoupling_median_pct !== null) {
    const count = v.decoupling_runs_counted
    parts.push(
      `median drift ${v.decoupling_median_pct.toFixed(1)}% (${count} ${count === 1 ? 'run' : 'runs'})`,
    )
  }
  return parts.join(' · ')
}

function AerobicChart({ points, unit }: { points: AerobicPoint[]; unit: Unit }) {
  const series = points.map((point) => ({
    date: point.local_date,
    ef: point.ef_m_per_beat,
    pace: fmtPaceFromSpeed(point.mean_speed_mps, unit),
    hr: Math.round(point.mean_hr_bpm),
  }))
  return (
    <div
      className="chart"
      role="img"
      aria-label="Metres per heartbeat on steady runs, last 84 days"
    >
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={series}>
          <CartesianGrid vertical={false} stroke="#e9e7df" />
          <XAxis dataKey="date" tickFormatter={(value: string) => dateLabel(value)} fontSize={11} />
          <YAxis
            domain={['auto', 'auto']}
            tickFormatter={(value: number) => value.toFixed(2)}
            fontSize={11}
            width={40}
          />
          <Tooltip
            formatter={(value: number, _name, item) => [
              `${value.toFixed(2)} m/beat · ${item.payload.pace} · ${item.payload.hr} bpm`,
              'Aerobic efficiency',
            ]}
          />
          <Line dataKey="ef" name="m per heartbeat" stroke="#5b754d" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function AerobicRunDetails({ points, unit }: { points: AerobicPoint[]; unit: Unit }) {
  if (!points.length) return null
  return (
    <Disclosure className="training-disclosure">
      <summary>Run details ({points.length})</summary>
      <div className="table-scroll">
        <Table aria-label="Aerobic efficiency by run">
          <TableHeader>
            <TableRow>
              <TableHead>Date</TableHead>
              <TableHead>m/beat</TableHead>
              <TableHead>Mean pace</TableHead>
              <TableHead>Mean heart rate</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {[...points].reverse().map((point) => (
              <TableRow key={point.activity_id}>
                <TableCell>{dateLabel(point.local_date)}</TableCell>
                <TableCell>{point.ef_m_per_beat.toFixed(2)}</TableCell>
                <TableCell>{fmtPaceFromSpeed(point.mean_speed_mps, unit)}</TableCell>
                <TableCell>{Math.round(point.mean_hr_bpm)} bpm</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Disclosure>
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
  const benchmarks = useQuery({
    queryKey: qk.blockBenchmarks,
    queryFn: () => api<{ items: BenchmarkRecord[] }>('/blocks/benchmarks'),
  })
  const data = windows.data?.data
  const selected = data?.windows.find((window) => window.days === days) ?? null
  const volume = selected?.volume ?? null
  const longRun = selected?.long_run ?? null
  const srpe = selected?.srpe ?? null
  const intensity = selected?.intensity ?? null
  const spacing = data?.spacing ?? null
  const aerobic = data?.aerobic ?? null
  const aerobic28 = aerobic?.w28 ?? null
  const aerobic84 = aerobic?.w84 ?? null
  const aerobicPoints = aerobic84?.value?.points ?? []
  const longRunCard = (
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
                  Share of 7-day running: {fmtPercent(longRun.value.latest.weekly_share_duration)}
                </p>
                <p>
                  Classified from {SOURCE[longRun.value.latest.classification_source]} (
                  {longRun.value.latest.classification_confidence} confidence)
                </p>
                <p>Delayed symptoms: {DELAYED[longRun.value.latest.delayed_symptom_status]}</p>
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
  )
  const srpeCard = (
    <Card data-testid="trend-srpe">
      <h2>Session RPE load</h2>
      {missingResult('Session RPE load', srpe) ??
        (srpe?.value && (
          <>
            <strong>
              {srpe.value.load_au == null ? MISSING : `${Math.round(srpe.value.load_au)} AU`}
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
  )
  const intensityCard = (
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
  )
  const aerobicCard = (
    <Card data-testid="trend-aerobic">
      <h2>Aerobic efficiency</h2>
      <small>
        Steady easy and long runs · metres per heartbeat. Higher means faster at the same heart
        rate.
      </small>
      {aerobicPoints.length >= 2 && <AerobicChart points={aerobicPoints} unit={unit} />}
      <p>{aerobicLine(aerobic28, 28)}</p>
      <p>{aerobicLine(aerobic84, 84)}</p>
      <AerobicRunDetails
        points={aerobicPoints.length ? aerobicPoints : (aerobic28?.value?.points ?? [])}
        unit={unit}
      />
      <small>
        Descriptive only. Heat, hills, fatigue, and sensor error change these numbers. Treadmill
        runs are left out.
      </small>
      {coverage(aerobic28)}
      {partialContext(aerobic28)}
    </Card>
  )
  const spacingCard = (
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
  )
  const panels = [
    { key: 'long-run', ok: assessable(longRun), node: longRunCard },
    { key: 'srpe', ok: assessable(srpe), node: srpeCard },
    {
      key: 'intensity',
      ok: assessable(intensity) && [intensity!.value!.hr, intensity!.value!.speed].some(zoneShown),
      node: intensityCard,
    },
    {
      key: 'aerobic',
      ok: assessable(aerobic84) && (aerobic84?.value?.runs_counted ?? 0) > 0,
      node: aerobicCard,
    },
    { key: 'spacing', ok: assessable(spacing), node: spacingCard },
  ]
  const shown = panels.filter((panel) => panel.ok)
  const deferred = panels.filter((panel) => !panel.ok)
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
          <>
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
              {shown.map((panel) => (
                <Fragment key={panel.key}>{panel.node}</Fragment>
              ))}
            </div>
            {deferred.length > 0 && (
              <Disclosure
                variant="card"
                className="training-disclosure"
                data-testid="trends-not-assessable"
              >
                <summary>Not yet assessable ({deferred.length})</summary>
                <div className="trend-grid">
                  {deferred.map((panel) => (
                    <Fragment key={panel.key}>{panel.node}</Fragment>
                  ))}
                </div>
              </Disclosure>
            )}
          </>
        )}
      </QueryState>
      <WorkoutProgressionCard unit={unit} />
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
      <Card data-testid="trend-benchmarks">
        <h2>Benchmark history</h2>
        <QueryState
          loading={benchmarks.isPending}
          error={benchmarks.error}
          stale={Boolean(benchmarks.data)}
          retry={() => void benchmarks.refetch()}
        >
          <BenchmarkHistory
            items={(benchmarks.data?.data?.items ?? []).filter((item) => item.outcome !== null)}
            unit={unit}
          />
        </QueryState>
      </Card>
    </section>
  )
}
