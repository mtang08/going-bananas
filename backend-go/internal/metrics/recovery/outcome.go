// Package recovery computes the separate nightly recovery signals and their seven-day coverage.
package recovery

import (
	"encoding/json"
	"math"
	"slices"
	"strconv"
	"time"
)

var signals = []string{"sleep", "hrv", "resting_hr"}

type observation struct {
	day               time.Time
	metric, partition string
	value             *float64
	resolved          bool
	refs              map[string]any
}
type checkin struct {
	day     string
	fatigue *float64
	illness *string
	refs    map[string]any
}
type outcome struct {
	status         string
	quality        *string
	reasons, flags []string
	value          map[string]any
}

func valid(metric string, v *float64) bool {
	if v == nil || math.IsNaN(*v) || math.IsInf(*v, 0) {
		return false
	}
	switch metric {
	case "sleep":
		return *v > 0 && *v <= 86400
	case "resting_hr":
		return *v >= 30 && *v <= 230
	default:
		return *v > 0
	}
}
func median(v []float64) float64 {
	slices.Sort(v)
	mid := len(v) / 2
	if len(v)%2 != 0 {
		return v[mid]
	}
	return (v[mid] + v[mid-1]) / 2
}
func round(v float64, digits int) float64 {
	s := strconv.FormatFloat(v, 'f', digits, 64)
	n, _ := strconv.ParseFloat(s, 64)
	return n
}
func signal(metric string, day time.Time, observations []observation) map[string]any {
	result := map[string]any{"status": "missing", "value": nil, "baseline_state": "none", "valid_nights": 0, "invalid_history_nights": 0, "z": nil, "adverse": nil, "baseline_median": nil, "baseline_mad": nil, "deviation": nil, "reason_codes": []string{}, "quality_flags": []string{}, "partition": nil}
	var current *observation
	for i := range observations {
		if observations[i].metric == metric && observations[i].day.Equal(day) {
			current = &observations[i]
		}
	}
	if current == nil {
		result["reason_codes"] = []string{"RECOVERY_MISSING"}
		return result
	}
	result["partition"] = current.partition
	if !current.resolved {
		result["status"] = "invalid"
		result["reason_codes"] = []string{"RECOVERY_UNRESOLVED"}
		return result
	}
	if current.value == nil {
		result["reason_codes"] = []string{"RECOVERY_MISSING"}
		return result
	}
	if !valid(metric, current.value) {
		result["status"] = "invalid"
		result["reason_codes"] = []string{"RECOVERY_VALUE_INVALID"}
		return result
	}
	result["value"] = round(*current.value, 1)
	flags := []string{}
	var p map[string]any
	if (json.Unmarshal([]byte(current.partition), &p) == nil && p["device_generation"] == "unknown") || current.partition == "unknown" {
		flags = append(flags, "SOURCE_DEVICE_UNKNOWN")
	}
	latest := map[time.Time]observation{}
	invalid := map[time.Time]bool{}
	for _, o := range observations {
		if o.metric != metric || o.partition != current.partition || o.day.Before(day.AddDate(0, 0, -60)) || !o.day.Before(day) {
			continue
		}
		if o.resolved {
			latest[o.day] = o
		} else {
			invalid[o.day] = true
		}
	}
	transform := func(v float64) float64 {
		if metric == "hrv" {
			return math.Log(v)
		}
		return v
	}
	var values []float64
	fresh := 0
	for _, o := range latest {
		if valid(metric, o.value) {
			values = append(values, transform(*o.value))
			if !o.day.Before(day.AddDate(0, 0, -14)) {
				fresh++
			}
		} else {
			invalid[o.day] = true
		}
	}
	result["invalid_history_nights"] = len(invalid)
	result["valid_nights"] = len(values)
	if len(values) >= 28 {
		result["baseline_state"] = "established"
	} else if len(values) >= 14 {
		result["baseline_state"] = "provisional"
	}
	if fresh < 7 {
		flags = append(flags, "BASELINE_STALE")
	}
	result["quality_flags"] = flags
	var spread, deviation float64
	if len(values) > 0 {
		center := median(values)
		for i, v := range values {
			values[i] = math.Abs(v - center)
		}
		spread = median(values)
		deviation = transform(*current.value) - center
		digits := 1
		if metric == "hrv" {
			digits = 3
		}
		result["baseline_median"] = round(center, digits)
		result["baseline_mad"] = round(spread, digits)
		result["deviation"] = round(deviation, digits)
	}
	switch {
	case len(values) < 14:
		result["status"] = "partial"
		result["reason_codes"] = []string{"BASELINE_INSUFFICIENT"}
	case spread == 0:
		result["status"] = "partial"
		result["reason_codes"] = []string{"MAD_ZERO"}
	default:
		z := 0.6745 * deviation / spread
		result["status"] = "available"
		result["z"] = round(z, 2)
		result["adverse"] = (metric == "resting_hr" && z >= 1.5) || (metric != "resting_hr" && z <= -1.5)
	}
	return result
}
func anyThree(values []any) any {
	unknown := false
	for _, v := range values {
		if v == true {
			return true
		}
		if v == nil {
			unknown = true
		}
	}
	if unknown {
		return nil
	}
	return false
}
func sortedSet(v []string) []string { slices.Sort(v); return slices.Compact(v) }
func ptr[T any](v T) *T             { return &v }
func night(day time.Time, obs []observation, checks []checkin) outcome {
	d := day.Format(time.DateOnly)
	out := outcome{value: map[string]any{"local_date": d}, flags: []string{}, reasons: []string{}}
	var fatigue *float64
	var illness *string
	for _, c := range checks {
		if c.day != d {
			continue
		}
		if c.fatigue != nil {
			fatigue = c.fatigue
		}
		if c.illness != nil {
			illness = c.illness
		}
	}
	var fatiguePoor, illnessPoor any
	if fatigue != nil {
		fatiguePoor = *fatigue >= 7
	}
	if illness != nil {
		illnessPoor = *illness == "possible" || *illness == "present"
	}
	subjective := anyThree([]any{fatiguePoor, illnessPoor})
	var adverse []any
	var missing, available int
	for _, m := range signals {
		s := signal(m, day, obs)
		out.value[m] = s
		adverse = append(adverse, s["adverse"])
		if s["status"] == "missing" {
			missing++
		}
		if s["status"] == "available" {
			available++
		}
		out.flags = append(out.flags, s["quality_flags"].([]string)...)
		out.reasons = append(out.reasons, s["reason_codes"].([]string)...)
	}
	phys := anyThree(adverse)
	var discord any
	if phys != nil && subjective != nil {
		discord = phys != subjective
	}
	out.value["subjective_poor"] = subjective
	out.value["discordance"] = discord
	out.value["fatigue"] = fatigue
	out.value["illness"] = illness
	out.flags = sortedSet(out.flags)
	out.reasons = sortedSet(out.reasons)
	switch {
	case missing == 3 && subjective == nil:
		out.status = "missing"
	case available < 3:
		out.status = "partial"
		out.quality = ptr("limited")
	default:
		out.status = "available"
		out.quality = ptr("good")
		if len(out.flags) > 0 {
			out.quality = ptr("limited")
		}
	}
	return out
}
func week(nights []outcome) outcome {
	out := outcome{flags: []string{}, reasons: []string{}}
	missing := []string{}
	for _, n := range nights {
		has := false
		for _, m := range signals {
			if n.value[m].(map[string]any)["value"] != nil {
				has = true
			}
		}
		if !has {
			missing = append(missing, n.value["local_date"].(string))
		}
		out.flags = append(out.flags, n.flags...)
	}
	count := 7 - len(missing)
	out.flags = sortedSet(out.flags)
	out.status = "available"
	out.quality = ptr("good")
	if count < 7 {
		out.reasons = []string{"RECOVERY_NIGHTS_MISSING"}
		out.status = "partial"
		out.quality = ptr("limited")
	}
	if count < 5 {
		out.quality = ptr("insufficient")
	}
	if count == 0 {
		out.status = "missing"
	}
	out.value = map[string]any{"nights_total": 7, "nights_with_data": count, "missing_dates": missing, "coverage": round(float64(count)/7, 3)}
	return out
}
