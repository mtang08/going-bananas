package demoseed

import (
	"io"
	"os"
	"path/filepath"
	"testing"
)

func TestRejectsWrongModeDatabaseOrPrivateRootBeforeConnecting(t *testing.T) {
	parent := t.TempDir()
	other := filepath.Join(parent, "other")
	if err := os.Mkdir(other, 0700); err != nil {
		t.Fatal(err)
	}
	alias := filepath.Join(parent, "demo")
	if err := os.Symlink(other, alias); err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct{ mode, database, dir, want string }{
		{"test", "synthetic_test", alias, "demo_mode_required"},
		{"demo", "synthetic_test", alias, "demo_database_required"},
		{"demo", "synthetic_demo", "", "demo_private_dir_required"},
		{"demo", "synthetic_demo", alias, "expected demo private directory"},
	} {
		t.Setenv("APP_MODE", tc.mode)
		t.Setenv("DATABASE_URL", "postgresql://127.0.0.1:1/"+tc.database)
		t.Setenv("PRIVATE_DIR", tc.dir)
		if err := Run(t.Context(), nil, io.Discard); err == nil || err.Error() != tc.want {
			t.Fatalf("got %v, want %s", err, tc.want)
		}
	}
}
