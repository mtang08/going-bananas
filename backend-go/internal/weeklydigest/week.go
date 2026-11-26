// Package weeklydigest reports one athlete-local week of planned and recorded training.
package weeklydigest

import (
	"context"
	_ "embed"
	"encoding/json"
	"math"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/weeklyprojection"
)

//go:embed week.sql
var weekSQL string

type row = map[string]any

func pick(r row, keys ...string) row {
	out := row{}
	for _, k := range keys {
		out[k] = r[k]
	}
	return out
}

func num(v any) *float64 {
	n, ok := v.(float64)
	if !ok || math.IsNaN(n) || math.IsInf(n, 0) || n < 0 {
		return nil
	}
	return &n
}

func class(kind string, recipe, intent any) string {
	if kind != "run" {
		return kind
	}
	if recipe != nil {
		classes := map[string]string{"REC001": "easy", "REC002": "long", "REC003": "quality", "REC004": "quality", "REC005": "quality", "REC006": "quality", "REC007": "easy", "REC008": "quality", "REC009": "benchmark", "REC010": "cross"}
		if result := classes[recipe.(string)]; result != "" {
			return result
		}
		return "unknown"
	}
	text, _ := intent.(string)
	for _, rule := range []struct {
		class string
		words []string
	}{
		{"benchmark", []string{"race", "benchmark", "time trial"}}, {"long", []string{"long"}},
		{"quality", []string{"interval", "tempo", "threshold", "quality", "hill", "vo2", "fartlek"}},
		{"easy", []string{"easy", "recovery", "shakeout"}}} {
		for _, w := range rule.words {
			if strings.Contains(strings.ToLower(text), w) {
				return rule.class
			}
		}
	}
	return "unknown"
}

func outcome(s row, today string) string {
	switch s["status"] {
	case "completed_as_planned":
		return "completed"
	case "completed_modified":
		return "modified"
	case "partial":
		return "partial"
	case "moved":
		return "moved"
	case "skipped":
		return "missed"
	}
	if s["subject_id"] != nil {
		return "recorded"
	}
	if s["local_date"].(string) < today {
		return "not_recorded"
	}
	return "planned"
}

func execution(assessment, interval row) row {
	r := row{"assessment_status": nil, "reason_codes": []string{"ASSESSMENT_MISSING"}, "quality_flags": []string{}, "components": []row{}, "reps_planned": nil, "reps_completed": nil}
	r["reps_planned"], r["reps_completed"] = interval["reps_planned"], interval["reps_completed"]
	if assessment == nil {
		return r
	}
	status := assessment["status"]
	if status != "available" && status != "partial" {
		status = "missing"
	}
	r["assessment_status"] = status
	for _, k := range []string{"reason_codes", "quality_flags"} {
		r[k] = []string{}
		if assessment[k] != nil {
			r[k] = assessment[k]
		}
	}
	value, _ := assessment["value"].(map[string]any)
	cs, _ := value["components"].([]any)
	components := []row{}
	for _, c := range cs {
		if v, ok := c.(map[string]any); ok {
			components = append(components, pick(v, "name", "value", "status"))
		}
	}
	r["components"] = components
	return r
}

type subjectRef struct{ kind, id any }

func LoadWeek(ctx context.Context, tx pgx.Tx, weekStart, asOf string, now time.Time) (map[string]any, error) {
	week, err := time.Parse(time.DateOnly, weekStart)
	if err != nil {
		return nil, err
	}
	today, err := time.Parse(time.DateOnly, asOf)
	if err != nil {
		return nil, err
	}
	var head int
	var zone string
	var pace *float64
	var covered bool
	var planned, subjects, metrics []row
	err = tx.QueryRow(ctx, weekSQL, weekStart, asOf).Scan(&head, &zone, &pace, &covered, &planned, &subjects, &metrics)
	if err != nil {
		return nil, err
	}
	byRef := map[subjectRef]row{}
	for _, s := range subjects {
		for _, k := range []string{"duration_s", "distance_m"} {
			if num(s[k]) == nil {
				s[k] = nil
			}
		}
		byRef[subjectRef{s["subject"], s["id"]}] = s
	}
	assessments, intervals := map[any]row{}, map[any]row{}
	for _, m := range metrics {
		if m["metric_id"] == "planned_actual_session" {
			assessments[m["subject_key"]] = m
		} else {
			intervals[m["subject_key"]] = m
		}
	}
	rows, removed, unplanned := []row{}, []row{}, []row{}
	referenced := map[subjectRef]bool{}
	for _, s := range planned {
		ref := subjectRef{s["subject"], s["subject_id"]}
		if ref.id != nil {
			referenced[ref] = true
		}
		if s["kind"] == "rest" {
			continue
		}
		if s["deleted"] == true {
			removed = append(removed, pick(s, "session_uid", "local_date", "kind"))
			continue
		}
		var interval row
		if ref.kind == "activity" {
			interval = intervals[ref.id]
		}
		r := sessionRow(s, asOf, pace, byRef[ref], assessments[s["session_uid"]], interval)
		rows = append(rows, r)
	}
	slices.SortFunc(removed, func(a, b row) int {
		if x := strings.Compare(a["local_date"].(string), b["local_date"].(string)); x != 0 {
			return x
		}
		return strings.Compare(a["session_uid"].(string), b["session_uid"].(string))
	})
	end := week.AddDate(0, 0, 6).Format(time.DateOnly)
	inWeek := []row{}
	for _, s := range subjects {
		date := s["local_date"].(string)
		if date < weekStart || date > end || s["linked"] == true || s["kind"] == "mobility" || s["kind"] == "rehab" {
			continue
		}
		inWeek = append(inWeek, s)
		if !referenced[subjectRef{s["subject"], s["id"]}] {
			unplanned = append(unplanned, pick(s, "subject", "id", "local_date", "kind", "duration_s", "distance_m"))
		}
	}
	follow, err := followUp(ctx, tx, rows, planned, asOf, now)
	if err != nil {
		return nil, err
	}
	return row{"schema": "weekly_digest.v1", "week_start": weekStart, "week_end": end, "today": asOf, "days_elapsed": max(0, min(7, int(today.Sub(week).Hours()/24)+1)),
		"timezone": zone, "calendar_version": head, "plan_available": head > 0, "activity_coverage_complete": covered,
		"totals": totals(rows, planned, inWeek, unplanned, removed, asOf), "sessions": rows, "unplanned": unplanned, "removed": removed, "decision_follow_up": optionalRow(follow)}, nil
}

func sessionRow(s row, today string, pace *float64, found, assessment, interval row) row {
	r := pick(s, "session_uid", "local_date", "slot", "kind", "recipe_id", "custom", "intent", "modification_reason")
	kind := s["kind"].(string)
	cls := class(kind, s["recipe_id"], s["intent"])
	r["class"], r["key"], r["changed"] = cls, (cls == "long" || cls == "quality" || cls == "benchmark"), s["revision"].(float64) > 1
	r["outcome"] = outcome(s, today)
	raw := structure(s)
	r["planned_duration_s"] = plannedDuration(s, raw)
	var distance *float64
	estimate := false
	if kind == "run" {
		distance, estimate = weeklyprojection.PlannedDistance(num(s["planned_distance_m"]), num(s["planned_duration_s"]), raw, pace)
	}
	r["planned_distance_m"], r["planned_distance_estimated"] = nullable(distance), estimate
	r["execution"], r["actual"] = nil, nil
	if s["subject_id"] != nil {
		r["execution"] = execution(assessment, interval)
		if found != nil {
			r["actual"] = pick(found, "subject", "id", "local_date", "duration_s", "distance_m", "sport", "avg_hr_bpm", "moving_pace_s_per_km", "rpe", "rpe_source")
		}
	}
	return r
}

func structure(r row) json.RawMessage {
	text, _ := r["structure"].(string)
	return json.RawMessage(text)
}

func optionalRow(r row) any {
	if r == nil {
		return nil
	}
	return r
}

func nullable(v *float64) any {
	if v == nil {
		return nil
	}
	return *v
}
func rounded(n float64) float64 {
	v, _ := strconv.ParseFloat(strconv.FormatFloat(n, 'f', 1, 64), 64)
	return v
}
