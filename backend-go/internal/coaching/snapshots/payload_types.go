package snapshots

import (
	"bytes"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/snapshotreads"
)

type obj = map[string]any
type records = []map[string]any

const (
	daily       = "proceed_or_modify_today"
	rolling     = "review_rolling_plan"
	quality     = "select_quality_session"
	blockReview = "review_training_block"
	calibrate   = "recalibrate_intensity"
	race        = "handle_goal_or_race_change"
	exception   = "exception_review"
	postEvent   = "post_event_review"
)

// displayData is the wire projection of SnapshotInputs. Decode once so nested
// records from PostgreSQL JSON and typed source reads have the same shape.
type displayData struct {
	src  obj
	day  string
	now  time.Time
	zone *time.Location
	op   string
}

func display(in snapshotreads.Inputs, op string) (displayData, error) {
	raw, err := json.Marshal(in)
	if err != nil {
		return displayData{}, err
	}
	var src obj
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err = decoder.Decode(&src); err != nil {
		return displayData{}, err
	}
	// encoding/json renders integral binary64 values without their decimal. Keep
	// their Python identity throughout the dynamic records used in the payload hash.
	numeric, err := canonicaljson.Coaching(obj{
		"runs": in.Runs, "metric_results": in.MetricResults, "coverage": in.Coverage,
		"checkins": in.Checkins, "prompts": in.Prompts, "weekly_digest": in.WeeklyDigest,
		"exception_findings": in.Findings, "exception_patches": in.Patches, "review_recommended": in.Recommendations,
		"running_interruption": in.RunningInterruption, "confirmed_strength_sessions": in.ConfirmedStrengthSessions,
		"accepted_strength_omissions": in.AcceptedStrengthOmissions, "trips": in.Trips, "travel_meta": in.Meta,
	})
	if err != nil {
		return displayData{}, err
	}
	decoder = json.NewDecoder(bytes.NewReader(numeric))
	decoder.UseNumber()
	if err := decoder.Decode(&src); err != nil {
		return displayData{}, err
	}
	now, err := time.Parse(time.RFC3339Nano, in.Now)
	if err != nil {
		return displayData{}, err
	}
	zone, err := time.LoadLocation(in.Timezone)
	return displayData{src: src, day: in.AsOf, now: now, zone: zone, op: op}, err
}

func asObj(v any) obj { r, _ := v.(map[string]any); return r }
func list(v any) records {
	if r, ok := v.(records); ok {
		return r
	}
	a, _ := v.([]any)
	r := make(records, 0, len(a))
	for _, el := range a {
		if row := asObj(el); row != nil {
			r = append(r, row)
		}
	}
	return r
}
func str(v any) string { s, _ := v.(string); return s }
func number(v any) float64 {
	switch x := v.(type) {
	case json.Number:
		f, _ := x.Float64()
		return f
	case float64:
		return x
	case int:
		return float64(x)
	}
	return 0
}
func pick(r obj, keys string) obj {
	o := obj{}
	for _, k := range strings.Fields(keys) {
		o[k] = r[k]
	}
	return o
}
func between(v any, a, b string) bool { s := str(v); return s != "" && s >= a && s <= b }
func offset(day string, n int) string {
	d, err := time.Parse(time.DateOnly, day)
	if err != nil {
		return ""
	}
	return d.AddDate(0, 0, n).Format(time.DateOnly)
}
func days(a, b string) int {
	l, _ := time.Parse(time.DateOnly, a)
	r, _ := time.Parse(time.DateOnly, b)
	return int(r.Sub(l).Hours() / 24)
}
func index(rs records, key string) map[string]obj {
	o := map[string]obj{}
	for _, r := range rs {
		if s := str(r[key]); s != "" {
			o[s] = r
		}
	}
	return o
}
func (d displayData) rows(key string) records { return list(d.src[key]) }
func (d displayData) block() obj              { return asObj(d.src["active_block"]) }
func (d displayData) horizon() bool           { return d.op == rolling || d.op == race || d.op == blockReview }
func (d displayData) scopeEnd() string {
	switch d.op {
	case race, blockReview:
		return offset(d.day, 42)
	case rolling:
		n := 13
		if end := str(d.block()["review_date"]); end != "" {
			n = min(42, max(13, days(d.day, end)))
		}
		return offset(d.day, n)
	case daily:
		return offset(d.day, 3)
	case exception, postEvent:
		return offset(d.day, 6)
	}
	return offset(d.day, 13)
}
func (d displayData) window(section string) (string, string) {
	start, end := d.day, d.day
	switch section {
	case "calendar":
		switch d.op {
		case race:
			end = offset(end, 42)
		case postEvent:
			end = offset(end, 13)
		case exception:
			start, end = offset(start, -7), offset(end, 6)
		default:
			start = offset(start, -map[string]int{daily: 3, rolling: 14, quality: 14, blockReview: 28}[d.op])
			end = d.scopeEnd()
		}
	case "symptoms":
		n := 28
		if d.op == daily || d.op == exception {
			n = 14
		}
		start = offset(start, 1-n)
		if d.op == blockReview && d.block() != nil {
			start = str(d.block()["start_date"])
		}
	case "exposures", "recovery":
		n := map[string]int{daily: 3, rolling: 14, quality: 14, blockReview: 28, race: 14, calibrate: 84, exception: 3, postEvent: 14}[d.op]
		start = offset(start, 1-n)
	}
	return start, end
}
func sortKeys(rs records, keys ...string) {
	sort.SliceStable(rs, func(i, j int) bool {
		for _, k := range keys {
			a, b := fmt.Sprint(rs[i][k]), fmt.Sprint(rs[j][k])
			if a != b {
				return a < b
			}
		}
		return false
	})
}

func chronologicalSessions(rs records) records {
	sort.SliceStable(rs, func(i, j int) bool {
		a, b := rs[i], rs[j]
		if a["local_date"] != b["local_date"] {
			return str(a["local_date"]) < str(b["local_date"])
		}
		if number(a["slot"]) != number(b["slot"]) {
			return number(a["slot"]) < number(b["slot"])
		}
		return str(a["session_uid"]) < str(b["session_uid"])
	})
	return rs
}
