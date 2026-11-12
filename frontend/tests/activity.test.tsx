import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Activity } from '../src/pages/Activity'
import type {
  ActivityExecution, IntensityValue, IntervalValue, MetricResult, PlannedActualValue, ZoneDistribution,
} from '../src/api'

const metric = <V,>(metric_id: string, value: V | null, status: MetricResult<V>['status'] = 'available',
  reason_codes: string[] = []): MetricResult<V> => ({
  id: metric_id, metric_id, method_version: 'v1', subject_type: 'activity', subject_key: 'a1',
  window_start: null, window_end: null, window_label: null, status, quality_status: 'good',
  value, unit: null, reason_codes, quality_flags: [], anchor_keys: [], calculated_at: '2026-11-08T13:00:00Z',
  source_refs: {}, config_hash: '0'.repeat(64), anchor_set_hash: null, dependency_hash: '1'.repeat(64),
  timezone: 'America/New_York', is_current: true,
})
const zone: ZoneDistribution = {
  status: 'not_assessable', reason_codes: ['ANCHOR_MISSING'], easy_s: null, moderate_s: null,
  high_s: null, valid_s: null, fraction_valid: null, fraction_timer: null, unclassified_s: null,
  unknown_s: null, eligible_timer_s: null, coverage: null, confidence: null,
}
const structure: NonNullable<NonNullable<ActivityExecution['planned']>['structure']> = [
  { type: 'warmup', duration_type: 'time', duration_value: 600,
    target: { modality: 'effort', low: null, high: null, effort_cue: 'easy' } },
  { type: 'repeat', count: 4, steps: [
    { type: 'work', duration_type: 'distance', duration_value: 800,
      target: { modality: 'speed', low: 3.8, high: 4, effort_cue: null } },
    { type: 'recovery', duration_type: 'time', duration_value: 120,
      target: { modality: 'effort', low: null, high: null, effort_cue: 'easy jog' } },
  ] },
  { type: 'cooldown', duration_type: 'time', duration_value: 600,
    target: { modality: 'effort', low: null, high: null, effort_cue: 'easy' } },
]
const reps: IntervalValue['reps'] = [205, 208, 210, 214].map((time, index) => ({
  rep: index + 1, planned_step: 2 + 2 * index, step_path: '1.steps.0', repeat_index: index,
  lap_index: 1 + 2 * index, observed: true, fully_completed: true, status: 'available',
  reason_codes: [], planned_duration_type: 'distance', planned_value: 800,
  actual_timer_s: time, actual_distance_m: 800, completion_ratio: 1,
  mean_speed_mps: 800 / time, speed_status: 'available', speed_reason_codes: [],
  speed_coverage: 1, target_modality: 'speed', target_low: 3.8, target_high: 4,
  target_valid_s: time, target_in_range_s: index === 3 ? 0 : time,
  in_target: index !== 3, hr_median_bpm: null, flags: [],
}))
const base: ActivityExecution = {
  activity: {
    id: 'a1', local_date: '2026-11-08', sport: 'running', distance_m: 6900, timer_s: 2517,
    elapsed_s: 2600, fit_status: 'decoded', start_at: '2026-11-08T12:00:00Z',
    end_at: '2026-11-08T12:43:20Z',
  },
  planned: {
    session_uid: 's1', local_date: '2026-11-08', kind: 'run', recipe_id: null, custom: true,
    intent: '4 × 800 m', planned_duration_s: null, planned_distance_m: null,
    structure, legacy_unstructured: false, legacy_payload: null, placeholder: false, locked: false,
  },
  completion: {
    id: 'c1', input_version: 1, session_uid: 's1', activity_id: 'a1', strong_workout_id: null,
    manual_session_id: null, status: 'completed_as_planned', match_method: 'explicit',
    modification_reason: null, reason_note: null, version: 1, updated_at: '2026-11-08T13:00:00Z',
    local_date: '2026-11-08',
  },
  laps: Array.from({ length: 10 }, (_, i) => ({
    lap_index: i, start_at: '2026-11-08T12:00:00Z', timer_s: i % 2 ? 205 : 300,
    elapsed_s: i % 2 ? 205 : 300, distance_m: i % 2 ? 800 : 1000,
    avg_speed_mps: i % 2 ? 800 / 205 : 3, avg_hr_bpm: null, max_hr_bpm: null,
    lap_trigger: null, wkt_step_index: i,
  })),
  watch_steps: [
    { message_index: 0, step_name: 'Warmup', intensity: 'warmup', duration_type: 'time', duration_value: 600,
      target_type: null, target_low: null, target_high: null, repeat_from: null, repeat_count: null },
    { message_index: 1, step_name: null, intensity: 'interval', duration_type: 'distance', duration_value: 800,
      target_type: null, target_low: null, target_high: null, repeat_from: null, repeat_count: null },
    { message_index: 2, step_name: null, intensity: 'recovery', duration_type: 'time', duration_value: 120,
      target_type: null, target_low: null, target_high: null, repeat_from: null, repeat_count: null },
    { message_index: 3, step_name: null, intensity: null, duration_type: 'repeat_until_steps_cmplt', duration_value: null,
      target_type: null, target_low: null, target_high: null, repeat_from: 1, repeat_count: 4 },
    { message_index: 4, step_name: 'Cooldown', intensity: 'cooldown', duration_type: 'time', duration_value: 600,
      target_type: null, target_low: null, target_high: null, repeat_from: null, repeat_count: null },
  ],
  planned_actual: metric<PlannedActualValue>('planned_actual_session', {
    overall_status: 'completed_as_planned', certainty: 'committed', kind: 'run',
    candidate_activity_ids: [], calendar_version: 2, match_method: 'explicit',
    components: [{ name: 'duration_ratio', value: .98, status: 'met' }],
  }),
  intervals: metric<IntervalValue>('work_interval_execution', {
    reps, n_planned: 4, n_observed: 4, n_completed: 4, step_completion_ratio: 1,
    cv_speed: 1.8, last_first_change_pct: -4.2, completed_work_s: 837,
    planned_work_s: null, completed_work_m: 3200, planned_work_m: 3200,
    target_coverage: .75,
  }),
  intensity: metric<IntensityValue>('time_in_intensity', { hr: zone, speed: zone }),
  rpe: { effective: 7, source: 'garmin_fit', manual: null, garmin_fit: 7, srpe_load_au: 293.6 },
  symptoms: [],
}
let fixture = base
let status = 200
let requests: { url: string; method: string }[] = []
const onCheckin = vi.fn()
beforeEach(() => {
  fixture = base
  status = 200
  requests = []
  onCheckin.mockClear()
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    requests.push({ url: String(input), method: init?.method ?? 'GET' })
    return status === 404
      ? new Response(JSON.stringify({ error: { code: 'not_found', message: 'Activity not found' } }), { status })
      : new Response(JSON.stringify({ schema_version: 'v1', data_revision: 2, mode: 'demo', data: fixture }), { status })
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><Activity activityId="a1" unit="mi" onCheckin={onCheckin}/></QueryClientProvider>)
}

describe('Activity execution', () => {
  it('renders structured reps, summary, plans, intensity, RPE and missing HR', async () => {
    mount()
    expect(await screen.findByRole('heading', { name: 'Run · Sunday, November 8' })).toBeInTheDocument()
    expect(screen.getByText('41:57')).toBeInTheDocument()
    expect(screen.getByText('9:47 /mi')).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Reps' })
    const bodyRows = within(table).getAllByRole('row').slice(1)
    expect(bodyRows).toHaveLength(4)
    expect(within(bodyRows[0]).getByText('6:52 /mi')).toBeInTheDocument()
    expect(within(bodyRows[3]).getByText('7:10 /mi')).toBeInTheDocument()
    expect(within(bodyRows[3]).getByText('No')).toBeInTheDocument()
    expect(screen.getByText('Completed work 13:57 · Planned work missing · Pace variation (CV) 1.8% · Last vs first rep -4.2% · Time in target 75%')).toBeInTheDocument()
    expect(screen.getByText('7/10 · from Garmin')).toBeInTheDocument()
    expect(screen.getByText('Session load 294 AU')).toBeInTheDocument()
    expect(screen.getByText('Completed as planned')).toBeInTheDocument()
    expect(screen.getByText('Duration vs plan')).toBeInTheDocument()
    expect(screen.getByText('98%')).toBeInTheDocument()
    expect(screen.getByText('Heart rate: not assessable — add aerobic-upper and threshold-lower anchors in Settings.')).toBeInTheDocument()
    expect(screen.getByText('No symptom reports are linked to this run.')).toBeInTheDocument()
    expect(requests).toEqual([{ url: '/api/v1/activities/a1/execution', method: 'GET' }])
  })
  it('shows watch and planned steps when structure mismatches', async () => {
    fixture = { ...base, intervals: metric<IntervalValue>('work_interval_execution', null, 'not_assessable', ['WATCH_WORKOUT_MISMATCH']) }
    mount()
    expect(await screen.findByText('The watch workout does not match the planned structure, so reps are not assessable.')).toBeInTheDocument()
    expect(screen.getByText('Planned steps')).toBeInTheDocument()
    expect(screen.getByText('Watch steps')).toBeInTheDocument()
    const planned = screen.getByText('Planned steps').parentElement!
    const labels = within(planned).getAllByRole('listitem').map(item => item.textContent)
    expect(labels).toHaveLength(10)
    expect(labels.slice(1, 5)).toEqual([
      'Work 800 m · 6:42 /mi–7:04 /mi', 'Recovery 2:00 · easy jog',
      'Work 800 m · 6:42 /mi–7:04 /mi', 'Recovery 2:00 · easy jog',
    ])
    expect(screen.getByText('Interval · 800 m')).toBeInTheDocument()
    expect(screen.queryByRole('table', { name: 'Reps' })).not.toBeInTheDocument()
  })
  it('makes missing FIT evidence explicit while retaining summary', async () => {
    fixture = { ...base, activity: { ...base.activity, fit_status: 'not_fetched' },
      laps: [], watch_steps: [], intervals: null, intensity: null }
    mount()
    expect(await screen.findByText('No decoded FIT file for this run (not fetched yet). Laps, reps, and intensity are not assessable; summary metrics are shown.')).toBeInTheDocument()
    expect(screen.getByText('Laps are not assessable without a decoded FIT file.')).toBeInTheDocument()
    expect(screen.getByText('Rep analysis: missing')).toBeInTheDocument()
    expect(screen.getByText('Intensity: missing')).toBeInTheDocument()
  })
  it('shows an extra run without fabricated planned reps', async () => {
    fixture = { ...base, planned: null, completion: { ...base.completion!, status: 'extra' }, intervals: null }
    mount()
    expect(await screen.findByText('Extra run — not in the plan.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Reps' })).not.toBeInTheDocument()
  })
  it('routes missing RPE entry through check-in', async () => {
    fixture = { ...base, rpe: { effective: null, source: null, manual: null, garmin_fit: null, srpe_load_au: null } }
    mount()
    expect(await screen.findByText('RPE: missing')).toBeInTheDocument()
    expect(screen.getByText('Session load missing')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Enter RPE' }))
    expect(onCheckin).toHaveBeenCalledWith({ kind: 'post_run', prompt: null, activityId: 'a1' })
  })
  it('renders symptom timing and provenance text', async () => {
    fixture = { ...base, symptoms: [{
      checkin_id: 'ch1', observed_at: '2026-11-09T12:00:00Z', kind: 'delayed_followup',
      site: 'posterior tibial tendon', side: 'left', severity: 3, timing: 'hours_24_48',
      hours_after_end: 30.2,
    }] }
    mount()
    expect(await screen.findByText('posterior tibial tendon · Left · severity 3/10 · 24–48 hours after · 30 h after the run')).toBeInTheDocument()
  })
  it('shows readable error for missing activity', async () => {
    status = 404
    mount()
    await waitFor(() => expect(screen.getByText('Could not load this view')).toBeInTheDocument())
    expect(screen.getByText('Activity not found')).toBeInTheDocument()
  })
  it('preserves imported prescription notes without claiming structured comparison', async () => {
    fixture = { ...base, planned: { ...base.planned!, legacy_unstructured: true,
      notes: 'Warm up gently, then run conversationally. Stop early if symptoms rise.', structure: null }, intervals: null }
    mount()
    expect(await screen.findByText('Warm up gently, then run conversationally. Stop early if symptoms rise.')).toBeInTheDocument()
    expect(screen.getByText('Structured comparison unavailable')).toBeInTheDocument()
  })

})
