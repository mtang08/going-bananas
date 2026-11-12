import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Trends } from '../src/pages/Trends'
import type {
  IntensityValue, LongRunValue, MetricResult, MetricWindows, RecoveryNight,
  RecoveryNights, RecoverySignal, SpacingValue, SrpeValue, VolumeValue, ZoneDistribution,
} from '../src/api'

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  LineChart: ({ children, data }: { children: React.ReactNode; data: unknown }) =>
    <div data-testid="recovery-chart" data-series={JSON.stringify(data)}>{children}</div>,
  Line: () => null, Tooltip: () => null, CartesianGrid: () => null, XAxis: () => null, YAxis: () => null,
}))

const metric = <V,>(id: string, value: V | null, status: MetricResult<V>['status'] = 'available'): MetricResult<V> => ({
  id, metric_id: id, method_version: 'v1', subject_type: 'window', subject_key: 'w28:2026-11-11',
  window_start: null, window_end: null, window_label: 'w28', status, quality_status: 'good',
  value, unit: null, reason_codes: [], quality_flags: [], anchor_keys: [],
  calculated_at: '2026-11-11T15:00:00Z', source_refs: {}, config_hash: '0'.repeat(64),
  anchor_set_hash: null, dependency_hash: '1'.repeat(64), timezone: 'America/New_York', is_current: true,
})
const totals = {
  start_date: '2026-10-15', end_date: '2026-11-11', runs_missing_timer: 0,
  runs_missing_distance: 0, timer_duration_s: 9000, distance_m: 16093.44, run_count: 5,
}
const volume: VolumeValue = { ...totals, previous: {
  ...totals, start_date: '2026-09-17', end_date: '2026-10-14',
  distance_m: 8046.72, run_count: 3, timer_duration_s: 5400, coverage_complete: true,
} }
const longRun: LongRunValue = { long_run_count: 1, latest: {
  classification: 'long', linked_checkin_ids: [], prior_max_timer_s: 4300,
  prior_max_distance_m: 12000, week_timer_s: 12000, week_distance_m: 22000,
  comparator_window: { start_date: '2026-10-12', end_date: '2026-11-08' },
  weekly_window: { start_date: '2026-11-03', end_date: '2026-11-09' },
  activity_id: 'a2', local_date: '2026-11-09', timer_s: 4800, distance_m: 13440,
  duration_ratio_to_recent_max: 1.12, distance_ratio_to_recent_max: 1.1,
  weekly_share_duration: .4, weekly_share_distance: .41,
  classification_source: 'plan_link', classification_confidence: 'high',
  delayed_symptom_status: 'unknown',
} }
const srpe: SrpeValue = {
  duration_total_s: 9000, duration_with_rpe_s: 2790, sessions_without_load: 3,
  sessions_missing_duration: 0, load_au: 420, sessions_with_rpe: 2,
  sessions_total: 5, coverage_duration: .31, coverage_sessions: .4,
}
const zone: ZoneDistribution = {
  status: 'not_assessable', reason_codes: ['ANCHOR_MISSING'], easy_s: null,
  moderate_s: null, high_s: null, valid_s: null, fraction_valid: null,
  fraction_timer: null, unclassified_s: null, unknown_s: null,
  eligible_timer_s: null, coverage: null, confidence: null,
}
const spacing: SpacingValue = {
  sessions: [],
  sequence: [
    { subject_key: 'q1', classes: ['quality'], local_date: '2026-11-05',
      session_uid: 's1', activity_id: null, source: 'plan',
      start_low: null, start_high: null, end_low: null, end_high: null },
    { subject_key: 'l1', classes: ['long'], local_date: '2026-11-09',
      session_uid: 's2', activity_id: null, source: 'plan',
      start_low: null, start_high: null, end_low: null, end_high: null },
  ],
  gaps: [{ from_class: 'quality', to_class: 'long', from_date: '2026-11-05',
    to_date: '2026-11-09', hours_min: 96, hours_max: 96, confidence: 'high' }],
}
const windows: MetricWindows = {
  as_of: '2026-11-11', windows: [
    { days: 7, volume: null, srpe: null, intensity: null, long_run: null, srpe_strength: null },
    { days: 28, volume: metric('run_volume_frequency', volume),
      srpe: metric('session_rpe_load', srpe), intensity: metric<IntensityValue>('time_in_intensity', {
        hr: zone, speed: zone,
      }), long_run: metric('long_run_exposure', longRun), srpe_strength: null },
  ],
  spacing: metric('hard_session_spacing', spacing), symptoms: null,
}
const signal = (value: number | null, status: RecoverySignal['status']): RecoverySignal => ({
  baseline_median: null, baseline_mad: null, deviation: null, reason_codes: [],
  quality_flags: [], partition: null, status, value, baseline_state: 'established',
  valid_nights: 30, z: null, adverse: status === 'missing' ? null : false,
})
const night = (date: string, missing: boolean): RecoveryNight => ({
  status: missing ? 'missing' : 'available', quality_status: missing ? null : 'good',
  reason_codes: [], quality_flags: [], fatigue: null, illness: null, local_date: date,
  sleep: signal(missing ? null : 25200, missing ? 'missing' : 'available'),
  hrv: signal(missing ? null : 60, missing ? 'missing' : 'available'),
  resting_hr: signal(missing ? null : 52, missing ? 'missing' : 'available'),
  subjective_poor: missing ? null : false, discordance: missing ? null : false,
})
const recovery: RecoveryNights = {
  start: '2026-10-15', end: '2026-11-11', nights: [
    night('2026-11-07', true), night('2026-11-08', false),
  ],
}
let windowData = windows
let recoveryData = recovery
let windowStatus = 200
let requests: string[] = []
beforeEach(() => {
  windowData = windows
  recoveryData = recovery
  windowStatus = 200
  requests = []
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const url = String(input)
    requests.push(url)
    if (url.includes('/metrics/windows') && windowStatus !== 200) {
      return new Response(JSON.stringify({ error: { code: 'failed', message: 'Metrics unavailable' } }), { status: windowStatus })
    }
    const data = url.includes('/metrics/recovery') ? recoveryData : windowData
    return new Response(JSON.stringify({ schema_version: 'v1', data_revision: 3, mode: 'demo', data }), { status: 200 })
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><Trends unit="mi"/></QueryClientProvider>)
}

describe('Trends', () => {
  it('shows 28-day volume without extrapolating missing values', async () => {
    mount()
    expect(await screen.findByText('10.0 mi')).toBeInTheDocument()
    expect(screen.getByText('5 runs · 2h 30m timer time')).toBeInTheDocument()
    expect(screen.getByText('Previous 28 days: 5.0 mi · 3 runs')).toBeInTheDocument()
  })
  it('labels incomplete previous volume instead of treating it as full coverage', async () => {
    windowData = { ...windows, windows: windows.windows.map(window => window.days !== 28 ? window : {
      ...window, volume: metric('run_volume_frequency', {
        ...volume, previous: { ...volume.previous!, coverage_complete: false },
      }),
    }) }
    mount()
    expect(await screen.findByText('Previous 28 days (incomplete): 5.0 mi · 3 runs')).toBeInTheDocument()
  })
  it('discloses partial long-run evidence when no confirmed long run is available', async () => {
    const partial = { ...metric<LongRunValue>('long_run_exposure', {
      long_run_count: 0, latest: null,
    }, 'partial'), quality_status: null,
      reason_codes: ['CLASSIFICATION_UNKNOWN', 'ACTIVITY_RESULT_MISSING', 'SYNC_COVERAGE_INCOMPLETE'],
      quality_flags: ['SOURCE_PARTIAL'] }
    windowData = { ...windows, windows: windows.windows.map(window => window.days !== 28 ? window : {
      ...window, long_run: partial,
    }) }
    mount()
    expect(await screen.findByText('No confirmed long run in available data.')).toBeInTheDocument()
    expect(screen.getByText('0 long runs in 28 days (partial)')).toBeInTheDocument()
    expect(screen.getByText('Partial data: CLASSIFICATION_UNKNOWN, ACTIVITY_RESULT_MISSING, SYNC_COVERAGE_INCOMPLETE, SOURCE_PARTIAL')).toBeInTheDocument()
  })
  it('keeps an absent window explicit', async () => {
    mount()
    await screen.findByText('10.0 mi')
    fireEvent.click(screen.getByRole('button', { name: '7 days' }))
    expect(screen.getByText('Volume: missing')).toBeInTheDocument()
    expect(screen.getByText('Session RPE load: missing')).toBeInTheDocument()
    expect(screen.queryByText('0.0 mi')).not.toBeInTheDocument()
  })
  it('reports missing anchors explicitly', async () => {
    mount()
    expect(await screen.findByTestId('intensity-hr')).toHaveTextContent(
      'Heart rate: No anchor — add aerobic-upper and threshold-lower anchors in Settings.')
  })
  it('renders measured zero high-intensity time', async () => {
    windowData = { ...windows, windows: windows.windows.map(window => window.days !== 28 ? window : {
      ...window, intensity: metric<IntensityValue>('time_in_intensity', {
        hr: { ...zone, status: 'available', reason_codes: [], easy_s: 5400,
          moderate_s: 600, high_s: 0, unknown_s: 60, coverage: .95, confidence: 'moderate' },
        speed: zone,
      }),
    }) }
    mount()
    expect(await screen.findByTestId('intensity-hr')).toHaveTextContent(
      'Heart rate: Easy 1h 30m · Moderate 10m · High 0m · Unknown 1m · Coverage 95%')
  })
  it('shows sRPE, long-run context and spacing', async () => {
    mount()
    expect(await screen.findByText('420 AU')).toBeInTheDocument()
    expect(screen.getByText('RPE on 2 of 5 runs')).toBeInTheDocument()
    expect(screen.getByText('Duration coverage 31%')).toBeInTheDocument()
    expect(screen.getByText('Latest long run Nov 9 · 1h 20m · 8.4 mi')).toBeInTheDocument()
    expect(screen.getByText('Delayed symptoms: unknown (no follow-up)')).toBeInTheDocument()
    expect(screen.getByText('Quality → Long run: 96 h')).toBeInTheDocument()
  })
  it('preserves missing recovery nights and null chart gaps', async () => {
    mount()
    await waitFor(() => expect(screen.getAllByTestId('recovery-night')).toHaveLength(2))
    const missingRow = document.querySelector('[data-testid="recovery-night"][data-date="2026-11-07"]') as HTMLElement
    expect(missingRow).toHaveClass('missing')
    expect(within(missingRow).getAllByText('missing')).toHaveLength(3)
    const measured = document.querySelector('[data-testid="recovery-night"][data-date="2026-11-08"]') as HTMLElement
    expect(within(measured).getByText('7h 00m')).toBeInTheDocument()
    expect(within(measured).getByText('60 ms')).toBeInTheDocument()
    expect(within(measured).getByText('52 bpm')).toBeInTheDocument()
    expect(within(measured).getByText('Established')).toBeInTheDocument()
    expect(within(measured).getByText('None')).toBeInTheDocument()
    expect(screen.getByTestId('recovery-chart')).toHaveAttribute('data-series',
      JSON.stringify([{ date: '2026-11-07', hrv: null, rhr: null },
        { date: '2026-11-08', hrv: 60, rhr: 52 }]))
  })
  it('queries the recovery range from server as_of only', async () => {
    mount()
    await waitFor(() => expect(requests).toContain('/api/v1/metrics/recovery?start=2026-10-15&end=2026-11-11'))
    expect(requests.every(url => url === '/api/v1/metrics/windows' ||
      url === '/api/v1/metrics/recovery?start=2026-10-15&end=2026-11-11')).toBe(true)
  })
  it('shows windows request errors', async () => {
    windowStatus = 500
    mount()
    expect(await screen.findByText('Could not load this view')).toBeInTheDocument()
    expect(screen.getByText('Metrics unavailable')).toBeInTheDocument()
  })
})
