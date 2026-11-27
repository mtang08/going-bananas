import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Trends } from '../src/pages/Trends'
import type {
  AerobicWindowValue,
  IntensityValue,
  LongRunValue,
  MetricResult,
  MetricWindows,
  RecoveryNight,
  RecoveryNights,
  RecoverySignal,
  SpacingValue,
  SrpeValue,
  VolumeValue,
  ZoneDistribution,
} from '../src/api/types/metrics'
import type { BenchmarkRecord } from '../src/api/types/blocks'

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  LineChart: ({ children, data }: { children: React.ReactNode; data: unknown }) => (
    <div
      data-testid={
        Array.isArray(data) && data[0] && 'ef' in data[0]
          ? 'aerobic-chart'
          : Array.isArray(data) && data[0] && 'speed' in data[0]
            ? 'progression-chart'
            : 'recovery-chart'
      }
      data-series={JSON.stringify(data)}
    >
      {children}
    </div>
  ),
  Line: () => null,
  Tooltip: () => null,
  CartesianGrid: () => null,
  XAxis: () => null,
  YAxis: () => null,
}))

const metric = <V,>(
  id: string,
  value: V | null,
  status: MetricResult<V>['status'] = 'available',
): MetricResult<V> => ({
  id,
  metric_id: id,
  method_version: 'v1',
  subject_type: 'window',
  subject_key: 'w28:2026-11-11',
  window_start: null,
  window_end: null,
  window_label: 'w28',
  status,
  quality_status: 'good',
  value,
  unit: null,
  reason_codes: [],
  quality_flags: [],
  anchor_keys: [],
  calculated_at: '2026-11-11T15:00:00Z',
  source_refs: {},
  config_hash: '0'.repeat(64),
  anchor_set_hash: null,
  dependency_hash: '1'.repeat(64),
  timezone: 'America/New_York',
  is_current: true,
})
function aerobicWindow(
  days: 28 | 84,
  runsCounted: number,
  extra: Partial<AerobicWindowValue> = {},
) {
  return metric<AerobicWindowValue>(
    'aerobic_efficiency',
    {
      window_days: days,
      runs_total: runsCounted,
      runs_counted: runsCounted,
      runs_without_result: 0,
      not_counted: {},
      ef_median_m_per_beat: runsCounted > 0 ? 1.2 : null,
      ef_early_median_m_per_beat: null,
      ef_late_median_m_per_beat: null,
      ef_change_pct: null,
      decoupling_runs_counted: 0,
      decoupling_median_pct: null,
      points: Array.from({ length: runsCounted }, (_, index) => ({
        activity_id: `aerobic-${index}`,
        local_date: `2026-11-${String(index + 1).padStart(2, '0')}`,
        session_class: 'easy',
        ef_m_per_beat: 1.2,
        mean_speed_mps: 2.8,
        mean_hr_bpm: 140,
        decoupling_pct: null,
        quality_flags: [],
      })),
      ...extra,
    },
    runsCounted > 0 ? 'available' : 'not_assessable',
  )
}
const totals = {
  start_date: '2026-10-15',
  end_date: '2026-11-11',
  runs_missing_timer: 0,
  runs_missing_distance: 0,
  timer_duration_s: 9000,
  distance_m: 16093.44,
  run_count: 5,
}
const volume: VolumeValue = {
  ...totals,
  previous: {
    ...totals,
    start_date: '2026-09-17',
    end_date: '2026-10-14',
    distance_m: 8046.72,
    run_count: 3,
    timer_duration_s: 5400,
    coverage_complete: true,
  },
}
const longRun: LongRunValue = {
  long_run_count: 1,
  latest: {
    classification: 'long',
    linked_checkin_ids: [],
    prior_max_timer_s: 4300,
    prior_max_distance_m: 12000,
    week_timer_s: 12000,
    week_distance_m: 22000,
    comparator_window: { start_date: '2026-10-12', end_date: '2026-11-08' },
    weekly_window: { start_date: '2026-11-03', end_date: '2026-11-09' },
    activity_id: 'a2',
    local_date: '2026-11-09',
    timer_s: 4800,
    distance_m: 13440,
    duration_ratio_to_recent_max: 1.12,
    distance_ratio_to_recent_max: 1.1,
    weekly_share_duration: 0.4,
    weekly_share_distance: 0.41,
    classification_source: 'plan_link',
    classification_confidence: 'high',
    delayed_symptom_status: 'unknown',
  },
}
const srpe: SrpeValue = {
  duration_total_s: 9000,
  duration_with_rpe_s: 2790,
  sessions_without_load: 3,
  sessions_missing_duration: 0,
  load_au: 420,
  sessions_with_rpe: 2,
  sessions_total: 5,
  coverage_duration: 0.31,
  coverage_sessions: 0.4,
}
const zone: ZoneDistribution = {
  status: 'not_assessable',
  reason_codes: ['ANCHOR_MISSING'],
  easy_s: null,
  moderate_s: null,
  high_s: null,
  valid_s: null,
  fraction_valid: null,
  fraction_timer: null,
  unclassified_s: null,
  unknown_s: null,
  eligible_timer_s: null,
  coverage: null,
  confidence: null,
}
const spacing: SpacingValue = {
  sessions: [],
  sequence: [
    {
      subject_key: 'q1',
      classes: ['quality'],
      local_date: '2026-11-05',
      session_uid: 's1',
      activity_id: null,
      source: 'plan',
      start_low: null,
      start_high: null,
      end_low: null,
      end_high: null,
    },
    {
      subject_key: 'l1',
      classes: ['long'],
      local_date: '2026-11-09',
      session_uid: 's2',
      activity_id: null,
      source: 'plan',
      start_low: null,
      start_high: null,
      end_low: null,
      end_high: null,
    },
  ],
  gaps: [
    {
      from_class: 'quality',
      to_class: 'long',
      from_date: '2026-11-05',
      to_date: '2026-11-09',
      hours_min: 96,
      hours_max: 96,
      confidence: 'high',
    },
  ],
}
const windows: MetricWindows = {
  aerobic: { w28: null, w84: null },
  as_of: '2026-11-11',
  windows: [
    { days: 7, volume: null, srpe: null, intensity: null, long_run: null, srpe_strength: null },
    {
      days: 28,
      volume: metric('run_volume_frequency', volume),
      srpe: metric('session_rpe_load', srpe),
      intensity: metric<IntensityValue>('time_in_intensity', {
        hr: zone,
        speed: zone,
      }),
      long_run: metric('long_run_exposure', longRun),
      srpe_strength: null,
    },
  ],
  spacing: metric('hard_session_spacing', spacing),
  symptoms: null,
}
const signal = (value: number | null, status: RecoverySignal['status']): RecoverySignal => ({
  baseline_median: null,
  baseline_mad: null,
  deviation: null,
  reason_codes: [],
  quality_flags: [],
  partition: null,
  status,
  value,
  baseline_state: 'established',
  valid_nights: 30,
  z: null,
  adverse: status === 'missing' ? null : false,
})
const night = (date: string, missing: boolean): RecoveryNight => ({
  status: missing ? 'missing' : 'available',
  quality_status: missing ? null : 'good',
  reason_codes: [],
  quality_flags: [],
  fatigue: null,
  illness: null,
  local_date: date,
  sleep: signal(missing ? null : 25200, missing ? 'missing' : 'available'),
  hrv: signal(missing ? null : 60, missing ? 'missing' : 'available'),
  resting_hr: signal(missing ? null : 52, missing ? 'missing' : 'available'),
  subjective_poor: missing ? null : false,
  discordance: missing ? null : false,
})
const recovery: RecoveryNights = {
  start: '2026-10-15',
  end: '2026-11-11',
  nights: [night('2026-11-07', true), night('2026-11-08', false)],
}
const progressionPoint = (id: string, status: 'available' | 'not_assessable') => ({
  session_uid: id,
  activity_id: id,
  local_date: '2026-11-09',
  planned_date: '2026-11-09',
  recipe_id: 'REC003',
  intent: 'Threshold',
  signature: 'ws1:4xt300',
  recovery_s: 360,
  target_modalities: ['speed'],
  sport: 'running',
  completion_status: 'unknown',
  status,
  reason_codes: status === 'available' ? [] : ['WATCH_WORKOUT_MISMATCH'],
  quality_flags: [],
  n_planned: 4,
  n_completed: status === 'available' ? 4 : null,
  step_completion_ratio: 1,
  reps_used: 4,
  reps_used_hr: 4,
  work_speed_mps: 3.6,
  work_hr_bpm: 160,
  work_m_per_beat: 1.35,
  cv_speed: null,
  last_first_change_pct: null,
  target_coverage: null,
  interval_result_id: id,
})
const g4x5 = {
  group_key: 'sig:ws1:4xt300',
  group_by: 'signature',
  signature: 'ws1:4xt300',
  signatures: ['ws1:4xt300'],
  recipe_ids: ['REC003'],
  sessions_total: 3,
  sessions_assessable: 2,
  latest_date: '2026-11-09',
  points: [
    progressionPoint('a', 'available'),
    progressionPoint('b', 'not_assessable'),
    progressionPoint('c', 'available'),
  ],
}
let progressionData = {
  start: '2026-05-15',
  end: '2026-11-11',
  group_by: 'signature',
  groups: [g4x5],
}
let benchmarkData: { items: unknown[] } = { items: [] }
let windowData = windows
let recoveryData = recovery
let windowStatus = 200
let requests: string[] = []
beforeEach(() => {
  progressionData = {
    start: '2026-05-15',
    end: '2026-11-11',
    group_by: 'signature',
    groups: [g4x5],
  }
  benchmarkData = { items: [] }
  windowData = windows
  recoveryData = recovery
  windowStatus = 200
  requests = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string) => {
      const url = String(input)
      requests.push(url)
      if (url.includes('/metrics/windows') && windowStatus !== 200) {
        return new Response(
          JSON.stringify({ error: { code: 'failed', message: 'Metrics unavailable' } }),
          { status: windowStatus },
        )
      }
      const data = url.includes('/metrics/workout-progression')
        ? progressionData
        : url.includes('/blocks/benchmarks')
          ? benchmarkData
          : url.includes('/metrics/recovery')
            ? recoveryData
            : windowData
      return new Response(
        JSON.stringify({ schema_version: 'v1', data_revision: 3, mode: 'demo', data }),
        { status: 200 },
      )
    }),
  )
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Trends unit="mi" />
    </QueryClientProvider>,
  )
}

describe('Trends', () => {
  it('shows workout progression for the default signature view', async () => {
    mount()
    const card = await screen.findByTestId('trend-workout-progression')
    expect(
      await within(card).findByRole('option', { name: '4 × 5:00 · 2/3 assessed' }),
    ).toBeInTheDocument()
    expect(within(card).getAllByTestId('progression-row')).toHaveLength(3)
  })
  it('switches to session-type grouping', async () => {
    progressionData = {
      ...progressionData,
      group_by: 'recipe',
      groups: [
        {
          ...g4x5,
          group_key: 'recipe:REC003',
          signature: null as unknown as string,
          group_by: 'recipe',
        },
      ],
    }
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Same session type' }))
    await waitFor(() => expect(requests.some((url) => url.includes('group_by=recipe'))).toBe(true))
    const card = screen.getByTestId('trend-workout-progression')
    expect(
      await within(card).findByRole('option', { name: 'Threshold intervals · 2/3 assessed' }),
    ).toBeInTheDocument()
    expect(within(card).getByRole('columnheader', { name: 'Work steps' })).toBeInTheDocument()
  })
  it('explains an empty progression', async () => {
    progressionData = { ...progressionData, groups: [] }
    mount()
    expect(
      await screen.findByText('No structured workouts in the last 180 days.'),
    ).toBeInTheDocument()
  })
  it('collapses only panels that are not yet assessable', async () => {
    mount()
    const disclosure = await screen.findByTestId('trends-not-assessable')
    expect(disclosure).not.toHaveAttribute('open')
    expect(disclosure.querySelector('summary')).toHaveTextContent('Not yet assessable (2)')
    expect(screen.getByTestId('trend-intensity').closest('details')).toBe(disclosure)
    expect(screen.getByTestId('trend-aerobic').closest('details')).toBe(disclosure)
    for (const id of [
      'trend-long-run',
      'trend-srpe',
      'trend-spacing',
      'trend-volume',
      'trend-recovery',
    ])
      expect(screen.getByTestId(id).closest('details')).toBeNull()
  })
  it('moves missing window results into the disclosure', async () => {
    mount()
    await screen.findByText('10.0 mi')
    fireEvent.click(screen.getByRole('button', { name: '7 days' }))
    const disclosure = screen.getByTestId('trends-not-assessable')
    expect(disclosure.querySelector('summary')).toHaveTextContent('Not yet assessable (4)')
    expect(screen.getByText('Volume: missing').closest('details')).toBeNull()
    expect(screen.getByText('Session RPE load: missing').closest('details')).toBe(disclosure)
  })
  it('shows intensity in the grid once a zone is available', async () => {
    windowData = {
      ...windows,
      aerobic: { w28: null, w84: aerobicWindow(84, 1) },
      windows: windows.windows.map((window) =>
        window.days !== 28
          ? window
          : {
              ...window,
              intensity: metric<IntensityValue>('time_in_intensity', {
                hr: {
                  ...zone,
                  status: 'available',
                  reason_codes: [],
                  easy_s: 5400,
                  moderate_s: 600,
                  high_s: 0,
                  unknown_s: 60,
                  coverage: 0.95,
                  confidence: 'moderate',
                },
                speed: zone,
              }),
            },
      ),
    }
    mount()
    await screen.findByTestId('trend-intensity')
    expect(screen.getByTestId('trend-intensity').closest('details')).toBeNull()
    expect(screen.queryByTestId('trends-not-assessable')).toBeNull()
  })
  it('shows aerobic efficiency summaries and chart', async () => {
    const w84 = aerobicWindow(84, 8)
    windowData = {
      ...windows,
      aerobic: {
        w28: aerobicWindow(28, 7, {
          ef_median_m_per_beat: 1.185,
          ef_change_pct: 3.58,
          decoupling_median_pct: 1.88,
          decoupling_runs_counted: 1,
        }),
        w84,
      },
    }
    mount()
    const card = await screen.findByTestId('trend-aerobic')
    expect(card.closest('details')).toBeNull()
    expect(card).toHaveTextContent(
      '28 days: median 1.19 m/beat over 7 runs · +3.6% early → late · median drift 1.9% (1 run)',
    )
    expect(card).toHaveTextContent('84 days: median 1.20 m/beat over 8 runs')
    expect(card).toHaveTextContent('Descriptive only.')
    const chart = within(card).getByRole('img', {
      name: 'Metres per heartbeat on steady runs, last 84 days',
    })
    expect(within(chart).getByTestId('aerobic-chart')).toHaveAttribute(
      'data-series',
      JSON.stringify(
        w84.value?.points.map((point) => ({
          date: point.local_date,
          ef: point.ef_m_per_beat,
          pace: '9:35 /mi',
          hr: 140,
        })),
      ),
    )
    fireEvent.click(within(card).getByText('Run details (8)'))
    const firstRun = within(card).getByRole('row', { name: /Nov 8/ })
    expect(firstRun).toHaveTextContent('1.20')
    expect(firstRun).toHaveTextContent('9:35 /mi')
    expect(firstRun).toHaveTextContent('140 bpm')
  })
  it('defers aerobic efficiency without eligible runs', async () => {
    windowData = {
      ...windows,
      aerobic: {
        w28: null,
        w84: aerobicWindow(84, 0, {
          runs_total: 5,
          not_counted: { STRUCTURED_SESSION: 3, TOO_SHORT: 2 },
        }),
      },
    }
    mount()
    const disclosure = await screen.findByTestId('trends-not-assessable')
    fireEvent.click(within(disclosure).getByText(/Not yet assessable/))
    const card = within(disclosure).getByTestId('trend-aerobic')
    expect(card).toHaveTextContent(
      '84 days: no steady easy or long runs (Structured workout 3, Too short after the 10-minute warm-up 2)',
    )
    expect(within(card).queryByRole('img')).toBeNull()
  })
  it('shows missing aerobic windows as missing', async () => {
    mount()
    const disclosure = await screen.findByTestId('trends-not-assessable')
    const card = within(disclosure).getByTestId('trend-aerobic')
    expect(card).toHaveTextContent('28 days: missing')
    expect(card).toHaveTextContent('84 days: missing')
  })
  it('shows benchmark history outside the not-assessable disclosure', async () => {
    mount()
    const card = await screen.findByTestId('trend-benchmarks')
    expect(
      await within(card).findByText(
        'No benchmark results yet. A block review sets one about every 6 weeks.',
      ),
    ).toBeInTheDocument()
    expect(card.closest('details')).toBeNull()
  })
  it('charts repeated distances and lists outcomes', async () => {
    const rec = (
      id: string,
      distance_m: number,
      local_date: string,
      result_s: number,
      outcome: BenchmarkRecord['outcome'] | null,
    ) => ({
      id,
      distance_m,
      local_date,
      result_s,
      outcome,
      block_uid: 'b',
      block_version: 1,
      objective: 'Build',
      protocol: '5 km solo time trial',
      compared_with: null,
      match_method: 'auto',
      activity_id: null,
      event_id: null,
    })
    benchmarkData = {
      items: [
        rec('b1', 5000, '2026-08-30', 1300, 'consolidate'),
        rec('b2', 5000, '2026-11-10', 1290, 'progress'),
        rec('b3', 10000, '2026-10-04', 2700, 'inconclusive'),
        rec('b4', 5000, '2026-07-01', 1400, null),
      ],
    }
    mount()
    const chart = await screen.findByRole('img', { name: '3.1 mi benchmark results' })
    expect(screen.getAllByRole('img', { name: '3.1 mi benchmark results' })).toHaveLength(1)
    expect(screen.queryByRole('img', { name: '6.2 mi benchmark results' })).toBeNull()
    expect(within(chart).getByTestId('recovery-chart')).toHaveAttribute(
      'data-series',
      JSON.stringify([
        { date: '2026-08-30', result_s: 1300 },
        { date: '2026-11-10', result_s: 1290 },
      ]),
    )
    const table = screen.getByRole('table', { name: 'Benchmark results' })
    expect(table.querySelectorAll('tbody tr')).toHaveLength(3)
    for (const label of ['Progress', 'Consolidate', 'Inconclusive'])
      expect(within(table).getByText(label)).toBeInTheDocument()
  })
  it('shows 28-day volume without extrapolating missing values', async () => {
    mount()
    expect(await screen.findByText('10.0 mi')).toBeInTheDocument()
    expect(screen.getByText('5 runs · 2h 30m timer time')).toBeInTheDocument()
    expect(screen.getByText('Previous 28 days: 5.0 mi · 3 runs')).toBeInTheDocument()
  })
  it('labels incomplete previous volume instead of treating it as full coverage', async () => {
    windowData = {
      ...windows,
      windows: windows.windows.map((window) =>
        window.days !== 28
          ? window
          : {
              ...window,
              volume: metric('run_volume_frequency', {
                ...volume,
                previous: { ...volume.previous!, coverage_complete: false },
              }),
            },
      ),
    }
    mount()
    expect(
      await screen.findByText('Previous 28 days (incomplete): 5.0 mi · 3 runs'),
    ).toBeInTheDocument()
  })
  it('discloses partial long-run evidence when no confirmed long run is available', async () => {
    const partial = {
      ...metric<LongRunValue>(
        'long_run_exposure',
        {
          long_run_count: 0,
          latest: null,
        },
        'partial',
      ),
      quality_status: null,
      reason_codes: [
        'CLASSIFICATION_UNKNOWN',
        'ACTIVITY_RESULT_MISSING',
        'SYNC_COVERAGE_INCOMPLETE',
      ],
      quality_flags: ['SOURCE_PARTIAL'],
    }
    windowData = {
      ...windows,
      windows: windows.windows.map((window) =>
        window.days !== 28
          ? window
          : {
              ...window,
              long_run: partial,
            },
      ),
    }
    mount()
    expect(await screen.findByText('No confirmed long run in available data.')).toBeInTheDocument()
    expect(screen.getByText('0 long runs in 28 days (partial)')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Partial data: CLASSIFICATION_UNKNOWN, Some runs not analysed yet, Sync incomplete for this window, SOURCE_PARTIAL',
      ),
    ).toBeInTheDocument()
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
      'Heart rate: No anchor — add aerobic-upper and threshold-lower anchors in Settings.',
    )
  })
  it('renders measured zero high-intensity time', async () => {
    windowData = {
      ...windows,
      windows: windows.windows.map((window) =>
        window.days !== 28
          ? window
          : {
              ...window,
              intensity: metric<IntensityValue>('time_in_intensity', {
                hr: {
                  ...zone,
                  status: 'available',
                  reason_codes: [],
                  easy_s: 5400,
                  moderate_s: 600,
                  high_s: 0,
                  unknown_s: 60,
                  coverage: 0.95,
                  confidence: 'moderate',
                },
                speed: zone,
              }),
            },
      ),
    }
    mount()
    expect(await screen.findByTestId('intensity-hr')).toHaveTextContent('Heart rate · Coverage 95%')
    expect(
      screen.getByRole('img', {
        name: 'Heart rate intensity time distribution; durations listed below',
      }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('img', {
        name: 'Pace intensity time distribution; durations listed below',
      }),
    ).not.toBeInTheDocument()
    expect(screen.getByText('Unknown · 1m')).toBeInTheDocument()
    expect(screen.getByText('High · 0m')).toBeInTheDocument()
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
    fireEvent.click(screen.getByText('Nightly details (2 nights)'))
    const missingRow = document.querySelector(
      '[data-testid="recovery-night"][data-date="2026-11-07"]',
    ) as HTMLElement
    expect(missingRow).toHaveClass('missing')
    expect(within(missingRow).getAllByText('missing')).toHaveLength(3)
    const measured = document.querySelector(
      '[data-testid="recovery-night"][data-date="2026-11-08"]',
    ) as HTMLElement
    expect(within(measured).getByText('7h 00m')).toBeInTheDocument()
    expect(within(measured).getByText('60 ms')).toBeInTheDocument()
    expect(within(measured).getByText('52 bpm')).toBeInTheDocument()
    expect(within(measured).getByText('Established')).toBeInTheDocument()
    expect(within(measured).getByText('None')).toBeInTheDocument()
    expect(screen.getByTestId('recovery-chart')).toHaveAttribute(
      'data-series',
      JSON.stringify([
        { date: '2026-11-07', hrv: null, rhr: null },
        { date: '2026-11-08', hrv: 60, rhr: 52 },
      ]),
    )
  })
  it('queries the recovery range from server as_of only', async () => {
    mount()
    await waitFor(() =>
      expect(requests).toContain('/api/v1/metrics/recovery?start=2026-10-15&end=2026-11-11'),
    )
    expect(
      requests.every(
        (url) =>
          url === '/api/v1/blocks/benchmarks' ||
          url === '/api/v1/metrics/windows' ||
          url === '/api/v1/metrics/recovery?start=2026-10-15&end=2026-11-11' ||
          url === '/api/v1/metrics/workout-progression?group_by=signature',
      ),
    ).toBe(true)
  })
  it('shows windows request errors', async () => {
    windowStatus = 500
    mount()
    expect(await screen.findByText('Could not load this view')).toBeInTheDocument()
    expect(screen.getByText('Metrics unavailable')).toBeInTheDocument()
  })
})

it('sorts recovery charts chronologically and keeps the latest summary visible when details are collapsed', async () => {
  recoveryData = { ...recovery, nights: [night('2026-11-08', true), night('2026-11-07', false)] }
  mount()
  const summary = await screen.findByLabelText('Latest recovery night')
  expect(within(summary).getByText('Latest night · Nov 8')).toBeVisible()
  expect(within(summary).getAllByText('missing')).toHaveLength(3)
  const disclosure = screen.getByText('Nightly details (2 nights)').closest('details')!
  expect(disclosure).not.toHaveAttribute('open')
  expect(screen.getByTestId('recovery-chart')).toHaveAttribute(
    'data-series',
    JSON.stringify([
      { date: '2026-11-07', hrv: 60, rhr: 52 },
      { date: '2026-11-08', hrv: null, rhr: null },
    ]),
  )
  fireEvent.click(screen.getByText('Nightly details (2 nights)'))
  expect(screen.getByRole('table', { name: 'Recovery nights' })).toBeVisible()
})
