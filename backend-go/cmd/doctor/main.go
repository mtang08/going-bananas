// Command doctor checks the tools and files used by this checkout without opening the workspace.
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

func check(out io.Writer, root string) bool {
	ready := true
	var report strings.Builder
	// Go and Node build the app; the PostgreSQL utilities run local databases and backups.
	for _, tool := range []string{"go", "node", "npm", "psql", "initdb", "pg_ctl", "pg_dump", "pg_restore", "createdb", "dropdb"} {
		status := "available"
		if _, err := exec.LookPath(tool); err != nil {
			status = "missing"
			ready = false
		}
		fmt.Fprintf(&report, "%s: %s\n", tool, status)
	}
	legacy := "available"
	if _, err := exec.LookPath("uv"); err != nil {
		legacy = "missing (needed for historical Alembic migrations and Python checks)"
	}
	fmt.Fprintf(&report, "uv: %s\n", legacy)
	if _, err := os.Stat(filepath.Join(root, ".env")); err == nil {
		fmt.Fprintln(&report, ".env: present (values hidden)")
	} else {
		fmt.Fprintln(&report, ".env: not configured")
	}
	if _, err := os.Stat(filepath.Join(root, "running_coach_kb")); err == nil {
		fmt.Fprintln(&report, "Research KB: present")
	} else {
		fmt.Fprintln(&report, "Research KB: not installed; analytics does not require it")
	}
	_, err := io.WriteString(out, report.String())
	return ready && err == nil
}

func main() {
	root := flag.String("repo", ".", "repository root")
	flag.Parse()
	if flag.NArg() != 0 {
		flag.Usage()
		os.Exit(2)
	}
	if !check(os.Stdout, *root) {
		os.Exit(1)
	}
}
