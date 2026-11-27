package weeklydigest

import "strings"

func tally(group map[string]int, due, done bool) {
	group["planned"]++
	if due {
		group["planned_to_date"]++
	}
	if done {
		group["done"]++
	}
}
func counts() map[string]int { return map[string]int{"planned": 0, "planned_to_date": 0, "done": 0} }
func outcomes() map[string]int {
	return map[string]int{"completed": 0, "modified": 0, "partial": 0, "moved": 0, "missed": 0, "recorded": 0, "not_recorded": 0, "planned": 0}
}
func withOutcomes(c, o map[string]int) row {
	return row{"planned": c["planned"], "planned_to_date": c["planned_to_date"], "done": c["done"], "by_outcome": o}
}
func headline(kind any) bool { return kind == "run" || kind == "strength" || kind == "cross" }

func sum(group map[string]float64, k string, v any) {
	if n := num(v); n != nil {
		group[k] += *n
	}
}
func totals(rows, planned, inWeek, unplanned, removed []row, today string) row {
	kinds := map[string]map[string]int{}
	for _, k := range []string{"run", "strength", "cross", "mobility", "rehab"} {
		kinds[k] = counts()
	}
	sessions, keys := counts(), counts()
	out, keyOut := outcomes(), outcomes()
	t := map[string]float64{"planned_s": 0, "planned_to_date_s": 0, "planned_unknown": 0, "actual_s": 0, "actual_unknown": 0, "unplanned_s": 0}
	d := map[string]float64{"planned_m": 0, "planned_to_date_m": 0, "planned_estimated": 0, "planned_unknown": 0, "actual_m": 0, "actual_unknown": 0}
	methods := map[any]any{}
	for _, s := range planned {
		methods[s["session_uid"]] = s["match_method"]
	}
	for _, s := range rows {
		kind := s["kind"].(string)
		o := s["outcome"].(string)
		due := s["local_date"].(string) <= today
		done := o == "completed" || o == "modified" || o == "recorded" || o == "partial" || o == "moved"
		if group := kinds[kind]; group != nil {
			tally(group, due, done)
		}
		if s["key"] == true {
			tally(keys, due, done)
			keyOut[o]++
		}
		if !headline(kind) {
			continue
		}
		tally(sessions, due, done)
		out[o]++
		sum(t, "planned_s", s["planned_duration_s"])
		if due {
			sum(t, "planned_to_date_s", s["planned_duration_s"])
		}
		if s["planned_duration_s"] == nil {
			t["planned_unknown"]++
		}
		self := o == "completed" && methods[s["session_uid"]] == "user_marked"
		if self {
			t["actual_unknown"]++
		}
		if kind != "run" {
			continue
		}
		sum(d, "planned_m", s["planned_distance_m"])
		if due {
			sum(d, "planned_to_date_m", s["planned_distance_m"])
		}
		if s["planned_distance_estimated"] == true {
			d["planned_estimated"]++
		}
		if s["planned_distance_m"] == nil {
			d["planned_unknown"]++
		}
		if self {
			d["actual_unknown"]++
		}
	}
	for _, s := range inWeek {
		sum(t, "actual_s", s["duration_s"])
		if s["duration_s"] == nil {
			t["actual_unknown"]++
		}
		if s["kind"] == "run" {
			sum(d, "actual_m", s["distance_m"])
			if s["distance_m"] == nil {
				d["actual_unknown"]++
			}
		}
	}
	for _, s := range unplanned {
		sum(t, "unplanned_s", s["duration_s"])
	}
	g := withOutcomes(sessions, out)
	n := 0
	for _, s := range removed {
		if headline(s["kind"]) {
			n++
		}
	}
	g["removed"], g["unplanned"] = n, len(unplanned)
	return row{"sessions": g, "by_kind": kinds, "time": measuredTotals(t), "run_distance": measuredTotals(d), "key_sessions": withOutcomes(keys, keyOut)}
}

// Python's sum starts at integer zero. A missing or zero measurement also
// contributes integer zero, while positive measurements yield floating totals.
func measuredTotals(amounts map[string]float64) row {
	result := row{}
	for k, v := range amounts {
		if v != 0 && (strings.HasSuffix(k, "_s") || strings.HasSuffix(k, "_m")) {
			result[k] = rounded(v)
		} else {
			result[k] = int(v)
		}
	}
	return result
}
