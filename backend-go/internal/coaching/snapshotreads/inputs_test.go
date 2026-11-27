package snapshotreads

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"reflect"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

func TestInputsPythonComposition(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires disposable dashboard test schema")
	}
	cmd := exec.CommandContext(t.Context(), os.Getenv("DASHBOARD_REFERENCE_PYTHON"), "testdata/inputs_reference.py")
	raw, err := cmd.Output()
	if err != nil {
		t.Fatal("Python snapshot composition reference failed:", err)
	}
	var reference struct {
		Expected             map[string]any
		Weeks                []map[string]any
		Confirmed, Omissions []map[string]any
	}
	if err := json.Unmarshal(raw, &reference); err != nil {
		t.Fatal(err)
	}
	conn, err := pgx.Connect(t.Context(), dsn)
	if err != nil {
		t.Fatal("open composition fixture")
	}
	defer func() { _ = conn.Close(context.Background()) }()
	tx, err := conn.BeginTx(t.Context(), pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
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
			t.Errorf("%s: Go %#v; Python %#v", key, actual[key], v)
		}
	}
	if out.RunningInterruption["activity_history_coverage"] != "complete" || out.RunningInterruption["latest_recorded_run"] == nil || len(out.ConfirmedStrengthSessions) == 0 {
		t.Fatal("composition fixture missing projected training context")
	}
}
