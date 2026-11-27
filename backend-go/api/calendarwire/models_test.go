package calendarwire

import (
	_ "embed"
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"
)

//go:embed testdata/command_responses.json
var commandResponses []byte

func TestCalendarResponses(t *testing.T) {
	corpus := commandResponses
	if path := os.Getenv("CALENDAR_WIRE_CASES"); path != "" {
		var err error
		corpus, err = os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
	}
	var cases []struct {
		Path     string
		Envelope json.RawMessage
	}
	if err := json.Unmarshal(corpus, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) == 0 {
		t.Fatal("missing calendar wire cases")
	}
	for _, item := range cases {
		t.Run(item.Path, func(t *testing.T) {
			var wire any = &CalendarViewEnvelope{}
			switch strings.SplitN(item.Path, "?", 2)[0] {
			case "/diff":
				wire = &CalendarDiffEnvelope{}
			case "/weekly-projection":
				wire = &WeeklyProjectionEnvelope{}
			case "/weekly-digest":
				wire = &WeeklyDigestEnvelope{}
			case "/bootstrap", "/edits", "/rollback":
				wire = &CalendarWriteResultEnvelope{}
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
