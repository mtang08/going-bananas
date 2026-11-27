package backup

import (
	"bytes"
	"encoding/json"
	"io"
	"path/filepath"
	"testing"
)

func TestCommandChecksSettingsBeforeCreatingOutput(t *testing.T) {
	t.Setenv("APP_MODE", "test")
	t.Setenv("DATABASE_URL", "postgresql://fixture@127.0.0.1:1/synthetic_real")
	output := filepath.Join(t.TempDir(), "backup.tar.gz")
	var stderr bytes.Buffer
	if code := RunCommand(t.Context(), []string{"backup", output}, io.Discard, &stderr); code != 2 {
		t.Fatalf("got status %d, want 2", code)
	}
	var detail map[string]string
	if err := json.Unmarshal(stderr.Bytes(), &detail); err != nil || detail["error"] != "Database name must end with APP_MODE suffix" {
		t.Fatalf("unexpected stderr: %s", stderr.String())
	}
	if err := mustBeNew(output, "file exists"); err != nil {
		t.Fatal(err)
	}
}

func TestRestoreCommandKeepsCurrentDatabaseGuardWithEitherFlagOrder(t *testing.T) {
	t.Setenv("APP_MODE", "test")
	t.Setenv("DATABASE_URL", "postgresql+psycopg://fixture@127.0.0.1:1/synthetic_test")
	for _, args := range [][]string{
		{"restore", "fixture.tar.gz", "--target-database-name", "synthetic_test", "--target-private-dir", "somewhere"},
		{"restore", "fixture.tar.gz", "--target-private-dir", "somewhere", "--target-database-name", "synthetic_test"},
		{"restore", "--target-database-name=synthetic_test", "--target-private-dir", "somewhere", "fixture.tar.gz"},
	} {
		var stderr bytes.Buffer
		if code := RunCommand(t.Context(), args, io.Discard, &stderr); code != 2 ||
			stderr.String() != "{\"error\":\"restore_target_is_current_database\"}\n" {
			t.Fatalf("args %v: status %d, stderr %q", args, code, stderr.String())
		}
	}
}
