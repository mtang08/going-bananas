package weeklydigest

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

func TestWeekPythonParity(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires disposable PostgreSQL dashboard runner")
	}
	ref, err := exec.CommandContext(t.Context(), os.Getenv("DASHBOARD_REFERENCE_PYTHON"), "testdata/reference.py").Output()
	if err != nil {
		t.Fatalf("Python digest reference: %v", err)
	}
	var expected []row
	if err := json.Unmarshal(ref, &expected); err != nil {
		t.Fatal(err)
	}
	conn, err := pgx.Connect(t.Context(), dsn)
	if err != nil {
		t.Fatal("open weekly fixture")
	}
	defer func() { _ = conn.Close(context.Background()) }()
	tx, err := conn.BeginTx(t.Context(), pgx.TxOptions{AccessMode: pgx.ReadOnly})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
	if _, err = tx.Exec(t.Context(), "SET LOCAL TIME ZONE 'Asia/Kathmandu'"); err != nil {
		t.Fatal(err)
	}
	for _, week := range expected {
		got, err := LoadWeek(t.Context(), tx, week["week_start"].(string), "2030-01-09", time.Date(2030, 1, 9, 18, 30, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		wire, err := json.Marshal(got)
		if err != nil {
			t.Fatal(err)
		}
		var actual row
		if err := json.Unmarshal(wire, &actual); err != nil {
			t.Fatal(err)
		}
		if len(actual) != len(week) {
			t.Fatal("week field count differs")
		}
		for k, v := range week {
			if !reflect.DeepEqual(v, actual[k]) {
				t.Errorf("%s %s: Python %v, Go %v", week["week_start"], k, v, actual[k])
			}
		}
	}
	if expected[0]["decision_follow_up"] == nil {
		t.Fatal("fixture missing reviewed session")
	}
}
