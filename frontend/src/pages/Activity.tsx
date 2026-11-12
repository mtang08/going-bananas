import { useQuery } from '@tanstack/react-query'
import {
  MISSING, SIDE_LABELS, TIMING_LABELS, api, dateLabel, distance, flattenStructure,
  fmtClock, fmtDistance, fmtPaceFromSpeed, fmtPercent, fmtRpe, formatStep,
  pageHref, qk, sessionTitle, statusText,
} from '../api'
import type {
  ActivityExecution, CheckinRequest, SessionKind, Unit, WatchStep, ZoneDistribution,
} from '../api'
import { QueryState } from '../components/QueryState'

const FIT = {
  not_fetched: 'not fetched yet', fetched: 'fetched, not decoded',
  decoded: 'decoded', unavailable: 'unavailable', decode_error: 'decode error',
} as const
const OVERALL: Record<string, string> = {
  completed_as_planned: 'Completed as planned', completed_modified: 'Completed, modified',
  partial: 'Partial', moved: 'Moved', skipped: 'Skipped', extra: 'Extra',
  unknown: 'Unknown', ambiguous: 'Needs matching',
}
const NAME: Record<string, string> = {
  duration_ratio: 'Duration vs plan', distance_ratio: 'Distance vs plan',
  step_completion_ratio: 'Steps completed', target_coverage: 'Time in target',
}

function watchStepText(step: WatchStep, unit: Unit): string {
  const label = step.step_name ?? (step.intensity
    ? step.intensity[0].toUpperCase() + step.intensity.slice(1) : 'Step')
  const amount = step.repeat_from !== null
    ? `Repeat from step ${step.repeat_from + 1} × ${step.repeat_count}`
    : step.duration_type === 'time' ? fmtClock(step.duration_value)
      : step.duration_type === 'distance' ? `${step.duration_value ?? MISSING} m`
        : step.duration_type
  const target = step.target_type === 'speed'
    ? ` · ${fmtPaceFromSpeed(step.target_high, unit)}–${fmtPaceFromSpeed(step.target_low, unit)}`
    : step.target_type === 'heart_rate' ? ` · ${step.target_low ?? MISSING}–${step.target_high ?? MISSING} bpm` : ''
  return `${label} · ${amount}${target}`
}

function plannedSteps(structure: NonNullable<ActivityExecution['planned']>['structure'], unit: Unit) {
  if (structure === null) return []
  return flattenStructure(structure).map(step => ({
    key: `${step.step_path}:${step.repeat_index ?? 'single'}`,
    text: formatStep(step, unit),
  }))
}

function intensityText(zone: ZoneDistribution, label: string): string {
  if (zone.status === 'available' || zone.status === 'partial') {
    return `${label}: Easy ${fmtClock(zone.easy_s)} · Moderate ${fmtClock(zone.moderate_s)} · High ${fmtClock(zone.high_s)} · Unknown ${fmtClock(zone.unknown_s)} · Coverage ${fmtPercent(zone.coverage)}`
  }
  return `${label}: ${statusText(zone.status)}${zone.reason_codes.includes('ANCHOR_MISSING')
    ? ' — add aerobic-upper and threshold-lower anchors in Settings.' : ''}`
}

function plannedTitle(planned: NonNullable<ActivityExecution['planned']>): string {
  if (planned.legacy_unstructured && planned.kind === 'run') return 'Imported run'
  const kinds: SessionKind[] = ['run', 'strength', 'cross', 'rest', 'mobility']
  return kinds.includes(planned.kind as SessionKind)
    ? sessionTitle({ ...planned, kind: planned.kind as SessionKind }) : statusText(planned.kind)
}

export function Activity({ activityId, unit, onCheckin }: {
  activityId: string; unit: Unit; onCheckin: (req: CheckinRequest) => void;
}) {
  const execution = useQuery({
    queryKey: qk.activityExecution(activityId),
    queryFn: () => api<ActivityExecution>(`/activities/${encodeURIComponent(activityId)}/execution`),
  })
  const data = execution.data?.data
  const { activity, planned, completion, laps, watch_steps, planned_actual, intervals, intensity, rpe, symptoms } =
    data ?? {} as ActivityExecution
  const flags = data ? Array.from(new Set([
    ...planned_actual?.quality_flags ?? [], ...intervals?.quality_flags ?? [], ...intensity?.quality_flags ?? [],
  ])).sort() : []
  const repsVisible = planned?.structure?.some(item => item.type === 'work' ||
    item.type === 'repeat' && item.steps.some(step => step.type === 'work')) || intervals !== null
  return <section className="page-content">
    <QueryState loading={execution.isPending} error={execution.error}
      stale={Boolean(data)} retry={() => void execution.refetch()}>
      {data && <>
        <div className="page-heading"><div><div className="eyebrow">ACTIVITY</div>
          <h1>{activity.sport === 'running' ? 'Run' : activity.sport.replaceAll('_', ' ')} · {dateLabel(activity.local_date, {
            weekday: 'long', month: 'long', day: 'numeric',
          })}</h1></div><a href={pageHref.home}>Back to Home</a></div>
        {activity.fit_status !== 'decoded' && <div className="notice muted">
          No decoded FIT file for this run ({FIT[activity.fit_status]}). Laps, reps, and intensity are not assessable; summary metrics are shown.
        </div>}
        <div className="detail-stats">
          <div><small>Distance</small><strong>{fmtDistance(activity.distance_m, unit)}</strong></div>
          <div><small>Timer time</small><strong>{fmtClock(activity.timer_s)}</strong></div>
          <div><small>Elapsed</small><strong>{fmtClock(activity.elapsed_s)}</strong></div>
          <div><small>Average pace</small><strong>{activity.timer_s && activity.distance_m
            ? fmtPaceFromSpeed(activity.distance_m / activity.timer_s, unit) : MISSING}</strong></div>
          <div><small>RPE</small><strong>{fmtRpe(rpe.effective)}</strong></div>
        </div>
        <div className="panel"><h2>Planned vs actual</h2>
          {planned === null ? <p>{completion?.status === 'extra'
            ? 'Extra run — not in the plan.' : 'No planned session is linked to this run.'}</p>
            : <><strong>{plannedTitle(planned)}</strong>
              <p>{planned.intent}</p>
              {planned.notes && <p>{planned.notes}</p>}
              {planned.legacy_unstructured && <p>Structured comparison unavailable</p>}
              {planned_actual === null ? <p>Planned vs actual: missing</p>
                : planned_actual.value === null
                  ? <p>Planned vs actual: {statusText(planned_actual.status)}
                    {planned_actual.reason_codes.length ? ` (${planned_actual.reason_codes.join(', ')})` : ''}</p>
                  : <><span className="status-chip">{OVERALL[planned_actual.value.overall_status] ?? statusText(planned_actual.value.overall_status)}</span>
                    <table aria-label="Planned vs actual"><thead><tr><th>Component</th><th>Value</th><th>Status</th></tr></thead>
                      <tbody>{planned_actual.value.components.map(component => <tr key={component.name}>
                        <td>{NAME[component.name]}</td><td>{fmtPercent(component.value)}</td>
                        <td>{statusText(component.status)}</td>
                      </tr>)}</tbody></table></>}
            </>}
        </div>
        {repsVisible && <div className="panel"><h2>Reps</h2>
          {intervals === null ? <p>Rep analysis: missing</p>
            : intervals.status === 'not_assessable' && intervals.reason_codes.includes('WATCH_WORKOUT_MISMATCH')
              ? <><div className="notice warning">The watch workout does not match the planned structure, so reps are not assessable.</div>
                <div className="grid halves"><div><h3>Planned steps</h3><ul>
                  {plannedSteps(planned?.structure ?? null, unit).map(step => <li key={step.key}>{step.text}</li>)}
                </ul></div><div><h3>Watch steps</h3><ul>{watch_steps.map(step =>
                  <li key={step.message_index}>{watchStepText(step, unit)}</li>)}</ul></div></div></>
              : intervals.value === null ? <p>Reps are {statusText(intervals.status)}: {intervals.reason_codes.join(', ')}</p>
                : <><table aria-label="Reps"><thead><tr>
                  <th>Rep</th><th>Planned</th><th>Actual time</th><th>Actual distance</th>
                  <th>Pace</th><th>Target</th><th>In target</th><th>HR</th>
                </tr></thead><tbody>{intervals.value.reps.map(rep => <tr key={rep.rep}>
                  <td>{rep.rep}</td><td>{rep.planned_duration_type === 'time'
                    ? fmtClock(rep.planned_value) : `${rep.planned_value} m`}</td>
                  <td>{fmtClock(rep.actual_timer_s)}</td>
                  <td>{rep.actual_distance_m == null ? MISSING : `${Math.round(rep.actual_distance_m)} m`}</td>
                  <td>{fmtPaceFromSpeed(rep.mean_speed_mps, unit)}</td>
                  <td>{rep.target_modality === 'speed'
                    ? `${fmtPaceFromSpeed(rep.target_high, unit)}–${fmtPaceFromSpeed(rep.target_low, unit)}`
                    : rep.target_modality === 'hr'
                      ? `${rep.target_low ?? MISSING}–${rep.target_high ?? MISSING} bpm` : 'effort'}</td>
                  <td>{rep.in_target === null ? 'not assessable' : rep.in_target ? 'Yes' : 'No'}</td>
                  <td>{rep.hr_median_bpm == null ? MISSING : `${Math.round(rep.hr_median_bpm)} bpm`}</td>
                </tr>)}</tbody></table>
                  <p className="fineprint">Completed work {fmtClock(intervals.value.completed_work_s)} · Planned work {fmtClock(intervals.value.planned_work_s)} · Pace variation (CV) {intervals.value.cv_speed == null ? MISSING : `${intervals.value.cv_speed.toFixed(1)}%`} · Last vs first rep {intervals.value.last_first_change_pct == null ? MISSING : `${intervals.value.last_first_change_pct > 0 ? '+' : ''}${intervals.value.last_first_change_pct.toFixed(1)}%`} · Time in target {fmtPercent(intervals.value.target_coverage)}</p>
                </>}
        </div>}
        <div className="panel"><h2>Laps</h2>
          {activity.fit_status !== 'decoded' ? <p>Laps are not assessable without a decoded FIT file.</p>
            : laps.length === 0 ? <p>No laps recorded.</p>
              : <table aria-label="Laps"><thead><tr><th>Lap</th><th>Time</th><th>Distance</th>
                <th>Pace</th><th>Avg HR</th><th>Max HR</th><th>Watch step</th></tr></thead>
                <tbody>{laps.map(lap => <tr key={lap.lap_index}><td>{lap.lap_index + 1}</td>
                  <td>{fmtClock(lap.timer_s)}</td><td>{lap.distance_m == null ? MISSING : distance(lap.distance_m, unit, 2)}</td>
                  <td>{fmtPaceFromSpeed(lap.avg_speed_mps, unit)}</td>
                  <td>{lap.avg_hr_bpm == null ? MISSING : `${Math.round(lap.avg_hr_bpm)} bpm`}</td>
                  <td>{lap.max_hr_bpm == null ? MISSING : `${Math.round(lap.max_hr_bpm)} bpm`}</td>
                  <td>{lap.wkt_step_index == null ? MISSING : lap.wkt_step_index + 1}</td>
                </tr>)}</tbody></table>}
        </div>
        <div className="panel"><h2>Intensity time</h2>
          {intensity === null ? <p>Intensity: missing</p> : intensity.value === null
            ? <p>Intensity: {statusText(intensity.status)}</p>
            : <><p>{intensityText(intensity.value.hr, 'Heart rate')}</p>
              <p>{intensityText(intensity.value.speed, 'Pace')}</p></>}
        </div>
        <div className="panel"><h2>Session RPE</h2>
          <p>{rpe.effective === null ? 'RPE: missing' :
            `${fmtRpe(rpe.effective)} · ${rpe.source === 'manual' ? 'entered in app' : 'from Garmin'}`}</p>
          {rpe.manual !== null && rpe.garmin_fit !== null &&
            <small>Garmin recorded {fmtRpe(rpe.garmin_fit)}; your entry is used.</small>}
          <p>Session load {rpe.srpe_load_au == null ? MISSING : `${Math.round(rpe.srpe_load_au)} AU`}</p>
          <button className="button" onClick={() => onCheckin({
            kind: 'post_run', prompt: null, activityId,
          })}>{rpe.effective === null ? 'Enter RPE' : 'Change RPE'}</button>
        </div>
        <div className="panel"><h2>Symptoms after this run</h2>
          {symptoms.length === 0 ? <p>No symptom reports are linked to this run.</p>
            : <ul>{symptoms.map((symptom, index) => <li key={`${symptom.checkin_id}:${symptom.site}:${symptom.side}:${symptom.timing}:${index}`}>
              {symptom.site} · {SIDE_LABELS[symptom.side]} · severity {symptom.severity}/10 · {TIMING_LABELS[symptom.timing]}
              {symptom.hours_after_end !== null && ` · ${Math.round(symptom.hours_after_end)} h after the run`}
            </li>)}</ul>}
        </div>
        <div className="panel"><h2>Data quality</h2>
          {flags.length ? <ul>{flags.map(flag => <li key={flag}><code>{flag}</code></li>)}</ul>
            : <p>No data-quality flags.</p>}
        </div>
      </>}
    </QueryState>
  </section>
}
