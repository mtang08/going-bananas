package calendarwire

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"
)

func TestPythonCalendarResponses(t *testing.T) {
	path := os.Getenv("CALENDAR_WIRE_CASES")
	if path == "" {
		t.Skip("run migrated calendar view comparison")
	}
	corpus, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Path     string
		Diff     bool
		Envelope json.RawMessage
	}
	if err := json.Unmarshal(corpus, &cases); err != nil {
		t.Fatal(err)
	}
	for _, item := range cases {
		t.Run(item.Path, func(t *testing.T) {
			var wire any = &CalendarViewEnvelope{}
			if item.Diff {
				wire = &CalendarDiffEnvelope{}
			}
			if err := json.Unmarshal(item.Envelope, wire); err != nil {
				t.Fatal(err)
			}
			encoded, err := json.Marshal(wire)
			if err != nil {
				t.Fatal(err)
			}
			var expected, got map[string]any
			if err := json.Unmarshal(item.Envelope, &expected); err != nil {
				t.Fatal(err)
			}
			if err := json.Unmarshal(encoded, &got); err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(expected, got) {
				t.Fatalf("generated response loses or adds wire fields: %s vs %s", encoded, item.Envelope)
			}
		})
	}
}
