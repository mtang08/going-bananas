package exceptions

import (
	"bytes"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"github.com/jackc/pgx/v5"
)

func TestPythonInputs(t *testing.T) {
	path := os.Getenv("DETECTOR_REFERENCE")
	if path == "" {
		t.Skip("run scripts/test-db.py exception-inputs")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cases []DetectionInputs
	if err := json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	ctx := t.Context()
	conn, err := pgx.Connect(ctx, os.Getenv("DASHBOARD_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal("connect to detector test database")
	}
	defer func() { _ = conn.Close(ctx) }()
	tx, err := conn.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var db, schema string
	if err := tx.QueryRow(ctx, "SELECT current_database(),current_schema()").Scan(&db, &schema); err != nil || db != "garmin_test" || !strings.HasPrefix(schema, "go_parity_") {
		t.Fatal("expected disposable detector schema")
	}
	for _, want := range cases {
		got, err := LoadInputs(ctx, tx, want.Now)
		if err != nil {
			t.Fatal(err)
		}
		a, err := json.Marshal(want)
		if err != nil {
			t.Fatal(err)
		}
		b, err := json.Marshal(got)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(a, b) {
			var expected, actual map[string]json.RawMessage
			if err := json.Unmarshal(a, &expected); err != nil {
				t.Fatal(err)
			}
			if err := json.Unmarshal(b, &actual); err != nil {
				t.Fatal(err)
			}
			for key, value := range expected {
				if !bytes.Equal(value, actual[key]) {
					t.Errorf("%s %s got %s want %s", want.Today, key, actual[key], value)
				}
			}
		}
	}
}
