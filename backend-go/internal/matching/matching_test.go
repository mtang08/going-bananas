package matching

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"
)

func TestMatchingFixture(t *testing.T) {
	checkMatchingCases(t, "testdata/matching.json")
}

func TestPythonMatchingCorpus(t *testing.T) {
	path := os.Getenv("MATCHING_REFERENCE_JSON")
	if path == "" {
		t.Skip("scripts/rewrite/check_matching.py supplies the Python reference corpus")
	}
	checkMatchingCases(t, path)
}

func checkMatchingCases(t *testing.T, path string) {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Name   string
		Input  Input
		Result json.RawMessage
	}
	if err := json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) == 0 {
		t.Fatal("empty matching corpus")
	}
	for _, tc := range cases {
		t.Run(tc.Name, func(t *testing.T) {
			raw, err := json.Marshal(PlanMatches(tc.Input))
			if err != nil {
				t.Fatal(err)
			}
			// JSON object ordering is immaterial. Array order and explicit empty
			// arrays/objects are part of the Python matcher contract.
			var got, want any
			if err := json.Unmarshal(raw, &got); err != nil {
				t.Fatal(err)
			}
			if err := json.Unmarshal(tc.Result, &want); err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(got, want) {
				t.Errorf("PlanMatches() = %s\nwant %s", raw, tc.Result)
			}
		})
	}
}
