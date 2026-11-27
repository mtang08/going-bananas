package snapshotreads

import (
	"encoding/json"
	"reflect"
	"testing"
)

func TestPlanningContract(t *testing.T) {
	tx, want := snapshotFixture(t, "planning")
	result, err := LoadPlanning(t.Context(), tx, "2026-03-08")
	if err != nil {
		t.Fatal(err)
	}
	raw, err := json.Marshal(result)
	if err != nil {
		t.Fatal(err)
	}
	var candidate, reference map[string][]map[string]any
	if err := json.Unmarshal(raw, &candidate); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(want, &reference); err != nil {
		t.Fatal(err)
	}
	for k, expected := range reference {
		if !reflect.DeepEqual(candidate[k], expected) {
			t.Errorf("%s projection: got %v, want %v", k, candidate[k], expected)
		}
	}
	if len(candidate) != len(reference) {
		t.Errorf("got %d planning sections, want %d", len(candidate), len(reference))
	}
}
