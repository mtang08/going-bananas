package snapshots

import (
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"math"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/calendarstructure"
)

const metricFields = "result_id metric_id method_version subject_type subject_key window_label status quality_status value unit reason_codes quality_flags anchor_keys calculated_at"

func (d displayData) addAdvanced(out obj) error {
	if d.op == rolling || d.op == blockReview || d.op == quality {
		groups, err := d.qualityProgression()
		if err != nil {
			return err
		}
		out["quality_progression"] = groups
	}
	if d.op == rolling || d.op == blockReview {
		out["aerobic_efficiency"] = d.aerobicEfficiency()
		weeks := records{}
		for _, w := range d.rows("weekly_digest") {
			weeks = append(weeks, digestView(w))
		}
		out["weekly_digest"] = obj{"schema": "weekly_digest.v1", "timezone": d.zone.String(), "weeks": weeks}
	}
	if d.op == postEvent || d.op == blockReview {
		event, err := d.eventSection()
		if err != nil {
			return err
		}
		if d.op == postEvent || event != nil {
			out["event"] = event
		}
		if d.op == blockReview {
			out["benchmark_history"] = d.rows("benchmark_history")
		}
	}
	if d.op != calibrate {
		travel, err := d.travelSection()
		if err != nil {
			return err
		}
		out["travel"] = travel
	}
	return nil
}

func (d displayData) eventSection() (obj, error) {
	var day, activity string
	var event obj
	events := d.rows("events")
	if d.op == blockReview {
		status := asObj(d.block()["benchmark_status"])
		if status["status"] != "completed" {
			return nil, nil
		}
		day, activity = str(status["local_date"]), str(status["activity_id"])
		event = index(events, "event_id")[str(status["event_id"])]
	} else {
		due := map[string]bool{}
		for _, f := range d.rows("exception_findings") {
			if f["rule_code"] == "POST_EVENT_REVIEW_DUE" && (f["status"] == "open" || f["status"] == "addressed") {
				due[strings.TrimPrefix(str(f["entity_key"]), "event:")] = true
			}
		}
		for _, e := range events {
			id := str(e["event_id"])
			date := str(e["event_date"])
			if due[id] && (date > day || date == day && id > str(event["event_id"])) {
				day, event = date, e
			}
		}
		if event == nil {
			return nil, nil
		}
	}
	var matched obj
	for _, r := range d.rows("runs") {
		id := str(r["activity_id"])
		if (activity != "" && id != activity) || (activity == "" && r["local_date"] != day) {
			continue
		}
		if matched == nil || number(r["distance_m"]) > number(matched["distance_m"]) || number(r["distance_m"]) == number(matched["distance_m"]) && id > str(matched["id"]) {
			matched = pick(r, "distance_m rpe rpe_source")
			matched["id"], matched["duration_s"], matched["start_local"] = id, r["timer_s"], nil
			if value := str(r["start_at"]); value != "" {
				t, err := time.Parse(time.RFC3339Nano, value)
				if err != nil {
					return nil, err
				}
				layout := "2006-01-02T15:04:05"
				if t.Nanosecond() != 0 {
					layout += ".000000"
				}
				matched["start_local"] = t.In(d.zone).Format(layout + "-07:00")
			}
		}
	}
	if event != nil {
		event = pick(event, eventKeys)
		event["id"] = event["event_id"]
		delete(event, "event_id")
	}
	last := offset(day, 3)
	checkins, nights := records{}, records{}
	for _, c := range d.rows("checkins") {
		if !between(c["local_date"], day, last) {
			continue
		}
		v := pick(c, "observed_at kind fatigue illness gait_change pain_reported")
		symptoms := records{}
		for _, s := range list(c["symptoms"]) {
			side := "None"
			if s["side"] != nil {
				side = str(s["side"])
			}
			symptoms = append(symptoms, obj{"site_key": strings.ToLower(strings.TrimSpace(str(s["site"]))) + "|" + side, "severity": s["severity"], "timing": s["timing"]})
		}
		v["symptoms"] = symptoms
		checkins = append(checkins, v)
	}
	for _, m := range d.rows("metric_results") {
		night, ok := strings.CutPrefix(str(m["subject_key"]), "night:")
		if ok && m["metric_id"] == "recovery_multisignal_summary" && m["subject_type"] == "night" && between(night, offset(day, -1), last) {
			nights = append(nights, pick(m, metricFields))
		}
	}
	return obj{"event": event, "matched_activity": matched, "checkins_after": checkins, "recovery_nights": nights}, nil
}

func (d displayData) aerobicEfficiency() obj {
	out := obj{"interpretation": "descriptive_only", "recent_runs": records{}, "w28": nil, "w84": nil}
	for _, r := range d.rows("metric_results") {
		if r["metric_id"] != "aerobic_efficiency" || r["subject_type"] != "window" {
			continue
		}
		for _, w := range []string{"w28", "w84"} {
			if r["subject_key"] != w+":"+d.day {
				continue
			}
			v := pick(r, metricFields)
			value := obj{}
			maps.Copy(value, asObj(v["value"]))
			points := list(value["points"])
			delete(value, "points")
			v["value"] = value
			out[w] = v
			if w == "w84" {
				out["recent_runs"] = points[max(0, len(points)-5):]
			}
		}
	}
	return out
}

func orderedSessions(rs records) records {
	result := slices.Clone(rs)
	sort.SliceStable(result, func(i, j int) bool {
		a, b := result[i], result[j]
		if a["local_date"] != b["local_date"] {
			return str(a["local_date"]) < str(b["local_date"])
		}
		if a["slot"] != b["slot"] && number(a["slot"]) != number(b["slot"]) {
			return number(a["slot"]) < number(b["slot"])
		}
		return str(a["session_uid"]) < str(b["session_uid"])
	})
	return result
}

func digestView(w obj) obj {
	view := pick(w, "week_start week_end days_elapsed activity_coverage_complete totals decision_follow_up")
	keys, notDone, rehab := records{}, records{}, records{}
	for _, r := range orderedSessions(list(w["sessions"])) {
		if r["kind"] == "rehab" {
			rehab = append(rehab, pick(r, "session_uid local_date slot intent planned_duration_s outcome"))
		}
		if r["key"] == true {
			v := pick(r, "session_uid local_date class recipe_id changed outcome modification_reason planned_duration_s planned_distance_m")
			a := asObj(r["actual"])
			e := asObj(r["execution"])
			v["actual_duration_s"], v["actual_distance_m"], v["activity_id"] = a["duration_s"], a["distance_m"], nil
			if a["subject"] == "activity" {
				v["activity_id"] = a["id"]
			}
			maps.Copy(v, pick(a, "sport avg_hr_bpm moving_pace_s_per_km rpe"))
			maps.Copy(v, pick(e, "assessment_status reps_planned reps_completed"))
			for _, k := range []string{"reason_codes", "quality_flags", "components"} {
				v[k] = e[k]
				if v[k] == nil {
					v[k] = []any{}
				}
			}
			keys = append(keys, v)
		} else if (r["kind"] == "run" || r["kind"] == "strength" || r["kind"] == "cross") && (r["outcome"] == "missed" || r["outcome"] == "not_recorded") {
			notDone = append(notDone, pick(r, "session_uid local_date kind class outcome"))
		}
	}
	view["rehab_sessions"] = rehab
	unplanned := list(w["unplanned"])
	sortKeys(unplanned, "local_date", "id")
	for _, part := range []struct {
		name  string
		rows  records
		limit int
	}{{"key_sessions", keys, 4}, {"not_done", notDone, 6}, {"unplanned", unplanned, 4}} {
		omitted := max(0, len(part.rows)-part.limit)
		view[part.name] = part.rows[omitted:]
		view[part.name+"_omitted"] = omitted
	}
	return view
}

func workSig(structure any) (string, error) {
	if structure == nil {
		return "", nil
	}
	if a, ok := structure.([]any); ok && len(a) == 0 {
		return "", nil
	}
	raw, err := json.Marshal(structure)
	if err != nil {
		return "", err
	}
	steps, ok := calendarstructure.Expand(raw)
	if !ok {
		return "", errors.New("invalid workout structure")
	}
	var groups []string
	last, count := "", 0
	for _, step := range steps {
		if step.Type != "work" {
			continue
		}
		unit, scale := "t", 5.
		if step.DurationType == "distance" {
			unit, scale = "d", 10
		}
		tok := unit + strconv.FormatFloat(scale*math.RoundToEven(step.DurationValue/scale), 'f', 0, 64)
		if tok != last && count > 0 {
			groups = append(groups, fmt.Sprintf("%dx%s", count, last))
			count = 0
		}
		last = tok
		count++
	}
	if count == 0 {
		return "", nil
	}
	groups = append(groups, fmt.Sprintf("%dx%s", count, last))
	return "ws1:" + strings.Join(groups, "+"), nil
}

func rounded(n float64, places int) float64 {
	v, _ := strconv.ParseFloat(strconv.FormatFloat(n, 'f', places, 64), 64)
	return v
}

func intervalPoint(session, run, metric obj) obj {
	value := asObj(metric["value"])
	if run == nil || value == nil {
		return nil
	}
	point := pick(value, "n_planned n_completed cv_speed last_first_change_pct target_coverage")
	point["local_date"], point["sport"], point["activity_id"], point["session_uid"] = run["local_date"], run["sport"], run["activity_id"], session["session_uid"]
	point["work_speed_mps"], point["work_hr_bpm"], point["work_m_per_beat"] = nil, nil, nil
	var weight, speed, hrWeight, hrSum, hrSpeed float64
	used := 0
	for _, rep := range list(value["reps"]) {
		t := number(rep["actual_timer_s"])
		if rep["fully_completed"] != true || rep["speed_status"] != "available" || rep["mean_speed_mps"] == nil || t <= 0 {
			continue
		}
		used++
		weight += t
		speed += t * number(rep["mean_speed_mps"])
		if rep["hr_median_bpm"] != nil {
			hrWeight += t
			hrSum += t * number(rep["hr_median_bpm"])
			hrSpeed += t * number(rep["mean_speed_mps"])
		}
	}
	if weight > 0 {
		point["work_speed_mps"] = rounded(speed/weight, 3)
	}
	if hrWeight > 0 {
		point["work_hr_bpm"] = rounded(hrSum/hrWeight, 1)
		if hrSum != 0 {
			point["work_m_per_beat"] = rounded(60*(hrSpeed/hrWeight)/(hrSum/hrWeight), 3)
		}
	}
	reasons := map[string]bool{}
	if a, ok := metric["reason_codes"].([]any); ok {
		for _, v := range a {
			reasons[str(v)] = true
		}
	}
	if used < int(number(value["n_completed"])) {
		reasons["REPS_EXCLUDED"] = true
	}
	codes := []string{}
	for r := range reasons {
		codes = append(codes, r)
	}
	slices.Sort(codes)
	point["reason_codes"] = codes
	point["status"] = "partial"
	if metric["status"] == "available" && used == int(number(value["n_planned"])) {
		point["status"] = "available"
	}
	return point
}

func (d displayData) qualityProgression() (records, error) {
	rows := orderedSessions(d.rows("sessions"))
	start, end := d.window("calendar")
	wanted := []string{}
	sigs := map[string]string{}
	for _, s := range rows {
		if s["kind"] != "run" {
			continue
		}
		sig, err := workSig(s["structure"])
		if err != nil {
			return nil, err
		}
		sigs[str(s["session_uid"])] = sig
		if sig != "" && len(wanted) < 3 && between(s["local_date"], start, end) && !slices.Contains(wanted, sig) {
			wanted = append(wanted, sig)
		}
	}
	completions := index(d.rows("completions"), "session_uid")
	runs := index(d.rows("runs"), "activity_id")
	executions := map[string]obj{}
	for _, m := range d.rows("metric_results") {
		if m["metric_id"] == "work_interval_execution" {
			executions[str(m["subject_key"])] = m
		}
	}
	result := records{}
	for _, sig := range wanted {
		total := 0
		points := records{}
		recipes := []string{}
		for _, s := range rows {
			id := str(s["session_uid"])
			if sigs[id] != sig || str(s["local_date"]) > d.day {
				continue
			}
			total++
			if recipe := str(s["recipe_id"]); recipe != "" && !slices.Contains(recipes, recipe) {
				recipes = append(recipes, recipe)
			}
			aid := str(completions[id]["activity_id"])
			if p := intervalPoint(s, runs[aid], executions[aid]); p != nil {
				points = append(points, p)
			}
		}
		if total == 0 {
			continue
		}
		sortKeys(points, "local_date", "session_uid")
		for _, p := range points {
			delete(p, "session_uid")
		}
		slices.Sort(recipes)
		result = append(result, obj{"signature": sig, "recipe_ids": recipes, "sessions_total": total, "sessions_assessable": len(points), "recent": points[max(0, len(points)-4):]})
	}
	return result, nil
}

func (d displayData) travelSection() (obj, error) {
	meta := asObj(d.src["travel_meta"])
	homeName := str(meta["home_timezone"])
	if homeName == "" {
		homeName = d.zone.String()
	}
	home, err := time.LoadLocation(homeName)
	if err != nil {
		return nil, err
	}
	trips := d.rows("trips")
	sortKeys(trips, "start_date", "trip_id")
	out := records{}
	for _, t := range trips[:min(8, len(trips))] {
		v, err := tripSummary(t, home)
		if err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return obj{"home_timezone": homeName, "calendar_synced_at": meta["calendar_synced_at"], "trips": out, "trips_omitted": len(trips) - len(out)}, nil
}

func tripSummary(t obj, home *time.Location) (obj, error) {
	v := maps.Clone(t)
	legs := list(t["legs"])
	known := len(legs) > 0
	views := records{}
	for _, leg := range legs {
		view, err := legSummary(leg)
		if err != nil {
			return nil, err
		}
		views = append(views, view)
		known = known && leg["timezone_basis"] == "calendar_endpoints"
	}
	v["legs"] = views
	v["zone_shift_hours"], v["direction"], v["nights_away"] = nil, nil, nil
	start := str(t["start_date"])
	if end := str(t["end_date"]); end != "" {
		v["nights_away"] = days(start, end)
	}
	if known || t["confirmed"] == true || t["source"] == "manual" {
		date, err := time.ParseInLocation(time.DateOnly, start, home)
		if err != nil {
			return nil, err
		}
		noon := time.Date(date.Year(), date.Month(), date.Day(), 12, 0, 0, 0, home)
		dest, err := time.LoadLocation(str(t["destination_timezone"]))
		if err != nil {
			return nil, err
		}
		_, before := noon.Zone()
		_, after := noon.In(dest).Zone()
		shift := float64(after-before) / 3600
		if shift > 12 {
			shift -= 24
		} else if shift <= -12 {
			shift += 24
		}
		direction := "none"
		if shift > 0 {
			direction = "east"
		} else if shift < 0 {
			direction = "west"
		}
		v["zone_shift_hours"], v["direction"] = shift, direction
	}
	return v, nil
}

func civilTime(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), t.Hour(), t.Minute(), t.Second(), t.Nanosecond(), time.UTC)
}

func legSummary(leg obj) (obj, error) {
	dep, err := time.Parse(time.RFC3339Nano, str(leg["depart_local"]))
	if err != nil {
		return nil, err
	}
	arr, err := time.Parse(time.RFC3339Nano, str(leg["arrive_local"]))
	if err != nil {
		return nil, err
	}
	out := maps.Clone(leg)
	out["duration_hours"] = math.Floor(arr.Sub(dep).Hours()*2+0.5) / 2
	out["zone_shift_hours"], out["night_overlap"] = nil, nil
	if leg["timezone_basis"] == "calendar_endpoints" {
		_, a := dep.Zone()
		_, b := arr.Zone()
		out["zone_shift_hours"] = float64(b-a) / 3600
		zone, err := time.LoadLocation(str(leg["depart_timezone"]))
		if err != nil {
			return nil, err
		}
		start, end := civilTime(dep.In(zone)), civilTime(arr.In(zone))
		first := time.Date(start.Year(), start.Month(), start.Day()-1, 23, 0, 0, 0, time.UTC)
		overlap := false
		for night := first; night.Before(end); night = night.AddDate(0, 0, 1) {
			if start.Before(night.Add(7 * time.Hour)) {
				overlap = true
				break
			}
		}
		out["night_overlap"] = overlap
	}
	return out, nil
}
