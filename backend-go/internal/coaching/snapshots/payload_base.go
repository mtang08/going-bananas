package snapshots

import (
	"errors"
	"maps"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/coaching/snapshotreads"
)

func project(rs records, keys string) records {
	out := make(records, 0, len(rs))
	for _, r := range rs {
		out = append(out, pick(r, keys))
	}
	return out
}
func inWindow(rs records, key, start, end string) records {
	out := records{}
	for _, r := range rs {
		if between(r[key], start, end) {
			out = append(out, r)
		}
	}
	return out
}

func (d displayData) exposures() obj {
	start, end := d.window("exposures")
	cs, ss := d.rows("completions"), index(d.rows("sessions"), "session_uid")
	byA, byL := index(cs, "activity_id"), index(cs, "strong_workout_id")
	runs := records{}
	for _, row := range inWindow(d.rows("runs"), "local_date", start, end) {
		c := byA[str(row["activity_id"])]
		s := ss[str(c["session_uid"])]
		recipe := str(s["recipe_id"])
		if d.op == calibrate && !slices.Contains([]string{"REC003", "REC004", "REC005", "REC009"}, recipe) {
			continue
		}
		r := pick(row, "activity_id local_date sport timer_s distance_m rpe rpe_source")
		r["session_uid"], r["planned_recipe_id"], r["completion_status"] = c["session_uid"], s["recipe_id"], c["status"]
		switch recipe {
		case "":
			r["class"] = "unplanned"
		case "REC002":
			r["class"] = "long"
		case "REC003", "REC004", "REC005", "REC006", "REC008", "REC009":
			r["class"] = "quality"
		default:
			r["class"] = "easy"
		}
		runs = append(runs, r)
	}
	sortKeys(runs, "local_date", "activity_id")
	out := obj{"runs": runs, "window_days": days(start, end) + 1}
	if d.op == calibrate {
		return out
	}
	lifts := records{}
	for _, row := range inWindow(d.rows("strong_workouts"), "local_date", start, end) {
		r := pick(row, "strong_workout_id local_date workout_name duration_s rpe")
		r["source"], r["session_uid"] = "strong", byL[str(row["strong_workout_id"])]["session_uid"]
		lifts = append(lifts, r)
	}
	for _, c := range cs {
		s := ss[str(c["session_uid"])]
		if s["kind"] == "strength" && between(s["local_date"], start, end) && c["match_method"] == "user_marked" && c["status"] == "completed_as_planned" && c["strong_workout_id"] == nil && c["activity_id"] == nil && c["manual_session_id"] == nil {
			lifts = append(lifts, obj{"source": "self_reported", "session_uid": s["session_uid"], "strong_workout_id": nil, "local_date": s["local_date"], "workout_name": nil, "duration_s": nil, "rpe": nil})
		}
	}
	slots := index(d.rows("strength_slots"), "slot_id")
	for _, l := range lifts {
		slotID := ss[str(l["session_uid"])]["strength_slot_id"]
		s := slots[str(slotID)]
		l["strength_slot_id"], l["planned_slot_label"], l["planned_lower_body_cost"] = slotID, s["label"], s["lower_body_cost"]
	}
	sort.SliceStable(lifts, func(i, j int) bool {
		key := func(r obj) string {
			id := str(r["strong_workout_id"])
			if id == "" {
				id = str(r["session_uid"])
			}
			return str(r["local_date"]) + id
		}
		return key(lifts[i]) < key(lifts[j])
	})
	out["lifts"] = lifts
	return out
}

func (d displayData) safety() obj {
	g := obj{"window_hours": 72, "gait_change_yes": false, "illness_present": false, "max_symptom_severity": nil, "clinical_restriction_active": strings.TrimSpace(str(d.src["clinical_restriction"])) != ""}
	for _, c := range d.rows("checkins") {
		t, err := time.Parse(time.RFC3339Nano, str(c["observed_at"]))
		if err != nil || t.Before(d.now.Add(-72*time.Hour)) || t.After(d.now) {
			continue
		}
		if c["gait_change"] == "yes" {
			g["gait_change_yes"] = true
		}
		if c["illness"] == "present" {
			g["illness_present"] = true
		}
		for _, s := range list(c["symptoms"]) {
			v := s["severity"]
			if v != nil && (g["max_symptom_severity"] == nil || number(v) > number(g["max_symptom_severity"])) {
				g["max_symptom_severity"] = number(v)
			}
		}
	}
	return g
}

func (d displayData) dataQuality() obj {
	flags := []string{}
	datasets := obj{}
	for _, name := range []string{"activities", "sleep", "hrv", "resting_hr"} {
		fresh := ""
		for _, r := range d.rows("coverage") {
			if r["dataset"] == name && r["status"] == "complete" {
				fresh = max(fresh, str(r["end_date"]))
			}
		}
		var through any
		status := "missing"
		if fresh != "" {
			through = fresh
			status = "fresh"
			if fresh < offset(d.day, -2) {
				status = "stale"
			}
		}
		datasets[name] = obj{"status": status, "fresh_through": through}
		if status != "fresh" {
			flags = append(flags, name+"_"+status)
		}
	}
	if !slices.ContainsFunc(d.rows("anchors"), func(r obj) bool { return r["status"] == "active" }) {
		flags = append(flags, "no_intensity_anchor")
	}
	if d.block() == nil {
		flags = append(flags, "no_active_block")
	}
	slices.Sort(flags)
	return obj{"datasets": datasets, "flags": flags}
}

func (d displayData) symptoms() obj {
	start, end := d.window("symptoms")
	reports, mornings, delayed := records{}, records{}, records{}
	responses := map[string]obj{}
	order := []string{}
	for _, c := range inWindow(d.rows("checkins"), "local_date", start, end) {
		id := str(c["activity_id"])
		if id != "" && c["kind"] == "delayed_followup" {
			if _, ok := responses[id]; !ok {
				order = append(order, id)
			}
			responses[id] = pick(c, "checkin_id observed_at recorded_at hours_after_end pain_reported gait_change")
		}
		for _, s := range list(c["symptoms"]) {
			r := pick(c, "checkin_id observed_at local_date kind activity_id")
			maps.Copy(r, pick(s, "site side severity timing"))
			reports = append(reports, r)
		}
		if m := asObj(c["morning_ankle"]); len(m) > 0 {
			r := pick(c, "checkin_id observed_at local_date")
			maps.Copy(r, m)
			mornings = append(mornings, r)
		}
	}
	sortKeys(reports, "observed_at", "checkin_id", "site", "timing")
	for _, p := range d.rows("prompts") {
		if p["kind"] != "delayed_symptom" {
			continue
		}
		id := str(p["activity_id"])
		t, _ := time.Parse(time.RFC3339Nano, str(p["opens_at"]))
		if responses[id] == nil && !between(t.In(d.zone).Format(time.DateOnly), start, end) {
			continue
		}
		r := pick(p, "prompt_id kind activity_id status opens_at closes_at")
		r["response"] = responses[id]
		delete(responses, id)
		delayed = append(delayed, r)
	}
	for _, id := range order {
		if r := responses[id]; r != nil {
			delayed = append(delayed, obj{"activity_id": id, "response": r})
		}
	}
	out := obj{"window_days": days(start, end) + 1, "reports": reports, "delayed_responses": delayed}
	if len(mornings) > 0 {
		out["morning_first_step_ankle"] = mornings
	}
	return out
}

const eventKeys = "event_id name event_date distance_m purpose goal_time_s goal_pace_s_per_km rank status result_s"

func (d displayData) goals() obj {
	slots := records{}
	for _, s := range d.rows("strength_slots") {
		if s["active"] != false {
			slots = append(slots, pick(s, "slot_id label default_weekday lower_body_cost typical_duration_s main_lower_body_lifts"))
		}
	}
	lifts := d.rows("strong_workouts")
	sort.SliceStable(lifts, func(i, j int) bool { return str(lifts[i]["local_date"]) > str(lifts[j]["local_date"]) })
	out := obj{"strength_routine": slots, "latest_strong_sessions": project(lifts[:min(len(lifts), 2)], "local_date workout_name duration_s"),
		"run_cycle": obj{"anchor_date": d.src["cycle_anchor"], "confirmed": d.src["anchor_confirmed"]}, "clinical_restriction": d.src["clinical_restriction"]}
	if d.horizon() || len(d.rows("accepted_strength_omissions")) > 0 {
		for _, k := range []string{"accepted_strength_omissions", "confirmed_strength_sessions"} {
			out[k] = inWindow(d.rows(k), "local_date", d.day, d.scopeEnd())
		}
	}
	if d.op != daily && d.op != exception {
		out["goals"] = project(d.rows("goals"), "goal_id text horizon priority status")
		out["events"] = project(d.rows("events"), eventKeys)
		out["goal_race"] = nil
		for _, e := range d.rows("events") {
			if number(e["rank"]) == 1 {
				out["goal_race"] = obj{"event_id": e["event_id"], "days_until": days(d.day, str(e["event_date"]))}
				break
			}
		}
	}
	return out
}

func (d displayData) calendar() obj {
	start, end := d.window("calendar")
	cs := index(d.rows("completions"), "session_uid")
	out := records{}
	for _, s := range chronologicalSessions(inWindow(d.rows("sessions"), "local_date", start, end)) {
		c := cs[str(s["session_uid"])]
		r := pick(s, "session_uid revision local_date slot kind recipe_id custom placeholder intent certainty planned_duration_s planned_distance_m structure strength_slot_id brief")
		if s["locked"] == true {
			r["locked"] = true
		}
		r["is_original"] = number(s["revision"]) == 1
		r["completion_status"], r["modification_reason"] = c["status"], c["modification_reason"]
		if c["match_method"] == "user_marked" && c["status"] == "completed_as_planned" {
			r["self_reported"] = true
		}
		out = append(out, r)
	}
	return obj{"head": d.src["calendar_version"], "start": start, "end": end, "sessions": out}
}

func (d displayData) metricsFor(section string, runs records) records {
	out := records{}
	ids := map[string]bool{}
	for _, r := range runs {
		if r["class"] == "quality" {
			ids[str(r["activity_id"])] = true
		}
	}
	windowSizes := []int{7, 14, 28}
	if d.op == blockReview {
		windowSizes = []int{7, 14, 28, 56, 84}
	} else if d.op == daily || d.op == exception {
		windowSizes = []int{7}
	}
	for _, n := range windowSizes {
		for _, suffix := range []string{"", ":run", ":strength"} {
			ids["w"+strconv.Itoa(n)+":"+d.day+suffix] = true
		}
	}
	start, end := d.window("recovery")
	for _, m := range d.rows("metric_results") {
		key := str(m["subject_key"])
		switch section {
		case "execution":
			if m["metric_id"] != "work_interval_execution" || !ids[key] {
				continue
			}
		case "load_shape":
			if m["subject_type"] != "window" || !ids[key] || m["metric_id"] == "aerobic_efficiency" {
				continue
			}
		case "recovery":
			if m["metric_id"] != "recovery_multisignal_summary" || m["subject_type"] != "night" || !strings.HasPrefix(key, "night:") || !between(strings.TrimPrefix(key, "night:"), start, end) {
				continue
			}
		}
		out = append(out, pick(m, "result_id metric_id method_version subject_type subject_key window_label status quality_status value unit reason_codes quality_flags anchor_keys calculated_at"))
	}
	return out
}

func BuildPayload(in snapshotreads.Inputs, operation string) (map[string]any, error) {
	if !slices.Contains([]string{daily, rolling, quality, blockReview, calibrate, race, exception, postEvent}, operation) {
		return nil, errors.New("unsupported snapshot operation")
	}
	d, err := display(in, operation)
	if err != nil {
		return nil, err
	}
	b := d.block()
	meta := obj{"schema_version": "coach_snapshot.v1", "operation": operation, "as_of": d.day, "timezone": in.Timezone, "calendar_version": in.CalendarVersion,
		"block_version_id": b["version_id"], "data_revision": in.DataRevision, "scope": obj{"start": d.day, "end": d.scopeEnd()}, "safety_guard": d.safety()}
	if v := d.src["running_restriction"]; v != nil {
		meta["running_restriction"] = v
	}
	if d.horizon() {
		rule := "proposed_block_review_date"
		if d.op == rolling {
			rule = "active_block_review_date"
		}
		review := str(b["review_date"])
		meta["horizon"] = obj{"min_end": offset(d.day, 13), "max_end": offset(d.day, 42), "rule": rule, "block_review_due": review != "" && review <= offset(d.day, 7)}
	}
	anchors := records{}
	for _, a := range d.rows("anchors") {
		if operation == blockReview || operation == calibrate || a["status"] == "active" {
			anchors = append(anchors, a)
		}
	}
	exposures := d.exposures()
	out := obj{"snapshot_meta": meta, "completed_exposures": exposures, "anchors": anchors, "data_quality": d.dataQuality(),
		"drill_down_queries": []string{"activity_execution", "long_run_history", "recovery_nights", "calendar_diff", "explain_metric"}}
	if ep := asObj(d.src["running_interruption"]); ep != nil {
		for _, r := range list(ep["affected_runs"]) {
			delete(r, "intent")
		}
		delete(asObj(ep["first_run"]), "intent")
		out["running_interruption"] = ep
	}
	if operation != calibrate {
		out["goals_and_constraints"] = d.goals()
		out["calendar"] = d.calendar()
		out["load_shape"] = d.metricsFor("load_shape", nil)
		out["symptoms"] = d.symptoms()
	}
	out["block"] = b
	if b != nil && (operation == daily || operation == exception) {
		out["block"] = pick(b, "block_uid version_id objective benchmark benchmark_status")
	} else if b != nil && operation == calibrate {
		out["block"] = pick(b, "objective benchmark benchmark_status")
	}
	if operation != race {
		out["execution"] = d.metricsFor("execution", list(exposures["runs"]))
	}
	if operation != race && operation != calibrate {
		out["recovery"] = d.metricsFor("recovery", nil)
	}
	if err := d.addSections(out); err != nil {
		return nil, err
	}
	return strip(out).(obj), nil
}

func strip(v any) any {
	switch x := v.(type) {
	case obj:
		for k, val := range x {
			private := false
			for _, word := range []string{"note", "latitude", "longitude", "gps", "coordinate", "stream", "access_token", "refresh_token", "password", "secret", "vo2max", "training_status", "body_battery", "readiness"} {
				if strings.Contains(strings.ToLower(k), word) {
					private = true
					break
				}
			}
			if private {
				delete(x, k)
			} else {
				x[k] = strip(val)
			}
		}
	case []any:
		for i, val := range x {
			x[i] = strip(val)
		}
	case records:
		for _, r := range x {
			strip(r)
		}
	}
	return v
}
