package exceptions

import (
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

func TestExceptionViewReference(t *testing.T) {
	path := os.Getenv("EXCEPTION_VIEW_REFERENCE")
	if path == "" {
		t.Skip("run scripts/test-db.py exception-view")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Now      time.Time
		Include  string
		Expected map[string]any
	}
	if err := json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) == 0 {
		t.Fatal("no captured reference cases")
	}
	ctx := t.Context()
	conn, err := pgx.Connect(ctx, os.Getenv("PROPOSAL_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal("connect to test database")
	}
	defer func() { _ = conn.Close(ctx) }()
	tx, err := conn.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var database, schema string
	if err := tx.QueryRow(ctx, "SELECT current_database(),current_schema()").Scan(&database, &schema); err != nil || database != "garmin_test" || !strings.HasPrefix(schema, "go_parity_") {
		t.Fatal("expected isolated exception test schema")
	}
	for _, c := range cases {
		result, err := View(ctx, tx, c.Now, c.Include)
		if err != nil {
			t.Fatal(err)
		}
		encoded, err := json.Marshal(result)
		if err != nil {
			t.Fatal(err)
		}
		var got map[string]any
		if err := json.Unmarshal(encoded, &got); err != nil {
			t.Fatal(err)
		}
		if len(got) != len(c.Expected) {
			t.Fatal("unexpected dashboard fields")
		}
		for key, want := range c.Expected {
			if !reflect.DeepEqual(got[key], want) {
				t.Fatalf("%s %s %s\ngot %v\nwant %v", c.Now, c.Include, key, got[key], want)
			}
		}
	}
}
