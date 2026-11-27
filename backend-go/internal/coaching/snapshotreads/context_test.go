package snapshotreads

import (
	"encoding/json"
	"reflect"
	"testing"
	"time"
)

func TestContextContract(t *testing.T) {
	tx, want := snapshotFixture(t, "context")
	ctx := t.Context()
	now := time.Date(2026, 11, 2, 3, 30, 0, 125000000, time.UTC)
	zone, err := time.LoadLocation("America/New_York")
	if err != nil {
		t.Fatal(err)
	}
	exceptions, err := LoadExceptions(ctx, tx, "2026-11-02", now)
	if err != nil {
		t.Fatal(err)
	}
	travel, err := LoadTravel(ctx, tx, "2026-11-02", zone)
	if err != nil {
		t.Fatal(err)
	}
	got, err := json.Marshal(struct {
		ExceptionContext
		TravelContext
	}{exceptions, travel})
	if err != nil {
		t.Fatal(err)
	}
	var a, b map[string]any
	if err = json.Unmarshal(got, &a); err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(want, &b); err != nil {
		t.Fatal(err)
	}
	for key, wanted := range b {
		if !reflect.DeepEqual(a[key], wanted) {
			t.Errorf("context %s: got %v, want %v", key, a[key], wanted)
		}
	}
}
