import { Badge, Card } from './ui'
import { dateLabel, fmtDistance, type Unit } from '../api'
import './plan-overview.css'
import type { WeeklyProjection } from '../api/types/calendar'

export function WeeklyMileage({
  projection: p,
  unit,
}: {
  projection: WeeklyProjection
  unit: Unit
}) {
  const incomplete =
    p.missing_actual_runs > 0 ||
    p.missing_planned_runs > 0 ||
    p.unrecorded_past_runs > 0 ||
    !p.activity_coverage_complete ||
    !p.plan_available ||
    p.plan_through === null ||
    p.plan_through < p.week_end
  const gaps = [
    p.missing_actual_runs > 0 &&
      `${p.missing_actual_runs} recorded ${p.missing_actual_runs === 1 ? 'run has' : 'runs have'} no distance`,
    p.missing_planned_runs > 0 &&
      `${p.missing_planned_runs} remaining ${p.missing_planned_runs === 1 ? 'run has' : 'runs have'} no distance estimate`,
    p.unrecorded_past_runs > 0 &&
      `${p.unrecorded_past_runs} past planned ${p.unrecorded_past_runs === 1 ? 'run is' : 'runs are'} unrecorded`,
    !p.activity_coverage_complete && 'activity history may be incomplete',
    !p.plan_available
      ? 'no accepted plan is available'
      : p.plan_through === null || p.plan_through < p.week_end
        ? 'the accepted plan does not cover the full week'
        : false,
  ].filter(Boolean)
  return (
    <Card className="weekly-mileage" data-testid="weekly-mileage">
      <div className="panel-head">
        <div>
          <h2>Projected this week</h2>
          <p>
            {dateLabel(p.week_start)}–{dateLabel(p.week_end)} · Monday–Sunday
          </p>
        </div>
        <Badge className="unit-pill">{unit}</Badge>
      </div>
      <strong className="weekly-mileage-total">
        {p.estimated_runs > 0 ? '~' : ''}
        {fmtDistance(p.projected_distance_m, unit)}
      </strong>
      {incomplete && (
        <p className="weekly-mileage-status">Incomplete projection · accounted distance</p>
      )}
      <div
        className="mileage-track"
        role="img"
        aria-label={`Recorded ${fmtDistance(p.actual_distance_m, unit)}; remaining accepted plan ${fmtDistance(p.remaining_distance_m, unit)}${incomplete ? '; incomplete projection' : ''}`}
      >
        <span
          className="mileage-recorded"
          style={{
            width: `${p.projected_distance_m > 0 ? (p.actual_distance_m / p.projected_distance_m) * 100 : 0}%`,
          }}
        />
        <span
          className="mileage-remaining"
          style={{
            width: `${p.projected_distance_m > 0 ? (p.remaining_distance_m / p.projected_distance_m) * 100 : 0}%`,
          }}
        />
      </div>
      <div className="weekly-mileage-parts">
        <span>
          Recorded: {fmtDistance(p.actual_distance_m, unit)} · {p.actual_runs}{' '}
          {p.actual_runs === 1 ? 'run' : 'runs'}
        </span>
        <span>
          Remaining accepted plan: {fmtDistance(p.remaining_distance_m, unit)} · {p.remaining_runs}{' '}
          {p.remaining_runs === 1 ? 'run' : 'runs'}
        </span>
      </div>
      {p.estimated_runs > 0 && (
        <p className="muted-text weekly-mileage-note">
          Time-based runs estimated from workout targets or recent pace.
        </p>
      )}
      {gaps.length > 0 && (
        <p className="muted-text weekly-mileage-note">
          Some distance is unknown: {gaps.join('; ')}.
        </p>
      )}
    </Card>
  )
}
