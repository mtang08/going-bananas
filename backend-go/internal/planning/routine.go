package planning

import (
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5"
	"strings"
	"unicode/utf8"
)

type Slot struct {
	Label    string   `json:"label"`
	Weekday  int      `json:"default_weekday"`
	Cost     string   `json:"lower_body_cost"`
	Duration *int     `json:"typical_duration_s"`
	Lifts    []string `json:"main_lower_body_lifts"`
	Active   bool     `json:"active"`
}

const profileProjection = `SELECT to_jsonb(p)-'id'-'recorded_at'-'effective_at' FROM profile_versions p ORDER BY version DESC LIMIT 1`
const defaults = `{"version":0,"timezone":"America/New_York","cycle_anchor":null,"anchor_confirmed":false,"strength_days_confirmed":false,"scheduled_strength_days":[],"strength_schedule_mode":"weekly","strength_week_a_start":null,"strength_week_a_days":[],"strength_week_b_days":[],"mobility_week_a_days":[],"mobility_week_b_days":[],"mobility_optional_days":[],"facts":{},"preferences":{},"unknowns":[]}`

func Profile(ctx context.Context, tx pgx.Tx) (json.RawMessage, error) {
	return jsonRow(ctx, tx, "SELECT coalesce(("+profileProjection+"),'"+defaults+"'::jsonb)")
}

const suggestedSlots = `WITH recent AS (
 SELECT id,trim(workout_name) AS name,local_date,(extract(isodow FROM local_date)::int-1) AS weekday,duration_s,sets FROM strong_workouts
 WHERE resolution_state='resolved' AND local_date BETWEEN $1::date-55 AND $1::date AND trim(workout_name)<>''
), chosen AS (
 SELECT name,count(*) AS frequency,percentile_cont(0.5) within group(order by duration_s) FILTER(WHERE duration_s>0 AND duration_s<'Infinity'::float8) AS duration FROM recent GROUP BY name ORDER BY frequency DESC,name COLLATE "C" LIMIT 2
), lifts AS (
 SELECT DISTINCT ON (r.id,lower(trim(item->>'Exercise Name'))) r.id,r.name,r.local_date,lower(trim(item->>'Exercise Name')) AS key,trim(item->>'Exercise Name') AS label
 FROM recent r CROSS JOIN LATERAL jsonb_array_elements(r.sets) WITH ORDINALITY AS entry(item,n)
 WHERE item->>'Exercise Name' ~* 'squat|deadlift|lunge|rdl|leg press|hip thrust|step up|leg curl' ORDER BY r.id,key,n
), counts AS (
 SELECT name,key,count(*) AS frequency,(array_agg(label ORDER BY local_date DESC,id DESC))[1] AS label FROM lifts GROUP BY name,key
)
SELECT left(c.name,40) as label,(SELECT weekday FROM recent r WHERE r.name=c.name GROUP BY weekday ORDER BY count(*) DESC,weekday LIMIT 1) AS default_weekday,
 'moderate' AS lower_body_cost,CASE WHEN c.duration IS NOT NULL THEN greatest(300,floor(c.duration/300+0.5)*300)::integer END AS typical_duration_s,
 ARRAY(SELECT label FROM counts WHERE name=c.name ORDER BY frequency DESC,key COLLATE "C" LIMIT 3) AS main_lower_body_lifts,true AS active
 FROM chosen c ORDER BY c.frequency DESC,c.name COLLATE "C"`

func Routine(ctx context.Context, tx pgx.Tx, today string) (map[string]any, error) {
	var version int
	if err := tx.QueryRow(ctx, "SELECT coalesce(max(version),0) FROM strength_routine_slots").Scan(&version); err != nil {
		return nil, err
	}
	profile, err := Profile(ctx, tx)
	if err != nil {
		return nil, err
	}
	var cfg map[string]any
	if err = json.Unmarshal(profile, &cfg); err != nil {
		return nil, err
	}
	for _, key := range []string{"version", "timezone", "cycle_anchor", "anchor_confirmed", "facts", "preferences", "unknowns"} {
		delete(cfg, key)
	}
	out := map[string]any{"version": version, "suggested": version == 0, "schedule": cfg}
	if version != 0 {
		slots, err := jsonRow(ctx, tx, "SELECT coalesce(jsonb_agg(s ORDER BY label,id),'[]') FROM strength_routine_slots s WHERE version=$1 AND active", version)
		out["slots"] = slots
		return out, err
	}
	rows, err := tx.Query(ctx, suggestedSlots, today)
	if err != nil {
		return nil, err
	}
	slots, err := pgx.CollectRows(rows, pgx.RowToStructByPos[Slot])
	if err != nil {
		return nil, err
	}
	for len(slots) < 2 {
		i := len(slots)
		slots = append(slots, Slot{Label: []string{"Full body A", "Full body B"}[i], Weekday: []int{0, 4}[i], Cost: "moderate", Lifts: []string{}, Active: true})
	}
	type suggestion struct {
		Slot
		ID      *string `json:"id"`
		Version int     `json:"version"`
	}
	suggested := make([]suggestion, len(slots))
	for i, s := range slots {
		suggested[i].Slot = s
	}
	out["slots"] = suggested
	return out, nil
}
func ReplaceRoutine(ctx context.Context, tx pgx.Tx, today string, expected int, slots []Slot) (map[string]any, error) {
	var version int
	if err := tx.QueryRow(ctx, "SELECT coalesce(max(version),0) FROM strength_routine_slots").Scan(&version); err != nil {
		return nil, err
	}
	if expected != version {
		return nil, &Problem{409, "version_conflict", "Routine changed; reload before editing"}
	}
	if len(slots) == 0 {
		return nil, &Problem{422, "routine_empty", "At least one routine slot is required"}
	}
	for _, s := range slots {
		s.Label = strings.TrimSpace(s.Label)
		var msg string
		switch {
		case s.Label == "" || utf8.RuneCountInString(s.Label) > 40:
			msg = "Routine label must be 1–40 characters"
		case s.Weekday < 0 || s.Weekday > 6:
			msg = "Weekday must be 0–6"
		case s.Duration != nil && *s.Duration <= 0:
			msg = "Duration must be positive seconds"
		}
		for i, l := range s.Lifts {
			s.Lifts[i] = strings.TrimSpace(l)
			if msg == "" && s.Lifts[i] == "" {
				msg = "Lift names must be nonblank"
			}
		}
		if msg != "" {
			return nil, &Problem{422, "invalid_routine_slot", msg}
		}
		_, err := tx.Exec(ctx, `INSERT INTO strength_routine_slots(id,version,label,default_weekday,lower_body_cost,typical_duration_s,main_lower_body_lifts,active) VALUES(gen_random_uuid(),$1,$2,$3,$4,$5,$6,$7)`, version+1, s.Label, s.Weekday, s.Cost, s.Duration, s.Lifts, s.Active)
		if err != nil {
			return nil, err
		}
	}
	return Routine(ctx, tx, today)
}
