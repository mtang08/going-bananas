package garmincli

import (
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"testing"
	"time"
)

type fileSource struct{ dir string }

func (s fileSource) DownloadActivity(_ context.Context, id string) ([]byte, error) {
	if id == "3" {
		return nil, &garmin.RemoteError{StatusCode: 404}
	}
	if id == "4" {
		return []byte("invalid archive"), nil
	}
	if id != "1" && id != "2" {
		return nil, &garmin.RemoteError{StatusCode: 503}
	}
	return os.ReadFile(filepath.Join(s.dir, id+".zip"))
}
func TestFITCommandFixture(t *testing.T) {
	raw := os.Getenv("FIT_CLI_ARGS")
	if raw == "" {
		t.Skip("requires migrated schema")
	}
	cfg, err := pgxpool.ParseConfig(os.Getenv("PROPOSAL_TEST_DATABASE_URL"))
	if err != nil || cfg.ConnConfig.Database != "garmin_test" || (cfg.ConnConfig.Host != "localhost" && cfg.ConnConfig.Host != "127.0.0.1") || os.Getenv("APP_MODE") != "test" {
		t.Fatal("expected synthetic database")
	}
	ctx := t.Context()
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var schema string
	if err := pool.QueryRow(ctx, "SELECT current_schema()").Scan(&schema); err != nil || !regexp.MustCompile("^go_parity_[0-9a-f]{32}$").MatchString(schema) {
		t.Fatal("expected disposable schema")
	}
	var args []string
	if err := json.Unmarshal([]byte(raw), &args); err != nil {
		t.Fatal(err)
	}
	dir := os.Getenv("PRIVATE_DIR")
	f, err := os.Create(filepath.Join(dir, "result.json"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	now := func() time.Time { return time.Date(2026, 11, 16, 9, 0, 0, 0, time.UTC) }
	err = RunFITCommand(ctx, "real", Config{Pool: pool, PrivateDir: dir, Now: now, Refresh: SourceRefresh(now, refresh.Runs)}, args, f, fileSource{dir})
	if err != nil {
		t.Fatal(err)
	}
}

func TestFITBackfillRejectsModeAndFutureDateBeforeOpeningSource(t *testing.T) {
	now := func() time.Time { return time.Date(2026, 11, 16, 12, 0, 0, 0, time.Local) }
	cfg := Config{Now: now, Refresh: SourceRefresh(now, refresh.Runs)}
	for _, tc := range []struct{ mode, since, want string }{{"demo", "2026-11-16", "real_mode_required"}, {"real", "2026-11-17", "invalid_date_window"}} {
		err := RunFITCommand(t.Context(), tc.mode, cfg, []string{"fit-backfill", "--since", tc.since}, io.Discard, nil)
		if err == nil || err.Error() != tc.want {
			t.Fatalf("got %v, want %s", err, tc.want)
		}
	}
}
