package drafts

import (
	"bytes"
	"encoding/json"
	"fmt"
	"reflect"
	"slices"
	"strings"
)

type target struct {
	Modality  string `json:"modality"`
	Low, High *float64
	Cue       *string `json:"effort_cue"`
}
type step struct {
	Type     string  `json:"type"`
	Unit     string  `json:"duration_type"`
	Amount   float64 `json:"duration_value"`
	Target   *target `json:"target"`
	Count    int     `json:"count"`
	Children []step  `json:"steps"`
}

func validStep(s step) bool {
	if !slices.Contains([]string{"warmup", "work", "recovery", "cooldown"}, s.Type) || !slices.Contains([]string{"distance", "time"}, s.Unit) || s.Amount <= 0 {
		return false
	}
	t := s.Target
	if t == nil {
		return true
	}
	if t.Modality == "effort" {
		return t.Low == nil && t.High == nil && t.Cue != nil && strings.TrimSpace(*t.Cue) != ""
	}
	if t.Modality != "speed" && t.Modality != "hr" {
		return false
	}
	return t.Low != nil && t.High != nil && *t.Low >= 0 && *t.High >= *t.Low && (t.Modality != "hr" || *t.Low > 0) && (t.Cue == nil || strings.TrimSpace(*t.Cue) != "")
}

func expand(raw json.RawMessage) ([]step, bool) {
	var items []step
	if json.Unmarshal(raw, &items) != nil || len(items) == 0 {
		return nil, false
	}
	var result []step
	for _, s := range items {
		if s.Type != "repeat" {
			if !validStep(s) || len(result) == 100 {
				return nil, false
			}
			result = append(result, s)
			continue
		}
		if len(s.Children) == 0 || s.Count < 2 || s.Count > (100-len(result))/len(s.Children) {
			return nil, false
		}
		for _, child := range s.Children {
			if !validStep(child) {
				return nil, false
			}
		}
		for range s.Count {
			result = append(result, s.Children...)
		}
	}
	return result, true
}

type effort struct {
	Low  int `json:"rpe_low"`
	High int `json:"rpe_high"`
}

var recipeEffort = map[string]effort{"REC001": {2, 4}, "REC002": {3, 5}, "REC003": {5, 7}, "REC004": {5, 7}, "REC005": {6, 8}, "REC006": {5, 7}, "REC007": {2, 4}, "REC008": {5, 7}}

func prescribed(s sessionFields) *effort {
	var b struct{ Effort *effort }
	if json.Unmarshal(s.Brief, &b) != nil {
		return nil
	}
	return b.Effort
}
func quality(s sessionFields) bool {
	return s.Kind == "run" && (s.Placeholder || slices.Contains([]string{"REC003", "REC004", "REC005", "REC006", "REC008", "REC009"}, s.Recipe))
}
func value(n *int) int {
	if n == nil {
		return 0
	}
	return *n
}
func noHarder(a, b step) bool {
	if a.Type != b.Type || a.Unit != b.Unit || a.Amount > b.Amount {
		return false
	}
	if reflect.DeepEqual(a.Target, b.Target) {
		return true
	}
	n, o := a.Target, b.Target
	return n != nil && o != nil && n.Modality == o.Modality && (n.Modality == "speed" || n.Modality == "hr") && *n.Low <= *o.Low && *n.High <= *o.High && reflect.DeepEqual(n.Cue, o.Cue)
}
func sameJSON(a, b json.RawMessage) bool {
	if bytes.Equal(a, b) {
		return true
	}
	var x, y any
	if len(a) > 0 && json.Unmarshal(a, &x) != nil {
		return false
	}
	if len(b) > 0 && json.Unmarshal(b, &y) != nil {
		return false
	}
	return reflect.DeepEqual(x, y)
}
func raisesDose(a, b sessionFields) bool {
	if n := prescribed(a); n != nil {
		old := prescribed(b)
		if old != nil && (n.Low > old.Low || n.High > old.High) {
			return true
		}
		if guide, ok := recipeEffort[b.Recipe]; old == nil && ok && n.High > guide.High {
			return true
		}
	}
	if value(a.Duration) > value(b.Duration) || value(a.Distance) > value(b.Distance) {
		return true
	}
	if a.Recipe != b.Recipe {
		if quality(sessionFields{Kind: "run", Recipe: a.Recipe}) || (b.Recipe == "REC001" && a.Recipe == "REC007") {
			return true
		}
		g, ok := recipeEffort[a.Recipe]
		h, old := recipeEffort[b.Recipe]
		if ok && old && (g.Low > h.Low || g.High > h.High) {
			return true
		}
	}
	if sameJSON(a.Structure, b.Structure) {
		return false
	}
	previous, _ := expand(b.Structure)
	current, _ := expand(a.Structure)
	j := 0
	for _, s := range current {
		for j < len(previous) && !noHarder(s, previous[j]) {
			j++
		}
		if j == len(previous) {
			return true
		}
		j++
	}
	return false
}

type restriction struct {
	Start       string `json:"starts_on"`
	End         string `json:"ends_on"`
	Review      string `json:"review_on"`
	Pause       bool   `json:"pause_running"`
	NoQuality   bool   `json:"no_quality"`
	MaxDistance *int   `json:"max_distance_m"`
	MaxDuration *int   `json:"max_duration_s"`
}
type interruption struct {
	Start  string `json:"starts_on"`
	Return string `json:"return_on"`
}
type safetyGuard struct {
	Gait        bool     `json:"gait_change_yes"`
	Illness     bool     `json:"illness_present"`
	Restriction bool     `json:"clinical_restriction_active"`
	Severity    *float64 `json:"max_symptom_severity"`
}

func (g *safetyGuard) active() bool {
	return g == nil || g.Gait || g.Illness || g.Restriction || (g.Severity != nil && *g.Severity >= 6.5)
}

func structuredDose(steps []step, unit string) (float64, bool) {
	total := 0.0
	complete := len(steps) > 0
	for _, s := range steps {
		if s.Unit == unit {
			total += s.Amount
			continue
		}
		if t := s.Target; t != nil && t.Modality == "speed" {
			if unit == "distance" {
				total += s.Amount * (*t.High)
				continue
			}
			if *t.Low > 0 {
				total += s.Amount / (*t.Low)
				continue
			}
			if *t.High > 0 {
				total += s.Amount / (*t.High)
			}
		}
		complete = false
	}
	return total, complete
}

func restrictionConflict(r *restriction, a, b sessionFields, hasHead bool) string {
	if r == nil || a.Kind != "run" || a.LocalDate == "" || a.LocalDate < r.Start || (r.End != "" && a.LocalDate > r.End) {
		return ""
	}
	if hasHead {
		same := true
		for _, k := range strings.Fields("local_date kind recipe_id custom placeholder intent structure brief planned_duration_s planned_distance_m") {
			if !sameJSON(a.raw[k], b.raw[k]) {
				same = false
				break
			}
		}
		if same {
			return ""
		}
	}
	prefix := "Running restriction on " + a.LocalDate
	if r.End == "" && r.Review != "" && a.LocalDate >= r.Review {
		prefix += " (review date " + r.Review + ", with no confirmed end)"
	}
	if r.Pause {
		return prefix + " pauses running. Remove the run or move it outside the restricted dates."
	}
	steps, _ := expand(a.Structure)
	if r.NoQuality {
		class := ""
		switch a.Recipe {
		case "REC001", "REC007":
			class = "easy"
		case "REC002":
			class = "long"
		}
		work := 0
		recovery := false
		for _, s := range steps {
			if s.Type == "recovery" {
				recovery = true
			}
			if s.Type == "work" {
				work++
			}
		}
		if class == "" || a.Placeholder || a.Custom || recovery || work > 1 {
			return prefix + " excludes quality sessions. Use an easy or long run recipe with continuous work."
		}
		target := prescribed(a)
		guide := recipeEffort[a.Recipe]
		if target != nil && target.High > guide.High {
			return fmt.Sprintf("%s excludes quality sessions. Keep the target within the %s recipe range up to RPE %d.", prefix, class, guide.High)
		}
	}
	for _, limit := range []struct {
		unit, suffix, label string
		cap, declared       *int
	}{{"distance", "m", "distance", r.MaxDistance, a.Distance}, {"time", "s", "duration", r.MaxDuration, a.Duration}} {
		if limit.cap == nil {
			continue
		}
		measured, complete := structuredDose(steps, limit.unit)
		if max(float64(value(limit.declared)), measured) > float64(*limit.cap) {
			return fmt.Sprintf("%s caps each run at %d %s. Reduce the planned total and workout steps.", prefix, *limit.cap, limit.suffix)
		}
		if limit.declared == nil && !complete {
			return fmt.Sprintf("%s caps each run at %d %s. Enter a planned %s within the limit.", prefix, *limit.cap, limit.suffix, limit.label)
		}
	}
	return ""
}
