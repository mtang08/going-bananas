package assessment

import (
	"context"
	"encoding/json"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/matching"
)

func candidates(ctx context.Context, tx pgx.Tx, uid uuid.UUID, day, zone string, head int) ([]Candidate, error) {
	center, err := time.Parse(time.DateOnly, day)
	if err != nil {
		return nil, err
	}
	days := []string{center.AddDate(0, 0, -1).Format(time.DateOnly), day, center.AddDate(0, 0, 1).Format(time.DateOnly)}
	input := matching.Input{Days: days}
	rows, err := tx.Query(ctx, `WITH latest AS (
		SELECT DISTINCT ON(session_uid) * FROM calendar_session_revisions WHERE calendar_version_number<=$1
		ORDER BY session_uid,calendar_version_number DESC,revision DESC)
		SELECT session_uid::text,local_date::text,kind,planned_duration_s,planned_distance_m,structure FROM latest
		WHERE NOT deleted AND local_date BETWEEN $2::text::date AND $3::text::date`, head, days[0], days[2])
	if err != nil {
		return nil, err
	}
	input.Planned, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (matching.Plan, error) {
		var p matching.Plan
		var raw []byte
		err := row.Scan(&p.SessionUID, &p.LocalDate, &p.Kind, &p.PlannedDurationS, &p.PlannedDistanceM, &raw)
		if err != nil {
			return p, err
		}
		var steps []Step
		work := false
		if json.Unmarshal(raw, &steps) == nil {
			expanded, _ := expand(steps)
			for _, s := range expanded {
				if s.Type == "work" {
					work = true
					break
				}
			}
		}
		p.HasWorkSteps = &work
		return p, nil
	})
	if err != nil {
		return nil, err
	}
	rows, err = tx.Query(ctx, `SELECT a.id::text,(a.start_at AT TIME ZONE $1)::date::text,'run',a.timer_s,a.distance_m,
		EXISTS(SELECT FROM activity_workout_steps w WHERE w.activity_id=a.id)
		FROM activities a LEFT JOIN LATERAL(SELECT excluded FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1) an ON true
		WHERE a.sport IN ('running','treadmill_running','trail_running') AND a.resolution_state='resolved' AND NOT coalesce(an.excluded,false)
		AND (a.start_at AT TIME ZONE $1)::date BETWEEN $2::text::date AND $3::text::date ORDER BY a.start_at,a.id`, zone, days[0], days[2])
	if err != nil {
		return nil, err
	}
	input.Runs, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (matching.Subject, error) {
		var s matching.Subject
		err := row.Scan(&s.SubjectKey, &s.LocalDate, &s.Kind, &s.TimerS, &s.DistanceM, &s.HasWorkoutSteps)
		return s, err
	})
	if err != nil {
		return nil, err
	}
	rows, err = tx.Query(ctx, `SELECT 'strong:'||id,local_date::text FROM strong_workouts WHERE resolution_state='resolved' AND local_date BETWEEN $1::text::date AND $2::text::date
		UNION ALL SELECT 'manual:'||id,date::text FROM manual_sessions WHERE kind='strength' AND linked_activity_id IS NULL AND date BETWEEN $1::text::date AND $2::text::date`, days[0], days[2])
	if err != nil {
		return nil, err
	}
	strength, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (matching.Subject, error) {
		s := matching.Subject{Kind: "strength"}
		err := row.Scan(&s.SubjectKey, &s.LocalDate)
		return s, err
	})
	if err != nil {
		return nil, err
	}
	input.Runs = append(input.Runs, strength...)
	rows, err = tx.Query(ctx, `SELECT session_uid::text,coalesce(activity_id::text,''),coalesce(strong_workout_id::text,''),coalesce(manual_session_id::text,''),status,match_method FROM session_completions`)
	if err != nil {
		return nil, err
	}
	input.Completions, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (matching.Completion, error) {
		var c matching.Completion
		err := row.Scan(&c.SessionUID, &c.ActivityID, &c.StrongWorkoutID, &c.ManualSessionID, &c.Status, &c.MatchMethod)
		return c, err
	})
	if err != nil {
		return nil, err
	}
	var out []Candidate
	for _, c := range matching.PlanMatches(input).Candidates[uid.String()] {
		out = append(out, Candidate{SubjectKey: c.SubjectKey, Reason: c.Reason})
	}
	return out, nil
}
