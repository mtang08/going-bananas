package assessment

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"
)

func TestPythonOutcomes(t *testing.T) {
	b, err := os.ReadFile("testdata/outcomes.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Test     string
		Input    Input
		Expected json.RawMessage
	}
	if err := json.Unmarshal(b, &cases); err != nil {
		t.Fatal(err)
	}
	for _, tc := range cases {
		t.Run(tc.Test, func(t *testing.T) {
			out, err := Assess(tc.Input)
			if err != nil {
				t.Fatal(err)
			}
			actual, err := json.Marshal(out)
			if err != nil {
				t.Fatal(err)
			}
			var a, b any
			if err := json.Unmarshal(actual, &a); err != nil {
				t.Fatal(err)
			}
			if err := json.Unmarshal(tc.Expected, &b); err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(a, b) {
				t.Fatalf("Python %s\nGo %s", tc.Expected, actual)
			}
		})
	}
}
