package snapshots

import (
	"encoding/json"
	"slices"
	"strings"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/snapshotreads"
)

var qualityRecipes = []string{"REC003", "REC004", "REC005", "REC006", "REC008", "REC009"}

func topicDay(s string, days int) string {
	t, _ := time.Parse(time.DateOnly, s)
	return t.AddDate(0, 0, days).Format(time.DateOnly)
}
func stringField(r map[string]any, k string) string { s, _ := r[k].(string); return s }
func anyList(v any) []any                           { r, _ := v.([]any); return r }

func scopeEnd(operation, asOf, review string) string {
	switch operation {
	case "review_rolling_plan", "review_training_block", "handle_goal_or_race_change":
		return max(topicDay(asOf, 13), min(review, topicDay(asOf, 42)))
	case "proceed_or_modify_today":
		return topicDay(asOf, 3)
	case "post_event_review", "exception_review":
		return topicDay(asOf, 6)
	}
	return topicDay(asOf, 13)
}

func recoveryRelevant(v map[string]any) bool {
	if len(anyList(v["flags"])) > 0 || v["discordance"] == true || v["subjective_poor"] == true {
		return true
	}
	for _, name := range []string{"sleep", "hrv", "resting_hr"} {
		s, _ := v[name].(map[string]any)
		if s["adverse"] == true || s["value"] != nil && (len(anyList(s["reason_codes"])) > 0 || len(anyList(s["quality_flags"])) > 0) {
			return true
		}
	}
	return false
}

func numericTarget(s map[string]any) bool {
	for _, item := range anyList(s["structure"]) {
		v, _ := item.(map[string]any)
		steps := []any{v}
		if v["type"] == "repeat" {
			steps = anyList(v["steps"])
		}
		for _, step := range steps {
			q, _ := step.(map[string]any)
			target, _ := q["target"].(map[string]any)
			if target["modality"] == "speed" || target["modality"] == "hr" {
				return true
			}
		}
	}
	return false
}

func symptomTopic(in snapshotreads.Inputs, first string, zone *time.Location) bool {
	for _, c := range in.Checkins {
		d := stringField(c, "local_date")
		if d >= first && d <= in.AsOf && (len(anyList(c["symptoms"])) > 0 || c["pain_reported"] == true) {
			return true
		}
	}
	for _, p := range in.Prompts {
		if p["kind"] != "delayed_symptom" || p["status"] != "answered" {
			continue
		}
		at, err := time.Parse(time.RFC3339Nano, stringField(p, "opens_at"))
		if err != nil {
			continue
		}
		local := at.In(zone).Format(time.DateOnly)
		if local < first || local > in.AsOf {
			continue
		}
		found := false
		for _, c := range in.Checkins {
			samePrompt := p["prompt_id"] != nil && c["prompt_id"] == p["prompt_id"]
			sameActivity := p["activity_id"] != nil && c["activity_id"] == p["activity_id"]
			if c["kind"] != "delayed_followup" || (!samePrompt && !sameActivity) {
				continue
			}
			found = true
			if c["pain_reported"] != false || len(anyList(c["symptoms"])) > 0 {
				return true
			}
		}
		if !found {
			return true
		}
	}
	return false
}

func selectRoute(in snapshotreads.Inputs, op string) (recipes, topics []string, err error) {
	var sessions, slots, anchors []map[string]any
	var block map[string]any
	for _, item := range []struct {
		raw json.RawMessage
		dst any
	}{{in.Sessions, &sessions}, {in.StrengthSlots, &slots}, {in.Anchors, &anchors}, {in.ActiveBlock, &block}} {
		if err := json.Unmarshal(item.raw, item.dst); err != nil {
			return nil, nil, err
		}
	}
	zone, err := time.LoadLocation(in.Timezone)
	if err != nil {
		return nil, nil, err
	}
	end := scopeEnd(op, in.AsOf, stringField(block, "review_date"))
	first := topicDay(in.AsOf, -13)
	if op == "review_rolling_plan" || op == "select_quality_session" || op == "review_training_block" {
		first = topicDay(in.AsOf, -27)
	}
	if op == "review_training_block" && block != nil {
		first = stringField(block, "start_date")
	}
	recFirst := topicDay(in.AsOf, -13)
	if op == "proceed_or_modify_today" || op == "exception_review" {
		recFirst = topicDay(in.AsOf, -2)
	}
	if op == "review_training_block" {
		recFirst = topicDay(in.AsOf, -27)
	}
	enabled := [10]bool{}
	enabled[0] = symptomTopic(in, first, zone)
	for _, m := range in.MetricResults {
		d, ok := strings.CutPrefix(stringField(m, "subject_key"), "night:")
		v, _ := m["value"].(map[string]any)
		if ok && m["metric_id"] == "recovery_multisignal_summary" && m["subject_type"] == "night" && d >= recFirst && d <= in.AsOf && recoveryRelevant(v) {
			enabled[1] = true
		}
	}
	for _, c := range in.Checkins {
		d := stringField(c, "local_date")
		if d >= first && d <= in.AsOf && (c["illness"] == "possible" || c["illness"] == "present") {
			enabled[1] = true
		}
	}
	costly := map[any]bool{}
	for _, s := range slots {
		costly[s["slot_id"]] = s["active"] != false && (s["lower_body_cost"] == "moderate" || s["lower_body_cost"] == "high")
	}
	low := false
	for _, a := range anchors {
		if a["status"] == "active" && (a["confidence"] == "low" || a["confidence"] == "insufficient") {
			low = true
		}
	}
	liftDays, runDays := []string{}, []string{}
	ids := map[string]bool{}
	for _, s := range sessions {
		d := stringField(s, "local_date")
		if d < in.AsOf || d > end {
			continue
		}
		if s["kind"] == "strength" && costly[s["strength_slot_id"]] {
			liftDays = append(liftDays, d)
		}
		if s["kind"] != "run" {
			continue
		}
		runDays = append(runDays, d)
		id := stringField(s, "recipe_id")
		if id != "" {
			ids[id] = true
		}
		quality := slices.Contains(qualityRecipes, id)
		enabled[5] = enabled[5] || quality || s["placeholder"] == true
		enabled[6] = enabled[6] || low && quality && numericTarget(s)
	}
	for _, d := range liftDays {
		for _, r := range runDays {
			if r >= topicDay(d, -2) && r <= topicDay(d, 2) {
				enabled[2] = true
			}
		}
	}
	enabled[4] = op == "review_rolling_plan" || op == "review_training_block"
	enabled[3] = enabled[4] && ids["REC002"]
	enabled[6] = enabled[6] || op == "recalibrate_intensity"
	enabled[8] = op == "handle_goal_or_race_change" || op == "post_event_review"
	enabled[7] = enabled[8] || op == "review_training_block"
	if op != "recalibrate_intensity" {
		for _, trip := range in.Trips {
			start, last := stringField(trip, "start_date"), stringField(trip, "end_date")
			if last == "" {
				last = topicDay(start, 30)
			}
			if op == "review_training_block" || op == "handle_goal_or_race_change" || start <= end && last >= topicDay(in.AsOf, -7) {
				enabled[9] = true
				break
			}
		}
	}
	if op == "review_training_block" {
		for _, id := range []string{"REC001", "REC002", "REC003", "REC009"} {
			ids[id] = true
		}
	}
	if op == "review_training_block" || (op == "review_rolling_plan" || op == "select_quality_session") && enabled[5] {
		if block != nil {
			for _, v := range anyList(block["eligible_recipe_ids"]) {
				ids[v.(string)] = true
			}
		} else if op != "review_training_block" {
			for _, id := range qualityRecipes {
				ids[id] = true
			}
		}
	}
	for id := range ids {
		recipes = append(recipes, id)
	}
	slices.Sort(recipes)
	for i, t := range coaching.ConditionalTopics() {
		if enabled[i] {
			topics = append(topics, t)
		}
	}
	return recipes, topics, nil
}
