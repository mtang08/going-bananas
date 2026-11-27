package snapshots

import (
	"bytes"
	"encoding/json"
	"os"
	"reflect"
	"testing"

	"github.com/mtang08/going-bananas/backend-go/internal/coaching/snapshotreads"
)

func TestAdvancedSectionReferences(t *testing.T) {
	raw, err := os.ReadFile("testdata/advanced.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Inputs    snapshotreads.Inputs
		Operation string
		Want      map[string]any
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) < 40 {
		t.Fatal("expected populated sections and operation variations")
	}
	for n, c := range cases {
		d, err := display(c.Inputs, c.Operation)
		if err != nil {
			t.Fatal(err)
		}
		sections := obj{}
		if err := d.addAdvanced(sections); err != nil {
			t.Fatal(err)
		}
		got, err := json.Marshal(strip(sections))
		if err != nil {
			t.Fatal(err)
		}
		var result obj
		if err := json.Unmarshal(got, &result); err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(result, c.Want) {
			for k, v := range c.Want {
				if !reflect.DeepEqual(result[k], v) {
					actual, _ := json.Marshal(result[k])
					want, _ := json.Marshal(v)
					i := 0
					for i < len(actual) && i < len(want) && actual[i] == want[i] {
						i++
					}
					t.Fatalf("case %d %s %s differs at %d: Go %s; Python %s", n, c.Operation, k, i, bytes.TrimSpace(actual[max(0, i-60):min(i+100, len(actual))]), bytes.TrimSpace(want[max(0, i-60):min(i+100, len(want))]))
				}
			}
			t.Fatalf("case %d contains unexpected sections", n)
		}
	}
}
