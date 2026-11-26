// Package calendarstructure validates and expands the one-level calendar step language.
package calendarstructure

import (
	"encoding/json"
	"fmt"
	"slices"
	"strconv"
	"strings"
)

type Target struct {
	Modality  string `json:"modality"`
	Low, High *float64
	EffortCue *string `json:"effort_cue"`
}
type Step struct {
	Type          string  `json:"type"`
	DurationType  string  `json:"duration_type"`
	DurationValue float64 `json:"duration_value"`
	Target        *Target `json:"target"`
	StepPath      string  `json:"step_path"`
	ExpandedStep  int     `json:"expanded_step"`
	RepeatIndex   *int    `json:"repeat_index"`
}
type object map[string]json.RawMessage

func keys(o object, allowed ...string) bool {
	for k := range o {
		if !slices.Contains(allowed, k) {
			return false
		}
	}
	return true
}
func single(o object) (Step, bool) {
	var s Step
	if !keys(o, "type", "duration_type", "duration_value", "target") || json.Unmarshal(o["type"], &s.Type) != nil || !slices.Contains([]string{"warmup", "work", "recovery", "cooldown"}, s.Type) || json.Unmarshal(o["duration_type"], &s.DurationType) != nil || !slices.Contains([]string{"time", "distance"}, s.DurationType) || json.Unmarshal(o["duration_value"], &s.DurationValue) != nil || s.DurationValue <= 0 {
		return s, false
	}
	raw := o["target"]
	if len(raw) == 0 || string(raw) == "null" {
		return s, true
	}
	var targetFields object
	if json.Unmarshal(raw, &targetFields) != nil || !keys(targetFields, "modality", "low", "high", "effort_cue") || json.Unmarshal(raw, &s.Target) != nil {
		return s, false
	}
	t := s.Target
	cue := t.EffortCue != nil && strings.TrimSpace(*t.EffortCue) != ""
	switch t.Modality {
	case "effort":
		return s, t.Low == nil && t.High == nil && cue
	case "hr", "speed":
		return s, t.Low != nil && t.High != nil && *t.Low >= 0 && *t.High >= *t.Low && (t.Modality != "hr" || *t.Low > 0) && (t.EffortCue == nil || cue)
	default:
		return s, false
	}
}
func Expand(raw json.RawMessage) ([]Step, bool) {
	var items []object
	if json.Unmarshal(raw, &items) != nil || len(items) == 0 {
		return nil, false
	}
	var out []Step
	for i, o := range items {
		var typ string
		if json.Unmarshal(o["type"], &typ) != nil {
			return nil, false
		}
		if typ != "repeat" {
			s, ok := single(o)
			if !ok || len(out) >= 100 {
				return nil, false
			}
			s.StepPath = strconv.Itoa(i)
			s.ExpandedStep = len(out) + 1
			out = append(out, s)
			continue
		}
		var count int
		var children []object
		if !keys(o, "type", "count", "steps") || json.Unmarshal(o["count"], &count) != nil || count < 2 || json.Unmarshal(o["steps"], &children) != nil || len(children) == 0 || count > (100-len(out))/len(children) {
			return nil, false
		}
		for repetition := range count {
			for j, child := range children {
				s, ok := single(child)
				if !ok {
					return nil, false
				}
				s.StepPath = fmt.Sprintf("%d.steps.%d", i, j)
				s.RepeatIndex = &repetition
				s.ExpandedStep = len(out) + 1
				out = append(out, s)
			}
		}
	}
	return out, true
}
