package drilldowns

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/coachdashboard"
)

//go:embed testdata/seed.sql
var seed string

//go:embed testdata/preview.sql
var seedPreview string

func TestQueryPythonParity(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires the synthetic PostgreSQL runner")
	}
	cmd := exec.CommandContext(t.Context(), os.Getenv("DASHBOARD_REFERENCE_PYTHON"), "testdata/reference.py")
	expected, err := cmd.Output()
	if err != nil {
		t.Fatalf("Python drill-down reference: %v", err)
	}
	var cases [][]json.RawMessage
	if err = json.Unmarshal(expected, &cases); err != nil {
		t.Fatal(err)
	}
	ctx := t.Context()
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatal("connect to synthetic database")
	}
	defer func() { _ = conn.Close(context.Background()) }()
	tx, err := conn.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
	manifest, err := os.ReadFile("../evidence/metric_identities.json")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = tx.Exec(ctx, strings.ReplaceAll(seed, "@IDENTITIES@", string(manifest))); err != nil {
		t.Fatal(err)
	}
	r := Reader{Now: func() time.Time { return time.Date(2026, 11, 5, 12, 0, 0, 0, time.UTC) }}
	previewed := false
	for _, tc := range cases {
		if len(tc) > 2 && !previewed {
			if _, err := tx.Exec(ctx, seedPreview); err != nil {
				t.Fatal(err)
			}
			previewed = true
		}
		var args object
		var want any
		if err = json.Unmarshal(tc[0], &args); err != nil {
			t.Fatal(err)
		}
		if err = json.Unmarshal(tc[1], &want); err != nil {
			t.Fatal(err)
		}
		value, err := r.Query(ctx, tx, args)
		if err != nil {
			t.Fatalf("%v: %v", args, err)
		}
		gotJSON, err := json.Marshal(value)
		if err != nil {
			t.Fatal(err)
		}
		var got any
		if err = json.Unmarshal(gotJSON, &got); err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("%s: Go %s; Python %s", args["name"], gotJSON, tc[1])
		}
	}
	const id = "00000000-0000-0000-0000-000000000001"
	for _, test := range []struct {
		args object
		code string
	}{
		{object{"name": "calendar_diff", "from_version": "2147483648", "to_version": 0}, "calendar_version_not_found"},
		{object{"name": "calendar_diff", "from_version": 0, "to_version": 8}, "calendar_version_not_found"},
		{object{"name": "activity_execution", "activity_id": "00000000-0000-0000-0000-000000000010"}, "activity_not_found"},
		{object{"name": "explain_metric", "result_id": "00000000-0000-0000-0000-000000000010"}, "metric_result_not_found"},
	} {
		_, err := r.Query(ctx, tx, test.args)
		var failure *coachdashboard.ToolFailure
		if !errors.As(err, &failure) || failure.Code != test.code {
			t.Fatalf("%v: %v", test.args, err)
		}
	}
	// A row can still be marked current when its method's configuration changes.
	// Read it through the calculator, and leave persisted metric history intact.
	if _, err = tx.Exec(ctx, "UPDATE metric_results SET config_hash='superseded' WHERE metric_id='long_run_exposure'"); err != nil {
		t.Fatal(err)
	}
	lookups := 0
	r.Preview = func(_ context.Context, same pgx.Tx, metric, subject string, _ time.Time) (object, error) {
		if same != tx || metric != "long_run_exposure" || subject != id {
			t.Fatal("incorrect preview request")
		}
		lookups++
		return object{"id": nil, "value": object{"classification": "long"}}, nil
	}
	res, err := r.Query(ctx, tx, object{"name": "long_run_history", "start": "2026-11-02", "end": "2026-11-02"})
	if err != nil || lookups != 1 || len(res.([]object)) != 1 || res.([]object)[0]["id"] != nil {
		t.Fatalf("stale preview %v %v", res, err)
	}
	var hash string
	if err = tx.QueryRow(ctx, "SELECT config_hash FROM metric_results WHERE metric_id='long_run_exposure'").Scan(&hash); err != nil || hash != "superseded" {
		t.Fatal("preview changed metric history", err)
	}

}
