package snapshots

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"reflect"
	"slices"
	"testing"

	"github.com/mtang08/going-bananas/backend-go/internal/coaching/snapshotreads"
)

func TestReferencePayloads(t *testing.T) {
	python := os.Getenv("DASHBOARD_REFERENCE_PYTHON")
	if python == "" {
		t.Skip("requires configured backend Python")
	}
	raw, err := exec.CommandContext(t.Context(), python, "testdata/payload_reference.py").Output()
	if err != nil {
		t.Fatal("Python snapshot suite:", err)
	}
	var cases []struct {
		Inputs    snapshotreads.Inputs
		Operation string
		Expected  obj
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	ops := map[string]bool{}
	for i, c := range cases {
		ops[c.Operation] = true
		t.Run(fmt.Sprintf("%03d_%s", i, c.Operation), func(t *testing.T) {
			payload, err := BuildPayload(c.Inputs, c.Operation)
			if err != nil {
				t.Fatal(err)
			}
			b, err := json.Marshal(payload)
			if err != nil {
				t.Fatal(err)
			}
			var got obj
			if err = json.Unmarshal(b, &got); err != nil {
				t.Fatal(err)
			}
			keys := []string{}
			for k, v := range c.Expected {
				if !reflect.DeepEqual(got[k], v) {
					keys = append(keys, k)
				}
			}
			for k := range got {
				if _, ok := c.Expected[k]; !ok {
					keys = append(keys, k)
				}
			}
			slices.Sort(keys)
			for _, k := range keys {
				a, _ := json.Marshal(got[k])
				w, _ := json.Marshal(c.Expected[k])
				t.Errorf("%s: got %s; want %s", k, a, w)
			}
		})
	}
	if len(ops) != 8 {
		t.Fatal("missing reference operations", ops)
	}
}
