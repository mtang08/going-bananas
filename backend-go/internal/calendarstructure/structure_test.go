package calendarstructure

import "testing"

func TestRepeatAndMalformedStructure(t *testing.T) {
	steps, ok := Expand([]byte(`[{"type":"repeat","count":2,"steps":[{"type":"work","duration_type":"time","duration_value":60,"target":{"modality":"hr","low":120,"high":150}}]}]`))
	if !ok || len(steps) != 2 || steps[1].ExpandedStep != 2 || steps[1].StepPath != "0.steps.0" || *steps[0].RepeatIndex != 0 || *steps[1].RepeatIndex != 1 {
		t.Fatal(steps)
	}
	for _, raw := range []string{`[{"type":"work","duration_type":"time","duration_value":60,"count":2}]`, `[{"type":"repeat","count":2.0,"steps":[]}]`, `[{"type":"work","duration_type":"time","duration_value":10,"target":{"modality":"effort","effort_cue":" "}}]`} {
		if _, ok := Expand([]byte(raw)); ok {
			t.Fatal(raw)
		}
	}
}
