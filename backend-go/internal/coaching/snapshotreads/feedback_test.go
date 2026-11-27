package snapshotreads

import (
	"encoding/json"
	"reflect"
	"testing"
	"time"
)

func TestFeedbackContract(t *testing.T) {
	tx, reference := snapshotFixture(t, "feedback")
	zone, err := time.LoadLocation("America/New_York")
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 11, 2, 3, 30, 0, 125000000, time.UTC)
	checkins, err := Checkins(t.Context(), tx, now, zone)
	if err != nil {
		t.Fatal(err)
	}
	prompts, err := Prompts(t.Context(), tx, now)
	if err != nil {
		t.Fatal(err)
	}
	gotJSON, err := json.Marshal(map[string]any{"checkins": checkins, "prompts": prompts})
	if err != nil {
		t.Fatal(err)
	}
	var got, want map[string][]map[string]any
	if err = json.Unmarshal(gotJSON, &got); err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(reference, &want); err != nil {
		t.Fatal(err)
	}
	if len(want["checkins"]) != 5 || len(want["prompts"]) != 3 {
		t.Fatal("unexpected reference fixture sizes")
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("feedback differs from saved output\ngot: %s\nwant: %s", gotJSON, reference)
	}
}
