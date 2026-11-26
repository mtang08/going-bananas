// Package assessment computes and persists the planned-versus-actual session metric.
package assessment

import (
	"encoding/json"
	"errors"
	"github.com/mtang08/going-bananas/backend-go/internal/calendarstructure"
	"math"
	"slices"
	"strconv"
)

type Plan struct {
	LocalDate string          `json:"local_date"`
	Kind      string          `json:"kind"`
	Certainty *string         `json:"certainty"`
	Version   *int            `json:"calendar_version_number"`
	Duration  *float64        `json:"planned_duration_s"`
	Distance  *float64        `json:"planned_distance_m"`
	Steps     json.RawMessage `json:"structure"`
}
type Completion struct {
	Status   string `json:"status"`
	Method   string `json:"match_method"`
	Reason   string `json:"modification_reason"`
	Activity string `json:"activity_id"`
	Strong   string `json:"strong_workout_id"`
	Manual   string `json:"manual_session_id"`
	Key      string `json:"subject_key"`
}
type Activity struct {
	Kind     string   `json:"kind"`
	Sport    string   `json:"sport"`
	Timer    *float64 `json:"timer_s"`
	Distance *float64 `json:"distance_m"`
}
type Intervals struct {
	Step   *float64 `json:"step_completion_ratio"`
	Target *float64 `json:"target_coverage"`
}
type Candidate struct {
	SubjectKey string `json:"subject_key"`
	ActivityID string `json:"activity_id"`
	Reason     string `json:"reason"`
}
type Input struct {
	Plan       *Plan       `json:"plan"`
	Completion *Completion `json:"completion"`
	Activity   *Activity   `json:"activity"`
	Intervals  *Intervals  `json:"intervals"`
	Candidates []Candidate `json:"candidates"`
	Coverage   bool        `json:"coverage_complete"`
	AsOf       string      `json:"as_of"`
}
type Component struct {
	Name   string   `json:"name"`
	Value  *float64 `json:"value"`
	Status string   `json:"status"`
}
type Value struct {
	Overall         string      `json:"overall_status"`
	Components      []Component `json:"components"`
	Certainty       *string     `json:"certainty"`
	Kind            *string     `json:"kind"`
	CandidateIDs    []string    `json:"candidate_activity_ids"`
	CalendarVersion *int        `json:"calendar_version"`
	Method          string      `json:"match_method"`
}
type Outcome struct {
	Status  string   `json:"status"`
	Quality *string  `json:"quality_status"`
	Value   Value    `json:"value"`
	Reasons []string `json:"reason_codes"`
	Flags   []string `json:"quality_flags"`
	Derived *string  `json:"derived_completion_status,omitempty"`
}

func valid(v *float64) bool { return v != nil && !math.IsNaN(*v) && !math.IsInf(*v, 0) }
func ratio(name string, actual, planned *float64) (Component, float64) {
	c := Component{Name: name, Status: "omitted"}
	if !valid(planned) || *planned <= 0 {
		return c, 0
	}
	c.Status = "not_assessable"
	if !valid(actual) || *actual < 0 {
		return c, 0
	}
	r := *actual / *planned
	rounded, _ := strconv.ParseFloat(strconv.FormatFloat(r, 'f', 3, 64), 64)
	c.Value = &rounded
	met, partial := 0.9, 0.5
	switch name {
	case "step_completion_ratio":
		met = 1
	case "target_coverage":
		met, partial = 0.75, 0.4
	}
	switch {
	case r >= met:
		c.Status = "met"
	case r >= partial:
		c.Status = "partially_met"
	default:
		c.Status = "not_met"
	}
	return c, r
}

func comparison(p Plan) (Plan, bool, bool, error) {
	if len(p.Steps) == 0 || string(p.Steps) == "null" || string(p.Steps) == "[]" {
		return p, false, false, nil
	}
	steps, ok := calendarstructure.Expand(p.Steps)
	if !ok {
		return p, false, false, errors.New("invalid_structure")
	}
	if p.Kind == "run" && len(steps) == 1 && steps[0].Type == "work" {
		s := steps[0]
		dose := &p.Distance
		if s.DurationType == "time" {
			dose = &p.Duration
		}
		if (s.Target == nil || s.Target.Modality == "effort") && (*dose == nil || **dose == s.DurationValue) {
			*dose = &s.DurationValue
			return p, false, false, nil
		}
	}
	work, speed := false, false
	for _, s := range steps {
		if s.Type == "work" {
			work = true
			if s.Target != nil && s.Target.Modality == "speed" {
				speed = true
			}
		}
	}
	return p, work, speed, nil
}

func unlinked(i Input, c Completion) string {
	switch {
	case c.Method == "user_marked" && c.Status == "completed_as_planned":
		return "SELF_REPORTED_COMPLETION"
	case i.Plan != nil && i.Plan.LocalDate != "" && i.Plan.LocalDate >= i.AsOf:
		return "NOT_YET_DUE"
	case c.Method == "user_marked" && c.Status != "skipped":
		return "UNLINKED_BY_USER"
	}
	for _, reason := range []string{"AMBIGUOUS_MATCH", "MOVE_CANDIDATE"} {
		for _, candidate := range i.Candidates {
			if candidate.Reason == reason {
				return reason
			}
		}
	}
	if !i.Coverage {
		return "AWAITING_SYNC"
	}
	return "NO_ACTIVITY_FOUND"
}

func (o *Outcome) linked(i Input, c Completion, treadmill bool) error {
	a := Activity{}
	if i.Activity == nil {
		o.Reasons = append(o.Reasons, "ACTIVITY_EXCLUDED")
	} else {
		a = *i.Activity
	}
	interval := Intervals{}
	if i.Intervals != nil {
		interval = *i.Intervals
	}
	statuses := map[string]bool{}
	durationShort, stepShort, exceeded := false, false, false
	if i.Plan != nil {
		p, work, speed, err := comparison(*i.Plan)
		if err != nil {
			return err
		}
		one := 1.0
		add := func(name string, actual, planned *float64) {
			item, raw := ratio(name, actual, planned)
			if item.Status == "omitted" {
				return
			}
			o.Value.Components = append(o.Value.Components, item)
			statuses[item.Status] = true
			if name == "duration_ratio" || name == "distance_ratio" {
				exceeded = exceeded || raw > 1.15
				if name == "duration_ratio" && valid(actual) {
					durationShort = *actual / *planned < 0.9
				}
			}
		}
		add("duration_ratio", a.Timer, p.Duration)
		if !treadmill || p.Duration == nil || *p.Duration == 0 {
			add("distance_ratio", a.Distance, p.Distance)
		}
		if work {
			add("step_completion_ratio", interval.Step, &one)
			stepShort = interval.Step != nil && *interval.Step < 1
		}
		if speed && !treadmill {
			add("target_coverage", interval.Target, &one)
		}
	}
	if len(statuses) == 0 && len(o.Reasons) == 0 {
		o.Reasons = append(o.Reasons, "INSUFFICIENT_PLAN")
	}
	if statuses["not_assessable"] {
		o.Reasons = append(o.Reasons, "COMPONENT_NOT_ASSESSABLE")
	}
	if i.Activity != nil && len(statuses) > 0 {
		switch {
		case stepShort && durationShort || statuses["not_met"]:
			o.Value.Overall = "partial"
		case (statuses["met"] || statuses["partially_met"]) && (c.Reason != "" || statuses["partially_met"]):
			o.Value.Overall = "completed_modified"
		case !statuses["not_assessable"] && statuses["met"]:
			o.Value.Overall = "completed_as_planned"
		}
		if exceeded {
			o.Flags = append(o.Flags, "EXCEEDED")
		}
	}
	if c.Method == "confirmed_move" && i.Activity != nil {
		if o.Value.Overall == "partial" {
			o.Flags = append(o.Flags, "MOVED")
		} else {
			o.Value.Overall = "moved"
		}
	}
	if slices.Contains([]string{"symptom_onset", "fatigue", "illness"}, c.Reason) {
		o.Flags = append(o.Flags, "SENSIBLE_MODIFICATION")
	}
	return nil
}

func Assess(i Input) (Outcome, error) {
	o := Outcome{Value: Value{Overall: "unknown", Method: "none", Components: []Component{}, CandidateIDs: []string{}}, Reasons: []string{}, Flags: []string{}}
	if p := i.Plan; p != nil {
		o.Value.Certainty = p.Certainty
		o.Value.CalendarVersion = p.Version
		o.Value.Kind = &p.Kind
	} else if i.Activity != nil {
		o.Value.Kind = &i.Activity.Kind
	}
	for _, candidate := range i.Candidates {
		key := candidate.SubjectKey
		if key == "" {
			key = candidate.ActivityID
		}
		if key == "" {
			key = "None"
		}
		o.Value.CandidateIDs = append(o.Value.CandidateIDs, key)
	}
	c := Completion{}
	if i.Completion != nil {
		c = *i.Completion
	}
	if c.Method != "" {
		o.Value.Method = c.Method
	}
	linked := c.Activity != "" || c.Strong != "" || c.Manual != "" || c.Key != ""
	treadmill := linked && i.Activity != nil && i.Activity.Sport == "treadmill_running"
	if treadmill {
		o.Flags = append(o.Flags, "TREADMILL_PACE_NOT_SCORED")
	}
	switch {
	case c.Status == "skipped" && slices.Contains([]string{"explicit", "user_marked", "confirmed_move"}, c.Method):
		o.Value.Overall = "skipped"
	case c.Status == "extra" && c.Method != "confirmed_move" && linked && i.Activity != nil:
		o.Value.Overall = "extra"
	case !linked:
		o.Reasons = append(o.Reasons, unlinked(i, c))
	default:
		if err := o.linked(i, c, treadmill); err != nil {
			return Outcome{}, err
		}
	}
	switch {
	case o.Value.Overall != "unknown" && len(o.Reasons) == 0:
		o.Status = "available"
	case o.Value.Overall != "unknown" || len(o.Reasons) > 0 && linked:
		o.Status = "partial"
	default:
		o.Status = "missing"
	}
	quality := ""
	switch {
	case o.Status == "available" && len(o.Flags) == 0:
		quality = "good"
	case o.Status == "partial" || len(o.Flags) > 0:
		quality = "limited"
	}
	if quality != "" {
		o.Quality = &quality
	}
	if linked || o.Value.Overall == "skipped" || o.Value.Overall == "extra" {
		o.Derived = &o.Value.Overall
	}
	return o, nil
}
