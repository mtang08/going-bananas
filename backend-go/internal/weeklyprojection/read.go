// Package weeklyprojection estimates running distance in the athlete's current local week.
package weeklyprojection

import (
	"context"
	"encoding/json"
	"math"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"
)

type Projection struct {
	WeekStart                string   `json:"week_start"`
	WeekEnd                  string   `json:"week_end"`
	Today                    string   `json:"today"`
	Timezone                 string   `json:"timezone"`
	CalendarVersion          int      `json:"calendar_version"`
	ActualDistance           float64  `json:"actual_distance_m"`
	RemainingDistance        float64  `json:"remaining_distance_m"`
	ProjectedDistance        float64  `json:"projected_distance_m"`
	ActualRuns               int      `json:"actual_runs"`
	RemainingRuns            int      `json:"remaining_runs"`
	EstimatedRuns            int      `json:"estimated_runs"`
	MissingActualRuns        int      `json:"missing_actual_runs"`
	MissingPlannedRuns       int      `json:"missing_planned_runs"`
	UnrecordedPastRuns       int      `json:"unrecorded_past_runs"`
	PaceSampleCount          int      `json:"pace_sample_count"`
	Pace                     *float64 `json:"pace_mps"`
	PlanAvailable            bool     `json:"plan_available"`
	PlanThrough              *string  `json:"plan_through"`
	ActivityCoverageComplete bool     `json:"activity_coverage_complete"`
}

func Load(ctx context.Context, tx pgx.Tx, now time.Time) (Projection, error) {
	var p Projection
	if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock_shared(71382413)"); err != nil {
		return Projection{}, err
	}
	err := tx.QueryRow(ctx, `SELECT COALESCE((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York'),
		COALESCE((SELECT calendar_head_version FROM app_state WHERE id=1),0)`).Scan(&p.Timezone, &p.CalendarVersion)
	if err != nil {
		return Projection{}, err
	}
	zone, err := time.LoadLocation(p.Timezone)
	if err != nil {
		return Projection{}, err
	}
	local := now.In(zone)
	p.Today = local.Format(time.DateOnly)
	start := local.AddDate(0, 0, -(int(local.Weekday())+6)%7)
	p.WeekStart = start.Format(time.DateOnly)
	p.WeekEnd = start.AddDate(0, 0, 6).Format(time.DateOnly)
	p.PlanAvailable = p.CalendarVersion > 0
	if err := p.readRuns(ctx, tx); err != nil {
		return Projection{}, err
	}
	var manual int
	if err := tx.QueryRow(ctx, `SELECT count(*) FROM manual_sessions WHERE kind='run' AND date BETWEEN $1::date AND $2::date AND linked_activity_id IS NULL`, p.WeekStart, p.Today).Scan(&manual); err != nil {
		return Projection{}, err
	}
	p.ActualRuns += manual
	p.MissingActualRuns += manual
	if err := tx.QueryRow(ctx, `SELECT NOT EXISTS (
		SELECT FROM generate_series(0,$2::date-$1::date) i
		WHERE NOT EXISTS (SELECT FROM coverage_intervals WHERE dataset='activities' AND status='complete'
			AND fully_enumerated AND $1::date+i BETWEEN start_date AND end_date))`, p.WeekStart, p.Today).Scan(&p.ActivityCoverageComplete); err != nil {
		return Projection{}, err
	}
	var planned []plannedRun
	if err := tx.QueryRow(ctx, planSQL, p.CalendarVersion, p.WeekStart, p.WeekEnd).Scan(&p.PlanThrough, &planned); err != nil {
		return Projection{}, err
	}
	for _, run := range planned {
		p.addPlan(run)
	}
	p.ProjectedDistance = p.ActualDistance + p.RemainingDistance
	return p, nil
}

func (p *Projection) readRuns(ctx context.Context, tx pgx.Tx) error {
	rows, err := tx.Query(ctx, `SELECT (a.start_at AT TIME ZONE $2)::date::text,a.distance_m,a.timer_s
		FROM activities a LEFT JOIN LATERAL (SELECT excluded FROM activity_annotations WHERE activity_id=a.id
			ORDER BY version DESC LIMIT 1) ann ON true
		WHERE sport IN ('running','trail_running','treadmill_running') AND resolution_state='resolved' AND ann.excluded IS NOT TRUE
			AND (a.start_at AT TIME ZONE $2)::date BETWEEN $1::date-27 AND $1::date
		ORDER BY start_at,id`, p.Today, p.Timezone)
	if err != nil {
		return err
	}
	defer rows.Close()
	var speeds []float64
	for rows.Next() {
		var day string
		var distance, timer *float64
		if err := rows.Scan(&day, &distance, &timer); err != nil {
			return err
		}
		if positive(distance) && positive(timer) {
			speeds = append(speeds, *distance / *timer)
		}
		if day < p.WeekStart {
			continue
		}
		p.ActualRuns++
		if distance == nil || *distance < 0 || math.IsNaN(*distance) || math.IsInf(*distance, 0) {
			p.MissingActualRuns++
			continue
		}
		p.ActualDistance += *distance
	}
	if err := rows.Err(); err != nil {
		return err
	}
	p.PaceSampleCount = len(speeds)
	if len(speeds) > 0 {
		slices.Sort(speeds)
		n := len(speeds) / 2
		median := speeds[n]
		if len(speeds)%2 == 0 {
			median = (median + speeds[n-1]) / 2
		}
		p.Pace = &median
	}
	return nil
}

type plannedRun struct {
	Day                string
	Status             string
	Recorded           bool
	Distance, Duration *float64
	Structure          json.RawMessage
}

const planSQL = `WITH newest AS (
	SELECT DISTINCT ON(session_uid) * FROM calendar_session_revisions WHERE calendar_version_number <= $1
	ORDER BY session_uid, calendar_version_number DESC, revision DESC
)
SELECT max(n.local_date)::text,coalesce(jsonb_agg(jsonb_build_object(
	'day', n.local_date, 'status', coalesce(c.status,''), 'recorded', num_nonnulls(c.activity_id,c.manual_session_id,c.strong_workout_id)>0,
	'distance',n.planned_distance_m,'duration',n.planned_duration_s,'structure',n.structure)
	ORDER BY n.local_date,n.slot,n.session_uid) FILTER(WHERE n.kind='run' AND n.local_date BETWEEN $2::date AND $3::date),'[]')
FROM newest n LEFT JOIN session_completions c USING(session_uid) WHERE NOT n.deleted`

func (p *Projection) addPlan(run plannedRun) {
	switch run.Status {
	case "skipped", "completed_as_planned", "completed_modified", "partial", "moved", "extra":
		return
	case "unknown":
		if run.Recorded {
			return
		}
		if run.Day < p.Today {
			p.UnrecordedPastRuns++
		} else {
			p.MissingPlannedRuns++
		}
		return
	}
	if run.Day < p.Today {
		p.UnrecordedPastRuns++
		return
	}
	p.RemainingRuns++
	distance, estimated := PlannedDistance(run.Distance, run.Duration, run.Structure, p.Pace)
	if distance == nil {
		p.MissingPlannedRuns++
		return
	}
	p.RemainingDistance += *distance
	if estimated {
		p.EstimatedRuns++
	}
}
