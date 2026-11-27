package exportcli

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"regexp"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/replay"
	"github.com/mtang08/going-bananas/backend-go/internal/garmincli"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

func TestModeGate(t *testing.T) {
	err := Run(t.Context(), nil, "", "test", []string{"synthetic.zip"}, &bytes.Buffer{}, nil)
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
	if os.Getenv("EXPORT_SEED") == "1" {
		seedAPIRecords(t, pool)
		return
	}
	args := []string{file}
	if os.Getenv("EXPORT_APPLY") == "1" {
		args = append(args, "--apply")
	}
	actual := garmincli.SourceRefresh(func() time.Time { return time.Date(2026, 11, 16, 9, 0, 0, 0, time.UTC) }, refresh.Runs)
	var out bytes.Buffer
	err = Run(t.Context(), pool, os.Getenv("PRIVATE_DIR"), "real", args, &out, func(ctx context.Context, tx pgx.Tx, scope replay.RefreshScope) error {
		_, err := tx.Exec(ctx, "INSERT INTO fixture_export_refresh(scope) VALUES($1)", scope)
		if err != nil {
			return err
		}
		return actual(ctx, tx, scope)
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(os.Getenv("PRIVATE_DIR"), "fixture-result.json"), out.Bytes(), 0600); err != nil {
		t.Fatal(err)
	}
}

func seedAPIRecords(t *testing.T, pool *pgxpool.Pool) {
	t.Helper()
	inputs := map[string]garmin.Record{
		"activities": {
			"activityId": 1234, "ownerId": 777, "activityType": map[string]any{"typeKey": "running"},
			"startTimeGMT": "2026-11-13T08:00:00Z", "distance": 2000, "elapsedDuration": 300,
		},
		"hrv": {"userProfilePk": 777, "calendarDate": "2026-11-13", "lastNightAvg": 74},
	}
	err := pgx.BeginTxFunc(t.Context(), pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		for _, dataset := range []string{"activities", "hrv"} {
			_, err := replay.ApplyJobPage(t.Context(), tx, os.Getenv("PRIVATE_DIR"), dataset,
				"garmin-owner:777", []garmin.Record{inputs[dataset]}, time.Date(2026, 11, 13, 0, 0, 0, 0, time.UTC))
			if err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestCommandExitAndErrors(t *testing.T) {
	invalidPath := filepath.Join(t.TempDir(), "missing.zip")
	for _, tc := range []struct {
		name string
		mode string
		args []string
		err  string
	}{
		{"missing archive", "test", nil, usage + "\ngoing-bananas import-export: error: the following arguments are required: archive\n"},
		{"unrecognized flag", "test", []string{"fixture.zip", "--bogus"}, usage + "\ngoing-bananas import-export: error: unrecognized arguments: --bogus\n"},
		{"extra positional", "test", []string{"fixture.zip", "extra"}, usage + "\ngoing-bananas import-export: error: unrecognized arguments: extra\n"},
		{"mode guard", "test", []string{"fixture.zip"}, "{\"error\":\"real_mode_required\"}\n"},
		{"invalid path", "real", []string{invalidPath}, "{\"error\":\"invalid_export_archive\"}\n"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("APP_MODE", tc.mode)
			t.Setenv("DATABASE_URL", "postgresql://fixture@127.0.0.1:1/synthetic_"+tc.mode)
			var stdout, stderr bytes.Buffer
			if code := Command(t.Context(), tc.args, &stdout, &stderr, nil); code != 2 ||
				stdout.Len() != 0 || stderr.String() != tc.err {
				t.Fatalf("status %d, stdout %q, stderr %q", code, stdout.String(), stderr.String())
			}
		})
	}
}
