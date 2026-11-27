package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestGoWorkspaceWithoutLegacyTools(t *testing.T) {
	root := t.TempDir()
	for _, tool := range []string{"go", "node", "npm", "psql", "initdb", "pg_ctl", "pg_dump", "pg_restore", "createdb", "dropdb"} {
		if err := os.WriteFile(filepath.Join(root, tool), []byte("#!/bin/sh\nexit 1"), 0700); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("PATH", root)
	if err := os.WriteFile(filepath.Join(root, ".env"), []byte("synthetic-value-must-stay-hidden"), 0600); err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	if !check(&out, root) || !strings.Contains(out.String(), "uv: missing") || !strings.Contains(out.String(), ".env: present (values hidden)") || strings.Contains(out.String(), "synthetic-value") {
		t.Fatal("unexpected tool or configuration report")
	}
	if err := os.Remove(filepath.Join(root, "pg_dump")); err != nil {
		t.Fatal(err)
	}
	out.Reset()
	if check(&out, root) || !strings.Contains(out.String(), "pg_dump: missing") {
		t.Fatal("missing backup tool was not reported")
	}
}
