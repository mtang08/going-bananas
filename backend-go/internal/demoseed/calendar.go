package demoseed

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/calendar"
)

//go:embed briefs.json
var demoBriefs []byte

type demoSession struct {
	id                   uuid.UUID
	day                  time.Time
	kind, intent, recipe string
	duration             int
	strength             *uuid.UUID
	placeholder          bool
	structure            any
}

func monday(day time.Time) time.Time {
	return day.AddDate(0, 0, -(int(day.Weekday())+6)%7)
}

func thresholdStructure(count, duration int) []map[string]any {
	step := func(kind string, seconds int, cue string) map[string]any {
		return map[string]any{"type": kind, "duration_type": "time", "duration_value": seconds, "target": map[string]any{"modality": "effort", "low": nil, "high": nil, "effort_cue": cue}}
	}
	return []map[string]any{step("warmup", 600, "easy"), {"type": "repeat", "count": count, "steps": []map[string]any{step("work", duration, "threshold"), step("recovery", 120, "easy jog")}}, step("cooldown", 600, "easy")}
}

func demoHistory(today time.Time, slots map[string]uuid.UUID) []demoSession {
	var rows []demoSession
	for _, ago := range []int{22, 18, 14, 10, 8, 4, 2, 12, 6} {
		s := demoSession{day: today.AddDate(0, 0, -ago), kind: "run", recipe: "REC001", intent: "Easy run", duration: 1800}
		switch ago {
		case 2:
			s.recipe, s.intent, s.duration = "REC002", "Long run", 4800
		case 18:
			s.recipe, s.intent, s.duration, s.structure = "REC003", "Threshold 5 × 4 min", 3000, thresholdStructure(5, 240)
		case 6, 12, 14, 22:
			s.recipe, s.intent, s.duration, s.structure = "REC003", "Threshold 4 × 5 min", 2880, thresholdStructure(4, 300)
		}
		rows = append(rows, s)
	}
	for ago := 14; ago > 0; ago-- {
		day := today.AddDate(0, 0, -ago)
		label := ""
		switch day.Weekday() {
		case time.Monday:
			label = "Full body A"
		case time.Friday:
			label = "Full body B"
		default:
			continue
		}
		rows = append(rows, demoSession{day: day, kind: "strength", intent: label, duration: 3600, strength: ptr(slots[label])})
	}
	for i, s := range rows {
		slot := 0
		if s.strength != nil {
			slot = 1
		}
		key := fmt.Sprintf("going-bananas-demo:%s:%s:%d", s.day.Format(time.DateOnly), s.kind, slot)
		rows[i].id = uuid.NewSHA1(uuid.NameSpaceURL, []byte(key))
	}
	return rows
}

// Use the same 28-day comparison for each candidate as the bootstrap planner.
// Recent runs classified as long are excluded from the easy-duration median.
const bootstrapDurations = `WITH history AS (
 SELECT a.id,a.start_at,(a.start_at AT TIME ZONE $2)::date AS local_day,a.timer_s
 FROM activities a LEFT JOIN LATERAL (SELECT excluded FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1) annotation ON true
 WHERE a.sport IN ('running','trail_running','treadmill_running') AND a.resolution_state='resolved'
 AND NOT coalesce(annotation.excluded,false) AND a.timer_s>0 AND a.timer_s<'Infinity'::float8
 AND (a.start_at AT TIME ZONE $2)::date >= $1::date-56 AND (a.start_at AT TIME ZONE $2)::date < $1::date
 ), classified AS (
 SELECT h.timer_s,prior.n>=4 AND h.timer_s>=1.33*prior.median is_long FROM history h
 CROSS JOIN LATERAL (SELECT count(*) n,percentile_cont(0.5) WITHIN GROUP(ORDER BY timer_s) median
 FROM history p WHERE p.local_day>=h.local_day-28 AND (p.start_at,p.id)<(h.start_at,h.id)) prior WHERE h.local_day>=$1::date-28
 ), doses AS (SELECT CASE WHEN count(*) FILTER(WHERE NOT is_long)>=3 THEN greatest(300,300*floor(
 (percentile_cont(0.5) WITHIN GROUP(ORDER BY timer_s) FILTER(WHERE NOT is_long))/300+0.5)) ELSE 1800 END easy,
 max(timer_s) FILTER(WHERE is_long) longest FROM classified)
 SELECT easy::int,greatest(300,300*floor(coalesce(longest/300,1.33*easy/300+0.5)))::int FROM doses`

func demoPlan(today, effective time.Time, easy, long int, slots map[string]uuid.UUID) []demoSession {
	weeks := map[string][]time.Time{}
	for i := 0; i < 14; i += 2 {
		d := today.AddDate(0, 0, i)
		w := monday(d).Format(time.DateOnly)
		weeks[w] = append(weeks[w], d)
	}
	var rows []demoSession
	for i := 0; i < 14; i += 2 {
		day := today.AddDate(0, 0, i)
		days := weeks[monday(day).Format(time.DateOnly)]
		last := days[len(days)-1] // The latest opportunity always selects the weekend if one exists.
		s := demoSession{id: uuid.New(), day: day, kind: "run", recipe: "REC001", intent: "Easy run", duration: easy}
		switch {
		case day.Equal(last):
			s.recipe, s.intent, s.duration = "REC002", "Long aerobic run", long
		case day.Equal(days[0]) && !day.After(last.AddDate(0, 0, -2)):
			s.recipe, s.intent, s.placeholder = "", "Quality slot — selected at first review", true
		}
		rows = append(rows, s)
	}
	position := 0
	for d := monday(today); d.Before(today.AddDate(0, 0, 14)); d = d.AddDate(0, 0, 1) {
		if d.Weekday() == time.Monday {
			position = 0
		}
		if d.Before(effective) || (d.Weekday() != time.Monday && d.Weekday() != time.Friday) {
			continue
		}
		label := []string{"Full body A", "Full body B"}[position%2]
		position++
		if !d.Before(today) {
			rows = append(rows, demoSession{id: uuid.New(), day: d, kind: "strength", intent: label, strength: ptr(slots[label])})
		}
	}
	return rows
}

func writeSeedVersion(ctx context.Context, tx pgx.Tx, number int, today time.Time, rows []demoSession, kind string, reason *string) error {
	_, err := tx.Exec(ctx, "INSERT INTO calendar_versions(id,number,parent_number,kind,actor,reason) VALUES(gen_random_uuid(),$1::int,nullif($1::int-1,0),$2,'system',$3)", number, kind, reason)
	if err != nil {
		return err
	}
	for _, s := range rows {
		slot := 0
		if s.strength != nil {
			slot = 1
		}
		_, err = tx.Exec(ctx, `INSERT INTO calendar_session_revisions(id,session_uid,revision,calendar_version_number,local_date,slot,kind,recipe_id,placeholder,intent,certainty,planned_duration_s,structure,strength_slot_id)
 VALUES(gen_random_uuid(),$1,1,$2,$3::date,$4,$5,nullif($6,''),$7,$8,CASE WHEN $3::date<=$9::date+6 THEN 'committed' ELSE 'provisional' END,nullif($10::int,0),$11,$12)`, s.id, number, s.day.Format(time.DateOnly), slot, s.kind, s.recipe, s.placeholder, s.intent, today.Format(time.DateOnly), s.duration, s.structure, s.strength)
		if err != nil {
			return err
		}
	}
	_, err = tx.Exec(ctx, "UPDATE app_state SET calendar_head_version=$1 WHERE id=1", number)
	return err
}

func seedCalendar(ctx context.Context, tx pgx.Tx, today, _ time.Time, slots map[string]uuid.UUID) error {
	var zone, effective string
	var confirmed bool
	err := tx.QueryRow(ctx, `SELECT timezone,(effective_at AT TIME ZONE timezone)::date::text,
 anchor_confirmed AND strength_days_confirmed AND cycle_anchor=$1::date-28 FROM profile_versions ORDER BY version DESC LIMIT 1`, today.Format(time.DateOnly)).Scan(&zone, &effective, &confirmed)
	if err != nil {
		return err
	}
	if !confirmed || slots["Full body A"] == uuid.Nil || slots["Full body B"] == uuid.Nil {
		return errors.New("demo schedule is unconfirmed")
	}
	effectiveDay, err := time.ParseInLocation(time.DateOnly, effective, today.Location())
	if err != nil {
		return err
	}
	var easy, long int
	if err = tx.QueryRow(ctx, bootstrapDurations, today.Format(time.DateOnly), zone).Scan(&easy, &long); err != nil {
		return err
	}
	future := demoPlan(today, effectiveDay, easy, long, slots)
	if err = writeSeedVersion(ctx, tx, 1, today, future, "bootstrap", nil); err != nil {
		return err
	}
	reason := "synthetic history fixture"
	if err = writeSeedVersion(ctx, tx, 2, today, demoHistory(today, slots), "manual_edit", &reason); err != nil {
		return err
	}
	var briefs map[string]json.RawMessage
	if err = json.Unmarshal(demoBriefs, &briefs); err != nil {
		return err
	}
	head := 2
	apply := func(actor, reason string, edits []calendar.PlanEdit) error {
		// The demo changes only the recipe/intent or brief of a supplied easy or long run.
		check := func(_, after json.RawMessage, _ bool) error {
			var s struct {
				Kind   string
				Recipe string `json:"recipe_id"`
			}
			if err := json.Unmarshal(after, &s); err != nil {
				return err
			}
			if s.Kind != "run" || briefs[s.Recipe] == nil {
				return errors.New("unexpected seed prescription")
			}
			return nil
		}
		out, err := calendar.ApplyEdits(ctx, tx, calendar.EditBatch{Head: head, Today: today.Format(time.DateOnly), Kind: "manual_edit", Actor: actor, Reason: &reason, Edits: edits}, check)
		head = out.Version
		return err
	}
	priorWeek := monday(today.AddDate(0, 0, -2))
	var edits []calendar.PlanEdit
	for i := range future {
		s := &future[i]
		if s.recipe == "REC002" && monday(s.day).Equal(priorWeek) {
			if err := apply("system", "synthetic fixture: retain one planned long run per week", []calendar.PlanEdit{{Op: "modify", SessionUID: &s.id, Fields: json.RawMessage(`{"recipe_id":"REC001","intent":"Easy run"}`)}}); err != nil {
				return err
			}
			s.recipe = "REC001"
		}
		if brief := briefs[s.recipe]; brief != nil {
			fields, err := json.Marshal(map[string]json.RawMessage{"brief": brief})
			if err != nil {
				return err
			}
			edits = append(edits, calendar.PlanEdit{Op: "modify", SessionUID: &s.id, Fields: fields})
		}
	}
	if len(edits) > 0 {
		return apply("coach", "synthetic fixture: coach briefs", edits)
	}
	return nil
}
