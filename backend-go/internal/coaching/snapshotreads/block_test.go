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

func TestBlockPythonParity(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires disposable dashboard test schema")
	}
	conn, err := pgx.Connect(t.Context(), dsn)
	if err != nil {
		t.Fatal("connect to dashboard schema")
	}
	defer func() { _ = conn.Close(context.Background()) }()
	for _, phase := range []string{"event", "manual", "pending", "missed", "trial", "not_set", "archived"} {
		asOf := "2026-11-01"
		if phase == "missed" {
			asOf = "2026-11-07"
		}
		cmd := exec.CommandContext(t.Context(), os.Getenv("DASHBOARD_REFERENCE_PYTHON"), "testdata/block_reference.py", phase)
		ref, err := cmd.Output()
		if err != nil {
			t.Fatalf("%s: Python fixture failed: %v", phase, err)
		}
		var got Block
		err = pgx.BeginTxFunc(t.Context(), conn, pgx.TxOptions{AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
			var err error
			got, err = LoadBlock(t.Context(), tx, asOf)
			return err
		})
		if err != nil {
			t.Fatal(err)
		}
		encoded, err := json.Marshal(got)
		if err != nil {
			t.Fatal(err)
		}
		var actual, expected map[string]any
		if err := json.Unmarshal(encoded, &actual); err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(ref, &expected); err != nil {
			t.Fatal(err)
		}
		for k, v := range expected {
			if !reflect.DeepEqual(actual[k], v) {
				t.Fatalf("%s %s: Go %#v; Python %#v", phase, k, actual[k], v)
			}
		}
	}
}
