package snapshotreads

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"reflect"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

func TestActivityPythonParity(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires disposable PostgreSQL runner")
	}
	cmd := exec.CommandContext(t.Context(), os.Getenv("DASHBOARD_REFERENCE_PYTHON"), "testdata/activity_reference.py")
	reference, err := cmd.Output()
	if err != nil {
		t.Fatalf("Python activity fixture: %v", err)
	}
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
	conn, err := pgx.Connect(t.Context(), dsn)
	if err != nil {
		t.Fatal("connect to activity fixture")
	}
	defer func() { _ = conn.Close(context.Background()) }()
	tx, err := conn.BeginTx(t.Context(), pgx.TxOptions{AccessMode: pgx.ReadOnly})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
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
		t.Errorf("snapshot inputs differ\nGo: %s\nPython: %s", encoded, reference)
	}
}
