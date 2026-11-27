package snapshotreads

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

func TestInputsComposition(t *testing.T) {
	tx, raw := snapshotFixture(t, "inputs")
	var reference struct {
		Expected             map[string]any
		Weeks                []map[string]any
		Confirmed, Omissions []map[string]any
	}
	if err := json.Unmarshal(raw, &reference); err != nil {
		t.Fatal(err)
	}
	const date = "2027-03-14"
	const operation = "review_rolling_plan"
	now := time.Date(2027, 3, 14, 14, 0, 0, 0, time.UTC)
	reads := InputReaders{
		Week: func(_ context.Context, transaction pgx.Tx, start, asOf string, instant time.Time) (map[string]any, error) {
			if tx != transaction || asOf != date || !instant.Equal(now) {
				return nil, errors.New("wrong weekly read context")
			}
			for _, w := range reference.Weeks {
				if w["week_start"] == start {
					return w, nil
				}
			}
			return nil, errors.New("incorrect Monday requested")
		},
		Strength: func(_ context.Context, transaction pgx.Tx, op, asOf string, instant time.Time) (StrengthInputs, error) {
			if tx != transaction || asOf != date || op != operation || !instant.Equal(now) {
				return StrengthInputs{}, errors.New("wrong lifecycle read context")
			}
			return StrengthInputs{reference.Confirmed, reference.Omissions}, nil
		},
	}
	out, err := LoadInputs(t.Context(), tx, operation, date, now, reads)
	if err != nil {
		t.Fatal(err)
	}
	encoded, err := json.Marshal(out)
	if err != nil {
		t.Fatal(err)
	}
	var actual map[string]any
	if err := json.Unmarshal(encoded, &actual); err != nil {
		t.Fatal(err)
	}
	if len(actual) != len(reference.Expected) {
		t.Fatalf("got %d fields, want %d", len(actual), len(reference.Expected))
	}
	for key, v := range reference.Expected {
		if !reflect.DeepEqual(actual[key], v) {
			t.Errorf("%s: got %#v; want %#v", key, actual[key], v)
		}
	}
	if out.RunningInterruption["activity_history_coverage"] != "complete" || out.RunningInterruption["latest_recorded_run"] == nil || len(out.ConfirmedStrengthSessions) == 0 {
		t.Fatal("composition fixture missing projected training context")
	}
}
