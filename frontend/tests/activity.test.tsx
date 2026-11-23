import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Activity } from '../src/pages/Activity'
import type {
  ActivityExecution,
  IntensityValue,
  IntervalValue,
  MetricResult,
  PlannedActualValue,
  ZoneDistribution,
} from '../src/api/types/metrics'

const metric = <V,>(
  metric_id: string,
  value: V | null,
  status: MetricResult<V>['status'] = 'available',
  reason_codes: string[] = [],
): MetricResult<V> => ({
  id: metric_id,
  metric_id,
  method_version: 'v1',
  subject_type: 'activity',
  subject_key: 'a1',
  window_start: null,
  window_end: null,
  window_label: null,
  status,
  quality_status: 'good',
  value,
  unit: null,
  reason_codes,
  quality_flags: [],
  anchor_keys: [],
  calculated_at: '2026-11-08T13:00:00Z',
  source_refs: {},
  config_hash: '0'.repeat(64),
  anchor_set_hash: null,
  dependency_hash: '1'.repeat(64),
  timezone: 'America/New_York',
  is_current: true,
})
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
const structure: NonNullable<NonNullable<ActivityExecution['planned']>['structure']> = [
  {
    type: 'warmup',
    duration_type: 'time',
    duration_value: 600,
    target: { modality: 'effort', low: null, high: null, effort_cue: 'easy' },
  },
  {
    type: 'repeat',
    count: 4,
    steps: [
      {
        type: 'work',
        duration_type: 'distance',
        duration_value: 800,
        target: { modality: 'speed', low: 3.8, high: 4, effort_cue: null },
      },
      {
        type: 'recovery',
        duration_type: 'time',
        duration_value: 120,
        target: { modality: 'effort', low: null, high: null, effort_cue: 'easy jog' },
      },
    ],
  },
  {
    type: 'cooldown',
    duration_type: 'time',
    duration_value: 600,
    target: { modality: 'effort', low: null, high: null, effort_cue: 'easy' },
  },
]
const reps: IntervalValue['reps'] = [205, 208, 210, 214].map((time, index) => ({
  rep: index + 1,
  planned_step: 2 + 2 * index,
  step_path: '1.steps.0',
  repeat_index: index,
  lap_indexes: [1 + 2 * index],
  observed: true,
  fully_completed: true,
  status: 'available',
  reason_codes: [],
  planned_duration_type: 'distance',
  planned_value: 800,
  actual_timer_s: time,
  actual_distance_m: 800,
  completion_ratio: 1,
  mean_speed_mps: 800 / time,
  speed_status: 'available',
  speed_reason_codes: [],
  speed_coverage: 1,
  target_modality: 'speed',
  target_low: 3.8,
  target_high: 4,
  target_valid_s: time,
  target_in_range_s: index === 3 ? 0 : time,
  in_target: index !== 3,
  hr_median_bpm: null,
  flags: [],
}))
const base: ActivityExecution = {
  aerobic: null,
  activity: {
    id: 'a1',
    local_date: '2026-11-08',
    sport: 'running',
    distance_m: 6900,
    timer_s: 2517,
    elapsed_s: 2600,
    fit_status: 'decoded',
    start_at: '2026-11-08T12:00:00Z',
    end_at: '2026-11-08T12:43:20Z',
  },
  planned: {
    session_uid: 's1',
    local_date: '2026-11-08',
    kind: 'run',
    recipe_id: null,
    custom: true,
    intent: '4 × 800 m',
    planned_duration_s: null,
    planned_distance_m: null,
    structure,
    legacy_unstructured: false,
    legacy_payload: null,
    placeholder: false,
    locked: false,
  },
  completion: {
    id: 'c1',
    input_version: 1,
    session_uid: 's1',
    activity_id: 'a1',
    strong_workout_id: null,
    manual_session_id: null,
    status: 'completed_as_planned',
    match_method: 'explicit',
    modification_reason: null,
    reason_note: null,
    version: 1,
    updated_at: '2026-11-08T13:00:00Z',
    local_date: '2026-11-08',
  },
  laps: Array.from({ length: 10 }, (_, i) => ({
    lap_index: i,
    start_at: '2026-11-08T12:00:00Z',
    timer_s: i % 2 ? 205 : 300,
    elapsed_s: i % 2 ? 205 : 300,
    distance_m: i % 2 ? 800 : 1000,
    avg_speed_mps: i % 2 ? 800 / 205 : 3,
    avg_hr_bpm: null,
    max_hr_bpm: null,
    lap_trigger: null,
    wkt_step_index: i,
  })),
  watch_steps: [
    {
      message_index: 0,
      step_name: 'Warmup',
      intensity: 'warmup',
      duration_type: 'time',
      duration_value: 600,
      target_type: null,
      target_low: null,
      target_high: null,
      repeat_from: null,
      repeat_count: null,
    },
    {
      message_index: 1,
      step_name: null,
      intensity: 'interval',
      duration_type: 'distance',
      duration_value: 800,
      target_type: null,
      target_low: null,
      target_high: null,
      repeat_from: null,
      repeat_count: null,
    },
    {
      message_index: 2,
      step_name: null,
      intensity: 'recovery',
      duration_type: 'time',
      duration_value: 120,
      target_type: null,
      target_low: null,
      target_high: null,
      repeat_from: null,
      repeat_count: null,
    },
    {
      message_index: 3,
      step_name: null,
      intensity: null,
      duration_type: 'repeat_until_steps_cmplt',
      duration_value: null,
      target_type: null,
      target_low: null,
      target_high: null,
      repeat_from: 1,
      repeat_count: 4,
    },
    {
      message_index: 4,
      step_name: 'Cooldown',
      intensity: 'cooldown',
      duration_type: 'time',
      duration_value: 600,
      target_type: null,
      target_low: null,
      target_high: null,
      repeat_from: null,
      repeat_count: null,
    },
  ],
  planned_actual: metric<PlannedActualValue>('planned_actual_session', {
    overall_status: 'completed_as_planned',
    certainty: 'committed',
    kind: 'run',
    candidate_activity_ids: [],
    calendar_version: 2,
    match_method: 'explicit',
    components: [{ name: 'duration_ratio', value: 0.98, status: 'met' }],
  }),
  intervals: metric<IntervalValue>('work_interval_execution', {
    reps,
    n_planned: 4,
    n_observed: 4,
    n_completed: 4,
    step_completion_ratio: 1,
    cv_speed: 1.8,
    last_first_change_pct: -4.2,
    completed_work_s: 837,
    planned_work_s: null,
    completed_work_m: 3200,
    planned_work_m: 3200,
    target_coverage: 0.75,
  }),
  intensity: metric<IntensityValue>('time_in_intensity', { hr: zone, speed: zone }),
  rpe: { effective: 7, source: 'garmin_fit', manual: null, garmin_fit: 7, srpe_load_au: 293.6 },
  symptoms: [],
}
const historyPoint = (id: string, day: string) => ({
  session_uid: id,
  activity_id: id,
  local_date: day,
  planned_date: day,
  recipe_id: 'REC003',
  intent: 'Threshold',
  signature: 'ws1:4xd800',
  recovery_s: 360,
  target_modalities: ['speed'],
  sport: 'running',
  completion_status: 'completed_as_planned',
  status: 'available' as const,
  reason_codes: [],
  quality_flags: [],
  n_planned: 4,
  n_completed: 4,
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
const defaultHistory = {
  activity_id: 'a1',
  signature: 'ws1:4xd800' as string | null,
  reason: null as string | null,
  points: [
    historyPoint('a3', '2026-10-01'),
    historyPoint('a2', '2026-10-15'),
    historyPoint('a1', '2026-11-08'),
  ],
}
let historyFixture = defaultHistory
let fixture = base
let status = 200
let requests: { url: string; method: string }[] = []
const onCheckin = vi.fn()
beforeEach(() => {
  fixture = base
  historyFixture = defaultHistory
  status = 200
  requests = []
  onCheckin.mockClear()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: string, init?: RequestInit) => {
      requests.push({ url: String(input), method: init?.method ?? 'GET' })
      return status === 404
        ? new Response(
            JSON.stringify({ error: { code: 'not_found', message: 'Activity not found' } }),
            { status },
          )
        : new Response(
            JSON.stringify({
              schema_version: 'v1',
              data_revision: 2,
              mode: 'demo',
              data: String(input).includes('/workout-history') ? historyFixture : fixture,
            }),
            { status },
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
      <Activity activityId="a1" unit="mi" onCheckin={onCheckin} />
    </QueryClientProvider>,
  )
}

describe('Activity execution', () => {
  it('compares with previous sessions of the same workout', async () => {
    mount()
    const card = await screen.findByTestId('activity-workout-history')
    expect(await within(card).findByText('4 × 800 m work · last 3 sessions')).toBeInTheDocument()
    const rows = within(card).getAllByTestId('progression-row')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveTextContent('(this run)')
  })
  it('explains why there is no comparison', async () => {
    historyFixture = {
      activity_id: 'a1',
      signature: null,
      reason: 'NO_STRUCTURED_PLAN',
      points: [],
    }
    mount()
    expect(
      await screen.findByText('No earlier sessions to compare: Plan has no structured steps'),
    ).toBeInTheDocument()
  })
  it('skips the history request for unstructured runs', async () => {
    fixture = { ...base, planned: { ...base.planned!, structure: null }, intervals: null }
    mount()
    await screen.findByRole('heading', { name: 'Run · Sunday, November 8' })
    expect(requests.some((request) => request.url.includes('/workout-history'))).toBe(false)
  })
  it('renders structured reps, summary, plans, intensity, RPE and missing HR', async () => {
    mount()
    expect(
      await screen.findByRole('heading', { name: 'Run · Sunday, November 8' }),
    ).toBeInTheDocument()
    expect(screen.getByText('41:57')).toBeInTheDocument()
    expect(screen.getByText('9:47 /mi')).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Reps' })
    const bodyRows = within(table).getAllByRole('row').slice(1)
    expect(bodyRows).toHaveLength(4)
    expect(within(bodyRows[0]).getByText('6:52 /mi')).toBeInTheDocument()
    expect(within(bodyRows[3]).getByText('7:10 /mi')).toBeInTheDocument()
    expect(within(bodyRows[3]).getByText('No')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Completed work 13:57 · Planned work missing · Pace variation (CV) 1.8% · Last vs first rep -4.2% · Time in target 75%',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('7/10 · from Garmin')).toBeInTheDocument()
    expect(screen.getByText('Session load 294 AU')).toBeInTheDocument()
    expect(screen.getByText('Completed as planned')).toBeInTheDocument()
    expect(screen.getByText('Duration vs plan')).toBeInTheDocument()
    expect(screen.getByText('98%')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Heart rate: not assessable — add aerobic-upper and threshold-lower anchors in Settings.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('No symptom reports are linked to this run.')).toBeInTheDocument()
    expect(requests).toContainEqual({ url: '/api/v1/activities/a1/execution', method: 'GET' })
  })
  it('shows the recorded laps for each rep', async () => {
    const interval = base.intervals!
    const value = interval.value!
    const changed = [
      { ...reps[0], lap_indexes: [1] },
      { ...reps[1], lap_indexes: [2, 3] },
      { ...reps[2], lap_indexes: [], observed: false },
    ]
    fixture = { ...base, intervals: { ...interval, value: { ...value, reps: changed } } }
    mount()
    const table = await screen.findByRole('table', { name: 'Reps' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((row) => within(row).getAllByRole('cell')[1].textContent)).toEqual([
      'Lap 2',
      'Laps 3–4',
      '—',
    ])
  })

  it('shows corrected treadmill lap pace without a plan link', async () => {
    fixture = {
      ...base,
      activity: { ...base.activity, sport: 'treadmill_running' },
      planned: null,
      completion: null,
      planned_actual: null,
      intervals: null,
      laps: [{ ...base.laps[0], avg_speed_mps: 3, confirmed_pace_s_per_mile: 455 }],
    }
    mount()
    const laps = await screen.findByTestId('activity-laps')
    laps.setAttribute('open', '')
    expect(within(laps).getByRole('cell', { name: /7:35 \/mi\s*Corrected/ })).toBeVisible()
    expect(within(laps).queryByText('8:56 /mi')).toBeNull()
  })
  it('shows watch and planned steps when structure mismatches', async () => {
    fixture = {
      ...base,
      intervals: metric<IntervalValue>('work_interval_execution', null, 'not_assessable', [
        'WATCH_WORKOUT_MISMATCH',
      ]),
    }
    mount()
    expect(
      await screen.findByText(
        'The watch workout does not match the planned structure, so reps are not assessable.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('Planned steps')).toBeInTheDocument()
    expect(screen.getByText('Watch steps')).toBeInTheDocument()
    const planned = screen.getByText('Planned steps').parentElement!
    const labels = within(planned)
      .getAllByRole('listitem')
      .map((item) => item.textContent)
    expect(labels).toHaveLength(5)
    expect(within(planned).getByText('4 ×')).toBeInTheDocument()
    expect(within(planned).getByText('Work 800 m · 6:42 /mi–7:04 /mi')).toBeInTheDocument()
    expect(within(planned).getByText('Recovery 2:00 · easy jog')).toBeInTheDocument()
    expect(
      within(planned).getByText('Recovery after every rep, including the final rep.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Interval · 800 m')).toBeInTheDocument()
    expect(screen.queryByRole('table', { name: 'Reps' })).not.toBeInTheDocument()
  })
  it('explains unavailable rep comparisons with readable and unknown reasons', async () => {
    fixture = {
      ...base,
      intervals: metric<IntervalValue>('work_interval_execution', null, 'not_assessable', [
        'LAP_ALIGNMENT_AMBIGUOUS',
        'FOO_BAR',
      ]),
    }
    mount()
    expect(
      await screen.findByText(
        'Rep comparison unavailable: Laps can match the workout in more than one way, FOO_BAR',
      ),
    ).toBeInTheDocument()
  })
  it('shows readable quality flags for available intervals', async () => {
    fixture = { ...base, intervals: { ...base.intervals!, quality_flags: ['LAP_SPLIT_MERGED'] } }
    mount()
    expect(await screen.findByText('Split laps combined')).toBeInTheDocument()
  })
  it('labels a treadmill run and its flags', async () => {
    fixture = {
      ...base,
      activity: { ...base.activity, sport: 'treadmill_running' },
      planned_actual: { ...base.planned_actual!, quality_flags: ['TREADMILL_PACE_NOT_SCORED'] },
      intervals: { ...base.intervals!, quality_flags: ['TREADMILL'] },
    }
    mount()
    expect(
      await screen.findByRole('heading', { name: 'Treadmill run · Sunday, November 8' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Treadmill: pace not scored')).toBeInTheDocument()
    expect(screen.getByText('Treadmill run', { exact: true })).toBeInTheDocument()
  })
  it('makes missing FIT evidence explicit while retaining summary', async () => {
    fixture = {
      ...base,
      activity: { ...base.activity, fit_status: 'not_fetched' },
      laps: [],
      watch_steps: [],
      intervals: null,
      intensity: null,
    }
    mount()
    expect(
      await screen.findByText(
        'No decoded FIT file for this run (not fetched yet). Laps, reps, and intensity are not assessable; summary metrics are shown.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Laps are not assessable without a decoded FIT file.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Rep analysis: missing')).toBeInTheDocument()
    expect(screen.getByText('Intensity: missing')).toBeInTheDocument()
  })
  it('shows an extra run without fabricated planned reps', async () => {
    fixture = {
      ...base,
      planned: null,
      completion: { ...base.completion!, status: 'extra' },
      intervals: null,
    }
    mount()
    expect(await screen.findByText('Extra run — not in the plan.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Reps' })).not.toBeInTheDocument()
  })
  it('routes missing RPE entry through check-in', async () => {
    fixture = {
      ...base,
      rpe: { effective: null, source: null, manual: null, garmin_fit: null, srpe_load_au: null },
    }
    mount()
    expect(await screen.findByText('RPE: missing')).toBeInTheDocument()
    expect(screen.getByText('Session load missing')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Enter RPE' }))
    expect(onCheckin).toHaveBeenCalledWith({ kind: 'post_run', prompt: null, activityId: 'a1' })
  })
  it('renders symptom timing and provenance text', async () => {
    fixture = {
      ...base,
      symptoms: [
        {
          checkin_id: 'ch1',
          observed_at: '2026-11-09T12:00:00Z',
          kind: 'delayed_followup',
          site: 'posterior tibial tendon',
          side: 'left',
          severity: 3,
          timing: 'hours_24_48',
          hours_after_end: 30.2,
        },
      ],
    }
    mount()
    expect(
      await screen.findByText(
        'posterior tibial tendon · Left · severity 3/10 · 24–48 hours after · 30 h after the run',
      ),
    ).toBeInTheDocument()
  })
  it('shows readable error for missing activity', async () => {
    status = 404
    mount()
    await waitFor(() => expect(screen.getByText('Could not load this view')).toBeInTheDocument())
    expect(screen.getByText('Activity not found')).toBeInTheDocument()
  })
  it('preserves imported prescription notes without claiming structured comparison', async () => {
    fixture = {
      ...base,
      planned: {
        ...base.planned!,
        legacy_unstructured: true,
        notes: 'Warm up gently, then run conversationally. Stop early if symptoms rise.',
        structure: null,
      },
      intervals: null,
    }
    mount()
    expect(
      await screen.findByText(
        'Warm up gently, then run conversationally. Stop early if symptoms rise.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('Structured comparison unavailable')).toBeInTheDocument()
  })

  it('collapses laps, intensity and data quality by default', async () => {
    mount()
    await screen.findByRole('heading', { name: 'Run · Sunday, November 8' })

    for (const [testId, label] of [
      ['activity-laps', 'Laps'],
      ['activity-intensity', 'Intensity time'],
      ['activity-data-quality', 'Data quality'],
    ]) {
      const disclosure = screen.getByTestId(testId)
      expect(disclosure.tagName).toBe('DETAILS')
      expect(disclosure).not.toHaveAttribute('open')
      expect(within(disclosure).getByText(label, { selector: 'summary' })).toBeInTheDocument()
    }

    expect(screen.getByRole('heading', { name: 'Session RPE' }).tagName).toBe('H2')
  })
})

describe('aerobic efficiency', () => {
  const value = {
    activity_id: 'a1',
    local_date: '2026-11-08',
    session_class: 'easy',
    sport: 'running',
    ef_m_per_beat: 1.171,
    mean_speed_mps: 2.8,
    mean_hr_bpm: 143.5,
    analysis_s: 3000,
    moving_s: 3000,
    paired_s: 3000,
    stopped_s: 0,
    coverage: 1,
    speed_cv_pct: 0,
    pauses_trimmed: 0,
    decoupling: {
      status: 'available' as const,
      reason_codes: [],
      pct: 4.76,
      first_ef_m_per_beat: 1.2,
      second_ef_m_per_beat: 1.14,
      first_mean_hr_bpm: 140,
      second_mean_hr_bpm: 147,
      first_mean_speed_mps: 2.8,
      second_mean_speed_mps: 2.8,
      half_s: 1500,
    },
    elevation: {
      status: 'available' as const,
      gain_m: 29.8,
      loss_m: 29,
      gain_m_per_km: 3.5,
      half_grade_diff_pct: 0,
    },
  }
  async function panel() {
    mount()
    const result = await screen.findByTestId('activity-aerobic')
    result.querySelector('summary')!.click()
    return within(result)
  }
  it('shows efficiency with pace, HR, terrain and drift', async () => {
    fixture = {
      ...base,
      aerobic: { ...metric('aerobic_efficiency', value), quality_flags: ['HILLY_ROUTE'] },
    }
    const view = await panel()
    expect(view.getByText('1.17 m per heartbeat · 9:35 /mi at 144 bpm')).toBeVisible()
    expect(view.getByText(/Heart-rate drift \+4.8%/)).toBeVisible()
    expect(
      view.getByText('Analysed 50:00 after the warm-up · data coverage 100% · climb 30 m'),
    ).toBeVisible()
    expect(view.getByText('Hilly route')).toBeVisible()
  })
  it('explains missing drift on a short run', async () => {
    fixture = {
      ...base,
      aerobic: metric('aerobic_efficiency', {
        ...value,
        decoupling: {
          ...value.decoupling,
          status: 'not_assessable',
          pct: null,
          reason_codes: ['DECOUPLING_TOO_SHORT'],
        },
      }),
    }
    expect(
      (await panel()).getByText(
        'Heart-rate drift: not assessed (Too short for a drift comparison)',
      ),
    ).toBeVisible()
  })
  it('explains structured workouts', async () => {
    fixture = {
      ...base,
      aerobic: {
        ...metric('aerobic_efficiency', value),
        value: null,
        status: 'not_applicable',
        reason_codes: ['STRUCTURED_SESSION'],
      },
    }
    expect((await panel()).getByText('Not assessed: Structured workout')).toBeVisible()
  })
  it('reports a missing result', async () => {
    expect((await panel()).getByText('Aerobic efficiency: missing')).toBeVisible()
  })
})
