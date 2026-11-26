package snapshotreads

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"reflect"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

func TestFeedbackPythonParity(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires the disposable PostgreSQL dashboard runner")
	}
	python := os.Getenv("DASHBOARD_REFERENCE_PYTHON")
	if python == "" {
		t.Fatal("runner must supply its backend Python interpreter")
	}
	cmd := exec.CommandContext(t.Context(), python, "testdata/feedback_reference.py")
	// Keep diagnostics separate from the reference JSON. Connection strings can be
	// present in tracebacks, so report only the exception type for failures.
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	reference, err := cmd.Output()
	if err != nil {
		lines := bytes.Split(bytes.TrimSpace(stderr.Bytes()), []byte("\n"))
		kind, _, _ := bytes.Cut(lines[len(lines)-1], []byte(":"))
		t.Fatalf("Python feedback reference: %v (%s)", err, kind)
	}

	conn, err := pgx.Connect(t.Context(), dsn)
	if err != nil {
		t.Fatal("connect to feedback fixture")
	}
	defer conn.Close(context.Background())
	tx, err := conn.BeginTx(t.Context(), pgx.TxOptions{AccessMode: pgx.ReadOnly})
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(context.Background())
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
		t.Errorf("feedback differs from Python\nGo: %s\nPython: %s", gotJSON, reference)
	}
}
