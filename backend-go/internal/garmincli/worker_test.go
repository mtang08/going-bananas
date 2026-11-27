package garmincli

import (
	"context"
	"errors"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/replay"
	"io"
	"os"
	"path/filepath"
	"testing"
)

func TestOpenRequiresRealModeAndRefreshBeforeCredentials(t *testing.T) {
	for mode, want := range map[string]string{"real": "garmin_refresh_required", "demo": "real_mode_required"} {
		_, err := Open(t.Context(), mode, Config{})
		if err == nil || err.Error() != want {
			t.Fatalf("mode %q: %v", mode, err)
		}
	}
}

func TestStartupWaitsOnlyForMissingWorkerKey(t *testing.T) {
	dir := t.TempDir()
	key := filepath.Join(dir, "fixture-key")
	t.Setenv("GARMIN_KEY_FILE", key)
	t.Setenv("GARMIN_API_KEY", "")
	t.Setenv("GARMIN_PERSONAL_API_KEY", "")
	cfg := Config{Pool: &pgxpool.Pool{}, PrivateDir: dir, ReportFIT: func(error) {}, Refresh: func(context.Context, pgx.Tx, replay.RefreshScope) error { return nil }}
	calls := 0
	wait := func(context.Context) error { calls++; return context.Canceled }
	code, err := run(t.Context(), "real", cfg, []string{"sync"}, io.Discard, wait)
	if code != 1 || !errors.Is(err, errCredentialMissing) || calls != 0 {
		t.Fatalf("sync returned %d, %v, waited %d", code, err, calls)
	}
	code, err = run(t.Context(), "real", cfg, []string{"worker"}, io.Discard, wait)
	if code != 0 || err != nil || calls != 1 {
		t.Fatalf("worker returned %d, %v, waited %d", code, err, calls)
	}
	if err = os.WriteFile(key, []byte("synthetic-key"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = Open(t.Context(), "real", cfg); err != nil {
		t.Fatal(err)
	}
}
