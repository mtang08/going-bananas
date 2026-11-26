package weeklyprojection

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

func TestProjectionPythonParity(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires disposable PostgreSQL runner")
	}
	cmd := exec.CommandContext(t.Context(), os.Getenv("DASHBOARD_REFERENCE_PYTHON"), "testdata/reference.py")
	output, err := cmd.Output()
	if err != nil {
		t.Fatalf("weekly projection reference failed: %v", err)
	}
	var cases []struct {
		Fixture    string
		Now        time.Time
		Projection map[string]any
	}
	if err := json.Unmarshal(output, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) != 5 {
		t.Fatal("incomplete Python reference")
	}
	conn, err := pgx.Connect(t.Context(), dsn)
	if err != nil {
		t.Fatal("connect to synthetic server")
	}
	defer func() { _ = conn.Close(context.Background()) }()
	tx, err := conn.Begin(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
	fixture := ""
	for _, c := range cases {
		if fixture != c.Fixture {
			fixture = c.Fixture
			raw, err := os.ReadFile("testdata/" + fixture)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := tx.Exec(t.Context(), string(raw)); err != nil {
				t.Fatal(err)
			}
		}
		p, err := Load(t.Context(), tx, c.Now)
		if err != nil {
			t.Fatal(err)
		}
		raw, err := json.Marshal(p)
		if err != nil {
			t.Fatal(err)
		}
		var got map[string]any
		if err := json.Unmarshal(raw, &got); err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(got, c.Projection) {
			t.Errorf("%s: Go %+v, Python %+v", c.Now, got, c.Projection)
		}
	}
}
