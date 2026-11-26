package exportcli

import (
	"bytes"
	"os"
	"path/filepath"
	"regexp"
	"testing"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestModeGate(t *testing.T) {
	err := Run(t.Context(), nil, "", "test", []string{"synthetic.zip"}, &bytes.Buffer{})
	if err == nil || err.Error() != "real_mode_required" {
		t.Fatalf("unexpected mode gate: %v", err)
	}
}

// TestExportFixture is driven by scripts/test-db.py import-export.
func TestExportFixture(t *testing.T) {
	file := os.Getenv("EXPORT_FIXTURE")
	if file == "" {
		t.Skip("requires isolated comparison schema")
	}
	cfg, err := pgxpool.ParseConfig(os.Getenv("PROPOSAL_TEST_DATABASE_URL"))
	if err != nil || os.Getenv("APP_MODE") != "test" || cfg.ConnConfig.Database != "garmin_test" || cfg.ConnConfig.Host != "127.0.0.1" && cfg.ConnConfig.Host != "localhost" {
		t.Fatal("expected the synthetic integration database")
	}
	pool, err := pgxpool.NewWithConfig(t.Context(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var schema string
	if err := pool.QueryRow(t.Context(), "SELECT current_schema()").Scan(&schema); err != nil || !regexp.MustCompile(`^go_parity_[0-9a-f]{32}$`).MatchString(schema) {
		t.Fatal("expected a disposable schema")
	}
	args := []string{file}
	if os.Getenv("EXPORT_APPLY") == "1" {
		args = append(args, "--apply")
	}
	var out bytes.Buffer
	err = Run(t.Context(), pool, os.Getenv("PRIVATE_DIR"), "real", args, &out)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(os.Getenv("PRIVATE_DIR"), "fixture-result.json"), out.Bytes(), 0600); err != nil {
		t.Fatal(err)
	}
}
