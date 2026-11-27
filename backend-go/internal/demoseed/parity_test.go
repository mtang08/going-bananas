package demoseed

import (
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestDemoSeedFixture(t *testing.T) {
	out := os.Getenv("DEMO_SEED_OUTPUT")
	if out == "" {
		t.Skip("run scripts/test-db.py demo-seed")
	}
	cfg, err := pgxpool.ParseConfig(os.Getenv("PROPOSAL_TEST_DATABASE_URL"))
	if err != nil || cfg.ConnConfig.Database != "garmin_test" || (cfg.ConnConfig.Host != "localhost" && cfg.ConnConfig.Host != "127.0.0.1") || fmt.Sprint(cfg.ConnConfig.Port) != os.Getenv("TEST_DATABASE_PORT") || os.Getenv("APP_MODE") != "test" {
		t.Fatal("expected a local synthetic database")
	}
	pool, err := pgxpool.NewWithConfig(t.Context(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var schema string
	if err = pool.QueryRow(t.Context(), "SELECT current_schema()").Scan(&schema); err != nil || !regexp.MustCompile("^go_parity_[0-9a-f]{32}$").MatchString(schema) {
		t.Fatal("expected disposable schema")
	}
	now, err := time.Parse(time.RFC3339, os.Getenv("DEMO_SEED_NOW"))
	if err != nil {
		t.Fatal(err)
	}
	totals, err := Seed(t.Context(), pool, os.Getenv("PRIVATE_DIR"), now)
	if err != nil {
		t.Fatal(err)
	}
	b, err := json.Marshal(totals)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(out, b, 0600); err != nil {
		t.Fatal(err)
	}
}
