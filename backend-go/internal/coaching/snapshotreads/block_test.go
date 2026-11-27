package snapshotreads

import (
	"encoding/json"
	"maps"
	"reflect"
	"testing"

	"github.com/mtang08/going-bananas/backend-go/internal/testpg"
)

func TestBlockContract(t *testing.T) {
	tx := testpg.DashboardTx(t)
	var baseline map[string]any
	if err := json.Unmarshal(fixtureFile(t, "event.json"), &baseline); err != nil {
		t.Fatal(err)
	}
	// Each later phase only changes a few persisted rows and response sections.
	for _, phase := range []string{"event", "manual", "pending", "missed", "trial", "not_set", "archived"} {
		if phase != "missed" {
			loadSeed(t, tx, phase)
		}
		t.Run(phase, func(t *testing.T) {
			asOf := "2026-11-01"
			if phase == "missed" {
				asOf = "2026-11-07"
			}
			got, err := LoadBlock(t.Context(), tx, asOf)
			if err != nil {
				t.Fatal(err)
			}
			encoded, err := json.Marshal(got)
			if err != nil {
				t.Fatal(err)
			}
			var actual map[string]any
			if err := json.Unmarshal(encoded, &actual); err != nil {
				t.Fatal(err)
			}
			expected := maps.Clone(baseline)
			if phase != "event" {
				var changes map[string]any
				if err := json.Unmarshal(fixtureFile(t, phase+".json"), &changes); err != nil {
					t.Fatal(err)
				}
				maps.Copy(expected, changes)
			}
			for k, v := range expected {
				if !reflect.DeepEqual(actual[k], v) {
					t.Errorf("%s: got %#v, want %#v", k, actual[k], v)
				}
			}
		})
	}
}
