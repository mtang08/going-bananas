// Package snapshotreads reads display inputs for coaching snapshots.
package snapshotreads

import (
	"context"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
)

// Checkins returns recorded observations and their symptoms from the last 120 days.
// Free-text notes stay in PostgreSQL. Only the phone form's fixed choices leave it.
func Checkins(ctx context.Context, tx pgx.Tx, now time.Time, zone *time.Location) ([]map[string]any, error) {
	rows, err := tx.Query(ctx, `SELECT c.id::text AS checkin_id,c.kind,c.observed_at,c.recorded_at,
		c.fatigue::float8,c.illness,c.gait_change,c.activity_id::text,c.prompt_id::text,c.pain_reported,
		a.end_at, COALESCE(symptoms.items,'[]'::jsonb) AS symptoms,
		CASE WHEN starts_with(c.idempotency_key,'phone-first-steps:') THEN CASE c.note
			WHEN 'First steps: no ankle pain.' THEN 'none'
			WHEN 'First-step ankle pain: gone after walking.' THEN 'gone'
			WHEN 'First-step ankle pain: eased after walking.' THEN 'eased'
			WHEN 'First-step ankle pain: unchanged after walking.' THEN 'same'
			WHEN 'First-step ankle pain: worse after walking.' THEN 'worse'
			WHEN 'First-step ankle pain: too early to assess walking response.' THEN 'too_early'
		END END AS walking_response
		FROM checkins_v2 c LEFT JOIN activities a ON a.id=c.activity_id
		LEFT JOIN LATERAL (SELECT jsonb_agg(jsonb_build_object('site',s.site,'side',s.side,
			'severity',s.severity,'timing',s.timing) ORDER BY s.id) AS items
			FROM symptom_reports s WHERE s.checkin_id=c.id) symptoms ON true
		WHERE c.observed_at BETWEEN $1 AND $2 AND c.recorded_at <= $2
		ORDER BY c.observed_at,c.id`, now.Add(-120*24*time.Hour), now)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (map[string]any, error) {
		value, err := pgx.RowToMap(row)
		if err != nil {
			return nil, err
		}
		observed := value["observed_at"].(time.Time)
		value["local_date"] = observed.In(zone).Format(time.DateOnly)
		value["hours_after_end"] = nil
		if end, ok := value["end_at"].(time.Time); ok && !observed.Before(end) {
			// Python round(x, 1) rounds the binary float to the nearest decimal tenth.
			hours, err := strconv.ParseFloat(strconv.FormatFloat(observed.Sub(end).Hours(), 'f', 1, 64), 64)
			if err != nil {
				return nil, err
			}
			value["hours_after_end"] = hours
		}
		symptoms := value["symptoms"].([]any)
		walking, _ := value["walking_response"].(string)
		switch {
		case walking == "none" && len(symptoms) == 0:
			value["morning_ankle"] = map[string]any{"pain": 0, "walking_response": nil}
		case walking != "" && walking != "none" && len(symptoms) == 1:
			value["morning_ankle"] = map[string]any{"pain": symptoms[0].(map[string]any)["severity"], "walking_response": walking}
		}
		delete(value, "end_at")
		delete(value, "walking_response")
		value["observed_at"] = feedbackInstant(observed)
		value["recorded_at"] = feedbackInstant(value["recorded_at"].(time.Time))
		return value, nil
	})
}

func Prompts(ctx context.Context, tx pgx.Tx, now time.Time) ([]map[string]any, error) {
	rows, err := tx.Query(ctx, `SELECT id::text AS prompt_id,kind,activity_id::text,opens_at,closes_at,
		CASE WHEN status='open' AND closes_at <= $2 THEN 'expired' ELSE status END AS status
		FROM prompts WHERE opens_at BETWEEN $1 AND $2 ORDER BY opens_at,id`, now.Add(-120*24*time.Hour), now)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (map[string]any, error) {
		value, err := pgx.RowToMap(row)
		if err != nil {
			return nil, err
		}
		value["opens_at"] = feedbackInstant(value["opens_at"].(time.Time))
		if end, ok := value["closes_at"].(time.Time); ok {
			value["closes_at"] = feedbackInstant(end)
		}
		return value, nil
	})
}

func feedbackInstant(t time.Time) string {
	layout := "2006-01-02T15:04:05"
	if t.Nanosecond() != 0 {
		layout += ".000000"
	}
	return t.UTC().Format(layout) + "+00:00"
}
