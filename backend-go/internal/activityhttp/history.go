package activityhttp

import (
	"cmp"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/calendarstructure"
	"math"
	"net/http"
	"slices"
	"strconv"
	"strings"
	"time"
)

type historyPlan struct {
	uid, day                                                 string
	recipe                                                   *string
	intent                                                   string
	structure                                                json.RawMessage
	activity, actualDay, sport, completion, metricID, status *string
	reasons                                                  []string
	value                                                    object
}
type facts struct {
	signature string
	count     int
	recovery  any
	targets   []string
}

func planFacts(raw json.RawMessage) (facts, error) {
	if len(raw) == 0 || string(raw) == "null" || string(raw) == "[]" {
		return facts{}, nil
	}
	steps, ok := calendarstructure.Expand(raw)
	if !ok {
		return facts{}, errors.New("invalid_structure")
	}
	var f facts
	var words []string
	lastToken := ""
	repeat := 0
	first, last := -1, -1
	flush := func() {
		if repeat > 0 {
			words = append(words, fmt.Sprintf("%dx%s", repeat, lastToken))
		}
	}
	for i, s := range steps {
		if s.Type != "work" {
			continue
		}
		if first < 0 {
			first = i
		}
		last = i
		f.count++
		prefix, bin := "t", 5.
		if s.DurationType == "distance" {
			prefix, bin = "d", 10.
		}
		token := fmt.Sprintf("%s%d", prefix, int(bin*math.RoundToEven(s.DurationValue/bin)))
		if token != lastToken {
			flush()
			lastToken = token
			repeat = 0
		}
		repeat++
		modality := "effort"
		if s.Target != nil {
			modality = s.Target.Modality
		}
		f.targets = append(f.targets, modality)
	}
	if first < 0 {
		return f, nil
	}
	flush()
	f.signature = "ws1:" + strings.Join(words, "+")
	slices.Sort(f.targets)
	f.targets = slices.Compact(f.targets)
	sec := 0.
	f.recovery = sec
	for _, s := range steps[first : last+1] {
		if s.Type == "recovery" {
			if s.DurationType != "time" {
				f.recovery = nil
				break
			}
			sec += s.DurationValue
			f.recovery = sec
		}
	}
	return f, nil
}
func decimal(x float64, digits int) float64 {
	n, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', digits, 64), 64)
	return n
}
func point(p historyPlan, f facts) object {
	day := p.day
	if p.actualDay != nil {
		day = *p.actualDay
	}
	flags := []string{}
	if p.sport != nil && *p.sport == "treadmill_running" {
		flags = append(flags, "TREADMILL")
	}
	v := object{"activity_id": p.activity, "session_uid": p.uid, "local_date": day, "planned_date": p.day, "recipe_id": p.recipe, "intent": p.intent, "signature": f.signature, "recovery_s": f.recovery, "target_modalities": f.targets, "sport": p.sport, "completion_status": p.completion, "status": "missing", "quality_flags": flags, "n_planned": f.count, "n_completed": nil, "step_completion_ratio": nil, "reps_used": 0, "reps_used_hr": 0, "work_speed_mps": nil, "work_hr_bpm": nil, "work_m_per_beat": nil, "cv_speed": nil, "last_first_change_pct": nil, "target_coverage": nil, "interval_result_id": p.metricID}
	if p.activity == nil {
		v["reason_codes"] = []string{"NO_LINKED_ACTIVITY"}
		return v
	}
	if p.metricID == nil {
		v["reason_codes"] = []string{"INTERVAL_RESULT_MISSING"}
		return v
	}
	reasons := p.reasons
	if p.value == nil {
		slices.Sort(reasons)
		v["reason_codes"] = reasons
		v["status"] = "not_assessable"
		return v
	}
	for _, k := range []string{"n_planned", "n_completed", "step_completion_ratio", "cv_speed", "last_first_change_pct", "target_coverage"} {
		v[k] = p.value[k]
	}
	var weight, speed, hrWeight, hrSpeed, hr float64
	used, usedHR := 0, 0
	reps, _ := p.value["reps"].([]any)
	for _, item := range reps {
		rep := item.(map[string]any)
		s, ok := rep["mean_speed_mps"].(float64)
		t, _ := rep["actual_timer_s"].(float64)
		if rep["fully_completed"] != true || rep["speed_status"] != "available" || !ok || t <= 0 {
			continue
		}
		used++
		weight += t
		speed += s * t
		if h, ok := rep["hr_median_bpm"].(float64); ok {
			hrWeight += t
			hrSpeed += s * t
			hr += h * t
			usedHR++
		}
	}
	if weight > 0 {
		v["work_speed_mps"] = decimal(speed/weight, 3)
	}
	if hrWeight > 0 {
		v["work_hr_bpm"] = decimal(hr/hrWeight, 1)
		if hr != 0 {
			v["work_m_per_beat"] = decimal(60*(hrSpeed/hrWeight)/(hr/hrWeight), 3)
		}
	}
	v["reps_used"] = used
	v["reps_used_hr"] = usedHR
	complete, _ := p.value["n_completed"].(float64)
	planned, _ := p.value["n_planned"].(float64)
	if float64(used) < complete {
		reasons = append(reasons, "REPS_EXCLUDED")
	}
	slices.Sort(reasons)
	v["reason_codes"] = slices.Compact(reasons)
	v["status"] = "partial"
	if *p.status == "available" && float64(used) == planned {
		v["status"] = "available"
	}
	return v
}

const latestPlans = `WITH latest AS (SELECT DISTINCT ON(r.session_uid) r.* FROM calendar_session_revisions r JOIN app_state h ON h.id=1
 WHERE r.calendar_version_number<=h.calendar_head_version ORDER BY r.session_uid,r.calendar_version_number DESC,r.revision DESC) `

func (h Handler) history(ctx context.Context, tx pgx.Tx, r *http.Request, _ time.Time, loc *time.Location) (any, error) {
	id, idErr := activityID(r)
	size, limitErr := limit(r.URL.Query(), 6, 2, 20)
	if err := bindingErrors(idErr, limitErr); err != nil {
		return nil, err
	}
	var day, sport string
	err := tx.QueryRow(ctx, "SELECT (start_at AT TIME ZONE $2)::date::text,sport FROM activities WHERE id=$1", id, loc.String()).Scan(&day, &sport)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, &problem{404, "activity_not_found", "Activity not found", nil}
	}
	if err != nil {
		return nil, err
	}
	if !isRun(sport) {
		return nil, &problem{422, "not_run_activity", "Activity is not a run", nil}
	}
	v := object{"activity_id": id.String(), "signature": nil, "reason": nil, "points": []object{}}
	var raw []byte
	err = tx.QueryRow(ctx, latestPlans+`SELECT p.structure FROM latest p JOIN session_completions c ON c.session_uid=p.session_uid WHERE c.activity_id=$1 AND NOT p.deleted AND p.kind='run'`, id).Scan(&raw)
	if errors.Is(err, pgx.ErrNoRows) {
		v["reason"] = "NO_PLAN_LINK"
		return v, nil
	}
	if err != nil {
		return nil, err
	}
	if len(raw) == 0 || string(raw) == "null" {
		v["reason"] = "NO_STRUCTURED_PLAN"
		return v, nil
	}
	current, err := planFacts(raw)
	if err != nil {
		return nil, err
	}
	if current.signature == "" {
		v["reason"] = "NO_WORK_STEPS"
		return v, nil
	}
	v["signature"] = current.signature
	focus, err := time.Parse(time.DateOnly, day)
	if err != nil {
		return nil, err
	}
	points, err := progressionPoints(ctx, tx, focus.AddDate(0, 0, -365), focus.AddDate(0, 0, 7), loc)
	if err != nil {
		return nil, err
	}
	points = slices.DeleteFunc(points, func(p object) bool { return p["signature"] != current.signature || p["local_date"].(string) > day })
	if len(points) > size {
		points = points[len(points)-size:]
	}
	v["points"] = points
	return v, nil
}

func progressionPoints(ctx context.Context, tx pgx.Tx, first, last time.Time, loc *time.Location) ([]object, error) {
	rows, err := tx.Query(ctx, latestPlans+`SELECT p.session_uid::text,p.local_date::text,p.recipe_id,p.intent,p.structure,a.id::text,(a.start_at AT TIME ZONE $2)::date::text,a.sport,c.status,m.id::text,m.status,m.reason_codes,m.value
 FROM latest p LEFT JOIN session_completions c USING(session_uid) LEFT JOIN activities a ON a.id=c.activity_id AND a.sport IN ('running','trail_running','treadmill_running')
 LEFT JOIN metric_results m ON m.subject_key=a.id::text AND m.metric_id='work_interval_execution' AND m.method_version='v2' AND m.is_current
 WHERE NOT p.deleted AND p.kind='run' AND p.structure IS NOT NULL AND p.local_date BETWEEN $1::text::date AND $3::text::date`, first.Format(time.DateOnly), loc.String(), last.Format(time.DateOnly))
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	points := []object{}
	for rows.Next() {
		var p historyPlan
		if err := rows.Scan(&p.uid, &p.day, &p.recipe, &p.intent, &p.structure, &p.activity, &p.actualDay, &p.sport, &p.completion, &p.metricID, &p.status, &p.reasons, &p.value); err != nil {
			return nil, err
		}
		f, err := planFacts(p.structure)
		if err != nil {
			return nil, err
		}
		if f.signature != "" {
			points = append(points, point(p, f))
		}
	}
	slices.SortFunc(points, func(a, b object) int {
		return cmp.Or(strings.Compare(a["local_date"].(string), b["local_date"].(string)), strings.Compare(a["session_uid"].(string), b["session_uid"].(string)))
	})
	return points, rows.Err()
}
func isRun(s string) bool {
	return slices.Contains([]string{"running", "trail_running", "treadmill_running"}, s)
}
