package metriccli

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestMetricCommands(t *testing.T) {
	if os.Getenv("PROPOSAL_TEST_DATABASE_URL") == "" {
		t.Skip("run the metrics-cli PostgreSQL check")
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
	buf, err := os.ReadFile("testdata/commands.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Query string
		Cases []struct {
			Args        []string
			Response    map[string]any
			StateSHA256 string `json:"state_sha256"`
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
		// Pin the durable result after every preview, apply, retry and failure.
		data, err := json.Marshal(state)
		if err != nil {
			t.Fatal(err)
		}
		if got := fmt.Sprintf("%x", sha256.Sum256(data)); got != item.StateSHA256 {
			t.Fatalf("%v: unexpected persisted state (%s); got %s", item.Args, got, data)
		}
	}
}
