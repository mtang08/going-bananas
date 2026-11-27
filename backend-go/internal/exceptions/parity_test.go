package exceptions

import (
	"compress/gzip"
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"testing"
)

func TestPythonRuleCases(t *testing.T) {
	f, err := os.Open("testdata/rules.json.gz")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	gz, err := gzip.NewReader(f)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = gz.Close() }()
	var cases []struct {
		Name     string
		Input    DetectionInputs
		Expected []Candidate
	}
	if err = json.NewDecoder(gz).Decode(&cases); err != nil {
		t.Fatal(err)
	}
	for i, c := range cases {
		t.Run(fmt.Sprintf("%03d_%s", i, c.Name), func(t *testing.T) {
			got := Candidates(c.Input)
			if len(got) != len(c.Expected) {
				t.Fatalf("got %d candidates, expected %d: %v", len(got), len(c.Expected), got)
			}
			for j, w := range c.Expected {
				a := got[j]
				if !w.At.Equal(a.At) {
					t.Fatalf("%s evidence time got %v, expected %v", w.Code, a.At, w.At)
				}
				// Compare JSON projections to normalize numeric Go types and time zones.
				w.At = a.At
				jsonValue := func(c Candidate) any {
					t.Helper()
					data, e := json.Marshal(c)
					if e != nil {
						t.Fatal(e)
					}
					var v any
					if e = json.Unmarshal(data, &v); e != nil {
						t.Fatal(e)
					}
					return v
				}
				if !reflect.DeepEqual(jsonValue(w), jsonValue(a)) {
					t.Fatalf("got %v\nwant %v", jsonValue(a), jsonValue(w))
				}
			}
		})
	}
}
