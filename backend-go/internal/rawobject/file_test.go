package rawobject

import (
	"os"
	"path/filepath"
	"testing"
)

func TestWriteConfinesDescendantSymlinks(t *testing.T) {
	demo := t.TempDir()
	other := t.TempDir()
	if err := os.Symlink(other, filepath.Join(demo, "raw")); err != nil {
		t.Fatal(err)
	}
	if err := Write(demo, "raw/aa/fixture.json", []byte("synthetic")); err == nil {
		t.Fatal("accepted a raw directory outside the workspace")
	}
	entries, err := os.ReadDir(other)
	if err != nil || len(entries) != 0 {
		t.Fatalf("outside directory changed: %v, %v", entries, err)
	}
}
