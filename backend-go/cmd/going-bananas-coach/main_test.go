package main

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/google/uuid"
)

func invoke(t *testing.T, want int, args ...string) object {
	t.Helper()
	var out, stderr bytes.Buffer
	if got := run(t.Context(), args, &out, &stderr); got != want {
		t.Fatalf("%s exit %d, expected %d, stderr %s", args[0], got, want, stderr.String())
	}
	var v object
	if out.Len() == 0 {
		out = stderr
	} else if stderr.Len() != 0 {
		t.Fatal("unexpected stderr")
	}
	if err := json.Unmarshal(out.Bytes(), &v); err != nil {
		t.Fatal(err)
	}
	return v
}
func TestCLIFileAndQueryValidation(t *testing.T) {
	if v := invoke(t, 2, "query", "calendar_diff", "--from", "0"); v["message"] != "--to required" {
		t.Fatal(v)
	}
	if v := invoke(t, 2, "submit", "--file", filepath.Join(t.TempDir(), "missing")); v["status"] != "invalid" || v["proposal_id"] != nil {
		t.Fatal(v)
	}
}
func TestPythonSchema(t *testing.T) {
	python := os.Getenv("DASHBOARD_REFERENCE_PYTHON")
	if python == "" {
		t.Skip("requires Python reference")
	}
	cmd := exec.CommandContext(t.Context(), python, "-m", "app.cli", "coach", "schema")
	cmd.Dir = "../../../backend"
	raw, err := cmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	var want object
	if err := json.Unmarshal(raw, &want); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(invoke(t, 0, "schema"), want) {
		t.Fatal("CLI schema differs from Python")
	}
}
func TestSyntheticCLI(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires migrated synthetic database")
	}
	t.Setenv("DATABASE_URL", dsn)
	t.Setenv("APP_MODE", "test")
	t.Setenv("PGOPTIONS", "-c default_transaction_read_only=on")
	t.Setenv("GB_MODE_ROOT", "../../..")
	if v := invoke(t, 0, "query", "calendar_diff", "--from", "0", "--to", "0"); v["query"] != "calendar_diff" {
		t.Fatal(v)
	}
	if v := invoke(t, 0, "query", "long_run_history", "--start", "2023-01-01", "--end", "2023-12-31"); v["query"] != "long_run_history" {
		t.Fatal(v)
	}
	if v := invoke(t, 4, "query", "activity_execution", "--activity-id", uuid.NewString()); v["error"] != "activity_not_found" {
		t.Fatal(v)
	}
	if v := invoke(t, 0, "snapshot", "--operation", "review_rolling_plan", "--as-of", "2023-01-02"); v["snapshot_id"] == nil {
		t.Fatal("missing snapshot id")
	}
	file := filepath.Join(t.TempDir(), "proposal.json")
	if err := os.WriteFile(file, []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	if v := invoke(t, 2, "submit", "--file", file); v["status"] != "invalid" {
		t.Fatal(v)
	}
	if v := invoke(t, 2, "revise", uuid.NewString(), "--expected-revision", "1", "--reason", "Revise", "--file", file); v["status"] != "invalid" {
		t.Fatal(v)
	}
}
