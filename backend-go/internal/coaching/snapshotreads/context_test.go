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

func TestContextPythonParity(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires the disposable dashboard PostgreSQL runner")
	}
	python := os.Getenv("DASHBOARD_REFERENCE_PYTHON")
	if python == "" {
		t.Fatal("runner must supply the backend interpreter")
	}
	const script = "testdata/context_reference.py"
	t.Cleanup(func() {
		if err := exec.Command(python, script, "cleanup").Run(); err != nil {
			t.Errorf("clean up synthetic context fixture: %v", err)
		}
	})
	want, err := exec.CommandContext(t.Context(), python, script).Output()
	if err != nil {
		t.Fatalf("Python context reference: %v", err)
	}
	ctx := t.Context()
	c, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatal("open synthetic database")
	}
	defer func() { _ = c.Close(context.Background()) }()
	tx, err := c.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadOnly})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
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
			t.Errorf("context %s differs from Python\nGo: %v\nPython: %v", key, a[key], wanted)
		}
	}
}
