package snapshotreads

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"reflect"
	"testing"

	"github.com/jackc/pgx/v5"
)

func TestPlanningPythonParity(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires synthetic dashboard runner")
	}
	want, err := exec.CommandContext(t.Context(), os.Getenv("DASHBOARD_REFERENCE_PYTHON"), "testdata/planning_reference.py").Output()
	if err != nil {
		t.Fatalf("Python planning fixture: %v", err)
	}
	conn, err := pgx.Connect(t.Context(), dsn)
	if err != nil {
		t.Fatal("opening synthetic database")
	}
	defer func() { _ = conn.Close(context.Background()) }()
	err = pgx.BeginFunc(t.Context(), conn, func(tx pgx.Tx) error {
		result, err := LoadPlanning(t.Context(), tx, "2026-03-08")
		if err != nil {
			return err
		}
		raw, err := json.Marshal(result)
		if err != nil {
			return err
		}
		var candidate, reference map[string][]map[string]any
		if err := json.Unmarshal(raw, &candidate); err != nil {
			return err
		}
		if err := json.Unmarshal(want, &reference); err != nil {
			return err
		}
		if !reflect.DeepEqual(reference, candidate) {
			t.Error("planning projections differ from Python")
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}
