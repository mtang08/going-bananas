package snapshotreads

import (
	"encoding/json"
	"reflect"
	"testing"
	"time"
)

func TestActivityContract(t *testing.T) {
	tx, reference := snapshotFixture(t, "activity")
	var want struct {
		ActivityInputs
		Zone string
	}
	if err := json.Unmarshal(reference, &want); err != nil {
		t.Fatal(err)
	}
	if len(want.Runs) != 4 || len(want.Coverage) != 2 || len(want.MetricResults) < 14 {
		t.Fatal("incomplete reference fixture")
	}
	zone, err := time.LoadLocation(want.Zone)
	if err != nil {
		t.Fatal(err)
	}
	got, err := LoadActivity(t.Context(), tx, "2021-11-07", zone)
	if err != nil {
		t.Fatal(err)
	}
	encoded, err := json.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	var normalized ActivityInputs
	if err := json.Unmarshal(encoded, &normalized); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(normalized, want.ActivityInputs) {
		t.Errorf("snapshot inputs differ\ngot: %s\nwant: %s", encoded, reference)
	}
}
