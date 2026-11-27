package calendar

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"maps"
	"math"
	"slices"
	"strings"
	"time"
)

type historicRun struct {
	day      time.Time
	duration float64
}

func median(values []float64) float64 {
	v := slices.Clone(values)
	slices.Sort(v)
	n := len(v)
	return (v[(n-1)/2] + v[n/2]) / 2
}
func bootstrapDoses(history []historicRun, today time.Time) (int, int) {
	var easySamples, longSamples []float64
	for i, r := range history {
		if r.day.Before(today.AddDate(0, 0, -28)) {
			continue
		}
		var prior []float64
		for _, p := range history[:i] {
			if !p.day.Before(r.day.AddDate(0, 0, -28)) {
				prior = append(prior, p.duration)
			}
		}
		if len(prior) >= 4 && r.duration >= 1.33*median(prior) {
			longSamples = append(longSamples, r.duration)
		} else {
			easySamples = append(easySamples, r.duration)
		}
	}
	round := func(n float64) int { return max(300, int(math.Floor(n/300+0.5))*300) }
	easy := 1800
	if len(easySamples) >= 3 {
		easy = round(median(easySamples))
	}
	long := round(1.33 * float64(easy))
	if len(longSamples) > 0 {
		long = max(300, int(slices.Max(longSamples)/300)*300)
	}
	return easy, long
}
func isoWeekday(d time.Time) int { return (int(d.Weekday()) + 6) % 7 }
func bootstrapRuns(anchor, start time.Time, easy, long int) []revisionRow {
	daysByWeek := map[string][]time.Time{}
	for i := range 14 {
		d := start.AddDate(0, 0, i)
		if int(d.Sub(anchor).Hours()/24)%2 != 0 {
			continue
		}
		monday := d.AddDate(0, 0, -isoWeekday(d)).Format(time.DateOnly)
		daysByWeek[monday] = append(daysByWeek[monday], d)
	}
	var rows []revisionRow
	for _, week := range slices.Sorted(maps.Keys(daysByWeek)) {
		days := daysByWeek[week]
		last := days[len(days)-1]
		quality := days[0]
		for _, d := range days {
			f := maps.Clone(optionalFields)
			f["kind"] = "run"
			f["local_date"] = d.Format(time.DateOnly)
			f["legacy_unstructured"] = false
			f["legacy_payload"] = nil
			switch {
			case d.Equal(last):
				f["recipe_id"] = "REC002"
				f["intent"] = "Long aerobic run"
				f["planned_duration_s"] = long
			case d.Equal(quality) && !d.After(last.AddDate(0, 0, -2)):
				f["placeholder"] = true
				f["intent"] = "Quality slot — selected at first review"
				f["planned_duration_s"] = easy
			default:
				f["recipe_id"] = "REC001"
				f["intent"] = "Easy run"
				f["planned_duration_s"] = easy
			}
			rows = append(rows, revisionRow{uid: uuid.New(), revision: 1, fields: f})
		}
	}
	return rows
}

type scheduleProfile struct {
	Anchor    string `json:"cycle_anchor"`
	Confirmed bool   `json:"anchor_confirmed"`
	Strength  bool   `json:"strength_days_confirmed"`
	Mode      string `json:"strength_schedule_mode"`
	Week      []int  `json:"scheduled_strength_days"`
	FirstWeek string `json:"strength_week_a_start"`
	A         []int  `json:"strength_week_a_days"`
	B         []int  `json:"strength_week_b_days"`
	MobA      []int  `json:"mobility_week_a_days"`
	MobB      []int  `json:"mobility_week_b_days"`
	Optional  []int  `json:"mobility_optional_days"`
}
type routineSlot struct {
	id    *uuid.UUID
	label string
}

func routineSlots(ctx context.Context, tx pgx.Tx, today time.Time) ([]routineSlot, error) {
	var version int
	if err := tx.QueryRow(ctx, "SELECT coalesce(max(version),0) FROM strength_routine_slots").Scan(&version); err != nil {
		return nil, err
	}
	out := []routineSlot{}
	if version > 0 {
		rows, err := tx.Query(ctx, `SELECT id,label FROM strength_routine_slots WHERE active AND version=$1 ORDER BY label COLLATE "C",id`, version)
		if err != nil {
			return nil, err
		}
		return pgx.CollectRows(rows, func(r pgx.CollectableRow) (routineSlot, error) {
			var s routineSlot
			err := r.Scan(&s.id, &s.label)
			return s, err
		})
	}
	rows, err := tx.Query(ctx, `SELECT left(trim(workout_name),40) FROM strong_workouts WHERE resolution_state='resolved' AND local_date BETWEEN $1::date-55 AND $1::date AND trim(workout_name)<>'' GROUP BY trim(workout_name) ORDER BY count(*) DESC,trim(workout_name) COLLATE "C" LIMIT 2`, today.Format(time.DateOnly))
	if err != nil {
		return nil, err
	}
	names, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, err
	}
	for _, n := range names {
		out = append(out, routineSlot{label: n})
	}
	for _, pad := range []string{"Full body A", "Full body B"}[len(out):] {
		out = append(out, routineSlot{label: pad})
	}
	return out, nil
}
func routineRows(p scheduleProfile, effective string, start time.Time, slots []routineSlot) []revisionRow {
	a := p.Week
	alternating := p.Mode == "alternating"
	first, _ := time.Parse(time.DateOnly, p.FirstWeek)
	if alternating {
		a = p.A
		if len(p.B) != 2 || first.IsZero() || isoWeekday(first) != 0 {
			return nil
		}
	}
	if len(a) != 2 {
		return nil
	}
	var out []revisionRow
	end := start.AddDate(0, 0, 13)
	position := 0
	for d := start.AddDate(0, 0, -isoWeekday(start)); !d.After(end); d = d.AddDate(0, 0, 1) {
		day := d.Format(time.DateOnly)
		wd := isoWeekday(d)
		if wd == 0 {
			position = 0
		}
		if day < effective {
			continue
		}
		days := a
		var mob []int
		if alternating {
			mob = p.MobA
			week := d.AddDate(0, 0, -wd)
			if int(week.Sub(first).Hours()/(7*24))%2 != 0 {
				days = p.B
				mob = p.MobB
			}
		}
		add := func(kind, label string, slot int, id *uuid.UUID, optional bool) {
			if d.Before(start) {
				return
			}
			f := maps.Clone(optionalFields)
			f["local_date"] = day
			f["kind"] = kind
			f["intent"] = label
			f["slot"] = slot
			f["legacy_unstructured"] = false
			if id != nil {
				f["strength_slot_id"] = id.String()
			}
			if optional {
				f["legacy_payload"] = map[string]bool{"optional": true}
			}
			out = append(out, revisionRow{uid: uuid.New(), revision: 1, fields: f})
		}
		if slices.Contains(days, wd) {
			s := routineSlot{label: "Strength"}
			if len(slots) > 0 {
				s = slots[position%len(slots)]
			}
			position++
			add("strength", s.label, 1, s.id, false)
		}
		if alternating && (slices.Contains(mob, wd) || slices.Contains(p.Optional, wd)) {
			add("mobility", "Mobility", 2, nil, !slices.Contains(mob, wd))
		}
	}
	return out
}
func Bootstrap(ctx context.Context, tx pgx.Tx, anchor, start, today time.Time) (AppliedEdits, error) {
	out := AppliedEdits{Created: map[string]uuid.UUID{}, Preserved: []uuid.UUID{}, Stale: []uuid.UUID{}}
	head, err := lockedHead(ctx, tx)
	if err != nil {
		return out, err
	}
	if start.Before(today) {
		return out, &Problem{"protected_session", "Ordinary bootstrap cannot create historical sessions"}
	}
	if head != 0 {
		return out, &Problem{"calendar_exists", "Calendar already has a version"}
	}
	var raw json.RawMessage
	var effective, zone string
	err = tx.QueryRow(ctx, `SELECT to_jsonb(p),(effective_at AT TIME ZONE timezone)::date::text,timezone FROM profile_versions p ORDER BY version DESC LIMIT 1`).Scan(&raw, &effective, &zone)
	var profile scheduleProfile
	if err == nil {
		if err := json.Unmarshal(raw, &profile); err != nil {
			return out, err
		}
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return out, err
	}
	if !profile.Confirmed || !profile.Strength || profile.Anchor != anchor.Format(time.DateOnly) {
		return out, &Problem{"bootstrap_profile_unconfirmed", "Confirmed anchor and strength schedule required"}
	}
	rows, err := tx.Query(ctx, `SELECT (a.start_at AT TIME ZONE $1)::date::text,a.timer_s FROM activities a LEFT JOIN LATERAL (SELECT excluded FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1) n ON true WHERE a.sport IN ('running','trail_running','treadmill_running') AND a.resolution_state='resolved' AND NOT coalesce(n.excluded,false) AND a.timer_s>0 AND a.timer_s<'Infinity'::float8 AND (a.start_at AT TIME ZONE $1)::date BETWEEN $2::date-56 AND $2::date-1 ORDER BY a.start_at,a.id`, zone, today.Format(time.DateOnly))
	if err != nil {
		return out, err
	}
	history, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (historicRun, error) {
		var h historicRun
		var day string
		if err := r.Scan(&day, &h.duration); err != nil {
			return h, err
		}
		h.day, err = time.Parse(time.DateOnly, day)
		return h, err
	})
	if err != nil {
		return out, err
	}
	easy, long := bootstrapDoses(history, today)
	plans := bootstrapRuns(anchor, start, easy, long)
	slots, err := routineSlots(ctx, tx, today)
	if err != nil {
		return out, err
	}
	plans = append(plans, routineRows(profile, effective, start, slots)...)
	slices.SortStableFunc(plans, func(a, b revisionRow) int {
		if day := strings.Compare(a.fields["local_date"].(string), b.fields["local_date"].(string)); day != 0 {
			return day
		}
		order := map[string]int{"run": 0, "strength": 1, "mobility": 2}
		return order[a.fields["kind"].(string)] - order[b.fields["kind"].(string)]
	})
	b := EditBatch{Head: 0, Today: today.Format(time.DateOnly), Kind: "bootstrap", Actor: "system"}
	return appendEdits(ctx, tx, b, map[uuid.UUID]revisionRow{}, plans, out)
}
