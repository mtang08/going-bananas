// Package snapshotreads reads the display inputs for coaching snapshots.
package snapshotreads

import (
	"context"
	"encoding/json"

	"github.com/jackc/pgx/v5"
)

// Planning holds the calendar, strength, and goal projections used by the snapshot.
// Each array contains only the public fields selected by the Python snapshot loader.
type Planning struct {
	Sessions       json.RawMessage `json:"sessions"`
	Completions    json.RawMessage `json:"completions"`
	StrengthSlots  json.RawMessage `json:"strength_slots"`
	StrongWorkouts json.RawMessage `json:"strong_workouts"`
	Goals          json.RawMessage `json:"goals"`
}

func LoadPlanning(ctx context.Context, tx pgx.Tx, asOf string) (Planning, error) {
	var result Planning
	err := tx.QueryRow(ctx, planningSQL, asOf).Scan(&result.Sessions, &result.Completions,
		&result.StrengthSlots, &result.StrongWorkouts, &result.Goals)
	return result, err
}

const planningSQL = `
WITH newest AS (
	SELECT DISTINCT ON (session_uid) * FROM calendar_session_revisions
	WHERE calendar_version_number <= (SELECT calendar_head_version FROM app_state WHERE id=1)
	ORDER BY session_uid, calendar_version_number DESC, revision DESC
), sessions AS (
	SELECT session_uid, revision, local_date, slot, kind, recipe_id, custom, placeholder, locked,
		intent, CASE WHEN local_date <= $1::date + 6 THEN 'committed' ELSE 'provisional' END AS certainty,
		planned_duration_s, planned_distance_m, structure, strength_slot_id, brief
	FROM newest WHERE NOT deleted AND local_date BETWEEN $1::date - 120 AND $1::date + 42
), completions AS (
	SELECT session_uid, status, match_method, activity_id, strong_workout_id, manual_session_id,
		modification_reason FROM session_completions
), slots AS (
	SELECT id AS slot_id, label, default_weekday, lower_body_cost, typical_duration_s,
		main_lower_body_lifts, active FROM strength_routine_slots
), workouts AS (
	SELECT w.local_date, w.workout_name, w.duration_s, w.id AS strong_workout_id,
		(SELECT rpe FROM session_rpe WHERE strong_workout_id=w.id AND source IN ('manual','garmin_fit')
		 ORDER BY (source='manual') DESC, collected_at DESC, id DESC LIMIT 1) AS rpe
	FROM strong_workouts w WHERE resolution_state='resolved' AND local_date BETWEEN $1::date - 120 AND $1::date
), goals AS (
	SELECT id AS goal_id, text, horizon, priority, status FROM goals WHERE status='active'
)
SELECT
	COALESCE((SELECT json_agg(s ORDER BY local_date,slot,session_uid) FROM sessions s),'[]'),
	COALESCE((SELECT json_agg(c ORDER BY session_uid) FROM completions c),'[]'),
	COALESCE((SELECT json_agg(s ORDER BY default_weekday,slot_id) FROM slots s),'[]'),
	COALESCE((SELECT json_agg(w ORDER BY local_date,strong_workout_id) FROM workouts w),'[]'),
	COALESCE((SELECT json_agg(g ORDER BY priority,goal_id) FROM goals g),'[]')`
