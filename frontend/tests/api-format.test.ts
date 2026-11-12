import { afterEach, describe, expect, it, vi } from 'vitest'
import fixture from './fixtures/planning-wire.json'
import { ANCHOR_UNIT, MISSING, clockToSeconds, fetchDailyGuidance, flattenStructure, fmtClock, fmtDistance, fmtDuration, fmtPaceFromSpeed, fmtPercent, fmtRpe, formatStep, paceToSpeed, pageHref, qk, sessionMarker, sessionTitle, statusText } from '../src/api'
import type { AnchorCreate, CalendarView, CompletionPut, DailyGuidance, GoalCreate, MetricResult, PlannedStep, Profile, SrpeValue, StrengthRoutineSlot, StructureItem, VolumeValue } from '../src/api'

const wire: Record<string, unknown> = fixture
const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value)
const calendarView = (value: unknown): value is CalendarView => record(value) && typeof value.head === 'number' && typeof value.version === 'number' && typeof value.today === 'string' && typeof value.timezone === 'string' && Array.isArray(value.sessions) && Array.isArray(value.completions) && (value.undo === null || record(value.undo) && Array.isArray(value.undo.protected_session_uids))
const guidance = (value: unknown): value is DailyGuidance => record(value) && typeof value.created_at === 'string' && typeof value.input_hash === 'string' && typeof value.decision === 'string' && Array.isArray(value.trigger_codes)
const profile = (value: unknown): value is Profile => record(value) && (value.planning_authority === 'legacy' || value.planning_authority === 'calendar') && typeof value.version === 'number' && Array.isArray(value.scheduled_strength_days) && Array.isArray(value.strength_week_a_days) && Array.isArray(value.strength_week_b_days)
const metric = <V>(value: unknown, valueCheck: (v: unknown) => v is V): value is MetricResult<V> => record(value) && typeof value.metric_id === 'string' && typeof value.status === 'string' && typeof value.dependency_hash === 'string' && Array.isArray(value.reason_codes) && valueCheck(value.value)
const volume = (value: unknown): value is VolumeValue => record(value) && typeof value.run_count === 'number' && typeof value.runs_missing_timer === 'number' && (value.timer_duration_s === null || typeof value.timer_duration_s === 'number') && (value.distance_m === null || typeof value.distance_m === 'number')
const srpe = (value: unknown): value is SrpeValue => record(value) && typeof value.sessions_total === 'number' && typeof value.sessions_without_load === 'number' && (value.load_au === null || typeof value.load_au === 'number')
const structure = (value: unknown): value is StructureItem[] => Array.isArray(value) && value.length > 0 && value.every(item => record(item) && typeof item.type === 'string')

describe('planning wire', () => {
  it('checks empty and populated calendar and rollback', () => {
    expect(calendarView(wire.empty_calendar)).toBe(true)
    expect(calendarView(wire.populated_calendar)).toBe(true)
    if (!calendarView(wire.empty_calendar) || !calendarView(wire.populated_calendar)) throw Error('fixture')
    expect(wire.empty_calendar.head).toBe(0)
    expect(wire.empty_calendar.undo).toBeNull()
    expect(wire.populated_calendar.undo?.protected_session_uids).toEqual(['session-a'])
    expect(wire.populated_calendar.sessions[0].legacy_unstructured).toBe(true)
    expect(wire.rollback_result).toMatchObject({ kind: 'rollback', preserved_session_uids: ['00000000-0000-0000-0000-000000000002'] })
  })
  it('checks guidance and profile projections', () => {
    expect(wire.guidance_null).toBeNull()
    expect(guidance(wire.guidance_full)).toBe(true)
    if (!guidance(wire.guidance_full)) throw Error('fixture')
    expect(wire.guidance_full.input_hash).toHaveLength(64)
    expect(profile(wire.profile_weekly)).toBe(true)
    expect(profile(wire.profile_alternating)).toBe(true)
    if (!profile(wire.profile_weekly) || !profile(wire.profile_alternating)) throw Error('fixture')
    expect(wire.profile_weekly.strength_schedule_mode).toBe('weekly')
    expect(wire.profile_alternating.strength_week_a_days).toEqual([1, 4])
    const writeFields = Object.fromEntries(Object.entries(wire.profile_weekly).filter(([key]) => key !== 'planning_authority' && key !== 'version'))
    expect({ expected_version: wire.profile_weekly.version, ...writeFields }).not.toHaveProperty('planning_authority')
  })
  it('keeps null unknown distinct from numeric zero', () => {
    expect(metric(wire.volume_all_missing, volume)).toBe(true)
    expect(metric(wire.volume_all_known, volume)).toBe(true)
    expect(metric(wire.srpe_all_missing, srpe)).toBe(true)
    expect(metric(wire.srpe_all_known, srpe)).toBe(true)
    expect(wire.metric_null).toBeNull()
    expect(metric(wire.metric_zero, volume)).toBe(true)
    if (!metric(wire.volume_all_missing, volume) || !metric(wire.metric_zero, volume)) throw Error('fixture')
    expect(wire.volume_all_missing.value?.timer_duration_s).toBeNull()
    expect(wire.metric_zero.value?.timer_duration_s).toBe(0)
  })
})

describe('planning helpers', () => {
  it('formats missing and zero separately', () => {
    expect(fmtPaceFromSpeed(800 / 205, 'mi')).toBe('6:52 /mi')
    expect(fmtPaceFromSpeed(0, 'km')).toBe(MISSING)
    expect(fmtPaceFromSpeed(null, 'km')).toBe(MISSING)
    expect(fmtDistance(null, 'mi')).toBe(MISSING)
    expect(fmtDistance(0, 'mi')).toBe('0.0 mi')
    expect(fmtClock(205)).toBe('3:25')
    expect(fmtClock(3725)).toBe('1:02:05')
    expect(fmtClock(0)).toBe('0:00')
    expect(fmtDuration(null)).toBe(MISSING)
    expect(fmtDuration(0)).toBe('0m')
    expect(fmtPercent(0.756)).toBe('76%')
    expect(fmtPercent(0)).toBe('0%')
    expect(fmtRpe(7)).toBe('7/10')
    expect(fmtRpe(6.5)).toBe('6.5/10')
    expect(statusText('not_assessable')).toBe('not assessable')
  })
  it('parses clock and pace strictly', () => {
    expect(clockToSeconds('6:52')).toBe(412)
    expect(clockToSeconds('1:02:05')).toBe(3725)
    expect(clockToSeconds('6:75')).toBeNull()
    expect(clockToSeconds('9007199254740991:00')).toBeNull()
    expect(paceToSpeed('8:00', 'mi')).toBeCloseTo(3.3528, 4)
  })
  it('expands repeats without mutation', () => {
    expect(structure(wire.structure)).toBe(true)
    if (!structure(wire.structure)) throw Error('fixture')
    const before = JSON.stringify(wire.structure)
    const expanded = flattenStructure(wire.structure)
    expect(expanded.map(step => [step.step_path, step.repeat_index, step.expanded_step])).toEqual([
      ['0', null, 1], ['1.steps.0', 0, 2], ['1.steps.1', 0, 3],
      ['1.steps.0', 1, 4], ['1.steps.1', 1, 5],
    ])
    expect(JSON.stringify(wire.structure)).toBe(before)
    expect(formatStep(expanded[0], 'mi')).toBe('Warm-up 10:00 · effort')
  })
  it('rejects malformed children and overlong expansions', () => {
    const good: PlannedStep = { type: 'work', duration_type: 'time', duration_value: 60, target: null }
    expect(() => flattenStructure([{ type: 'repeat', count: 101, steps: [good] }])).toThrow('invalid_structure')
    for (const child of [
      { ...good, type: 'repeat' }, { ...good, type: 'surprise' },
      { ...good, duration_value: 0 }, { ...good, target: { modality: 'speed', low: 4, high: 3, effort_cue: null } },
      { ...good, target: { modality: 'effort', low: null, high: null, effort_cue: '' } },
    ]) expect(() => flattenStructure([{ type: 'repeat', count: 2, steps: [child] }] as StructureItem[])).toThrow('invalid_structure')
    expect(() => flattenStructure([])).toThrow('invalid_structure')
  })
  it('formats target, titles, markers, and keys', () => {
    const step: PlannedStep = { type: 'work', duration_type: 'distance', duration_value: 800,
      target: { modality: 'speed', low: 3.8, high: 4, effort_cue: null } }
    expect(formatStep(step, 'mi')).toBe('Work 800 m · 6:42 /mi–7:04 /mi')
    expect(sessionTitle({ kind: 'run', recipe_id: null, custom: false })).toBe('Quality slot')
    expect(sessionTitle({ kind: 'run', recipe_id: 'REC002', custom: false })).toBe('Long run')
    if (!calendarView(wire.populated_calendar)) throw Error('fixture')
    const session = wire.populated_calendar.sessions[0]
    expect(sessionMarker(session, undefined, '2026-11-17')).toBe('not_recorded')
    expect(sessionMarker(session, undefined, '2026-11-16')).toBe('planned')
    expect(sessionMarker(session, { status: 'skipped' } as CalendarView['completions'][number], '2026-11-17')).toBe('missed')
    expect(sessionMarker(session, { status: 'completed_modified' } as CalendarView['completions'][number], '2026-11-17')).toBe('modified')
    expect(ANCHOR_UNIT.performance_3min).toBe('m')
    expect(ANCHOR_UNIT.performance_20_30min).toBe('mps')
    expect(qk.calendarView('head')).toEqual(['v2', 'calendar', 'view', 'head'])
    expect(qk.calendarDiff(2, 3)).toEqual(['v2', 'calendar', 'diff', 2, 3])
    expect(qk.metricsRecovery('a', 'b')).toEqual(['v2', 'metrics', 'recovery', 'a', 'b'])
    expect(qk.profile).toEqual(['profile'])
    expect(pageHref.activity('a/b')).toBe('#activity/a%2Fb')
  })
})

describe('daily guidance fetch', () => {
  afterEach(() => vi.unstubAllGlobals())
  it('returns successful null', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ schema_version: 'v1', data_revision: 0, mode: 'demo', data: null }), { status: 200 })))
    await expect(fetchDailyGuidance()).resolves.toBeNull()
    expect(fetch).toHaveBeenCalledWith('/api/v1/coach/v2/daily', expect.objectContaining({ credentials: 'same-origin' }))
  })
  it.each([404, 500])('keeps HTTP %i errors visible', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'unavailable', message: 'Failed' } }), { status })))
    await expect(fetchDailyGuidance()).rejects.toMatchObject({ status, code: 'unavailable' })
  })
})

// Compile-time producer DTO checks.
const goalCreate: GoalCreate = { text: 'Run well', horizon: 'season', priority: 1 }
const suggestedSlot: StrengthRoutineSlot = { id: null, label: 'Strength', default_weekday: 1, lower_body_cost: 'low', typical_duration_s: null, main_lower_body_lifts: [], active: true, version: 0 }
const anchorCreate: AnchorCreate = { kind: 'performance_3min', value_low: 900, unit: 'm', protocol: 'time_trial_3min', confidence: 'high', calibrated_at: '2026-11-16T10:00:00Z', valid_from: '2026-11-16' }
const completionPut: CompletionPut = { activity_id: 'activity-a' }
void [goalCreate, suggestedSlot, anchorCreate, completionPut]
// @ts-expect-error create requests cannot set status
const invalidGoal: GoalCreate = { text: 'Run well', horizon: 'season', priority: 1, status: 'active' }
// @ts-expect-error anchor creation requires valid_from
const invalidAnchor: AnchorCreate = { kind: 'performance_3min', value_low: 900, unit: 'm', protocol: 'time_trial_3min', confidence: 'high', calibrated_at: '2026-11-16T10:00:00Z' }
// @ts-expect-error completion match_method is derived by the server
const invalidCompletion: CompletionPut = { match_method: 'explicit' }
void [invalidGoal, invalidAnchor, invalidCompletion]
