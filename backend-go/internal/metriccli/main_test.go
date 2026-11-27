package metriccli

import (
	"bytes"
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestPythonCommands(t *testing.T) {
	path := os.Getenv("METRICS_CLI_CASES")
	if path == "" {
		t.Skip("requires isolated Python command corpus")
	}
	cfg, err := pgxpool.ParseConfig(os.Getenv("PROPOSAL_TEST_DATABASE_URL"))
	if err != nil || os.Getenv("APP_MODE") != "test" || cfg.ConnConfig.Database != "garmin_test" || !strings.HasPrefix(os.Getenv("PGOPTIONS"), "-csearch_path=go_parity_") {
		t.Fatal("expected disposable test database")
	}
	ctx := t.Context()
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	buf, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Query string
		Cases []struct {
			Args            []string
			Response, State map[string]any
		}
	}
	if err = json.Unmarshal(buf, &fixture); err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 11, 26, 12, 0, 0, 0, time.UTC)
	for _, item := range fixture.Cases {
		var out bytes.Buffer
		err := run(ctx, pool, item.Args, now, &out)
		got := map[string]any{}
		if err != nil {
			got["error"] = err.Error()
		} else if err = json.Unmarshal(out.Bytes(), &got); err != nil {
			t.Fatal(err)
		}
		delete(got, "ms")
		if !reflect.DeepEqual(got, item.Response) {
			t.Fatalf("%v response: %v want %v", item.Args, got, item.Response)
		}
		var state map[string]any
		if err = pool.QueryRow(ctx, fixture.Query).Scan(&state); err != nil {
			t.Fatal(err)
		}
		for k, v := range item.State {
			if !reflect.DeepEqual(state[k], v) {
				if a, ok := state[k].([]any); ok {
					if b, ok := v.([]any); ok {
						for i := 0; i < len(a) && i < len(b); i++ {
							if !reflect.DeepEqual(a[i], b[i]) {
								t.Fatalf("%v %s item %d: %v want %v", item.Args, k, i, a[i], b[i])
							}
						}
						t.Fatalf("%v %s len %d want %d", item.Args, k, len(a), len(b))
					}
				}
				t.Fatalf("%v %s: %v want %v", item.Args, k, state[k], v)
			}
		}
	}
}
