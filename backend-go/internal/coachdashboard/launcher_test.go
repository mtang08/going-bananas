package coachdashboard

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

func TestLocalLauncherUsesIsolatedProfileAndEnvironment(t *testing.T) {
	root := t.TempDir()
	launcher, err := NewLocalLauncher(root, "test")
	if err != nil {
		t.Fatal(err)
	}
	launcher.executable = filepath.Join(root, "synthetic-codex")
	script := `#!/bin/sh
printf '%s\n' "$PWD" "$CODEX_HOME" "${DASHBOARD_LAUNCH_CANARY:-absent}" "$(umask)" "$@"
`
	if err := os.WriteFile(launcher.executable, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("DASHBOARD_LAUNCH_CANARY", "must not reach child")
	stream, err := launcher.Open(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	data, err := io.ReadAll(stream)
	if err != nil {
		t.Fatal(err)
	}
	if err := stream.Close(); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSuffix(string(data), "\n"), "\n")
	if len(lines) < 6 || lines[0] != launcher.Workspace() || lines[1] != launcher.home || lines[2] != "absent" || strings.TrimLeft(lines[3], "0") != "77" || lines[4] != "app-server" || !slices.Equal(lines[5:], launchFlags) {
		t.Fatalf("unexpected synthetic launch (%d arguments)", len(lines))
	}
	for _, required := range []string{`approval_policy="never"`, `permissions.going_bananas_coach={filesystem={":root"="deny"},network={enabled=false}}`, "mcp_servers={}", `web_search="disabled"`, `forced_login_method="chatgpt"`} {
		if !slices.Contains(lines[5:], required) {
			t.Fatalf("missing restricted launch setting %s", required)
		}
	}
	for _, feature := range []string{"shell_tool", "unified_exec", "apps", "plugins", "browser_use", "computer_use", "hooks", "multi_agent"} {
		idx := slices.Index(lines, feature)
		if idx < 1 || lines[idx-1] != "--disable" {
			t.Fatalf("missing restriction for %s", feature)
		}
	}
	for _, p := range []string{launcher.home, launcher.workspace} {
		s, err := os.Stat(p)
		if err != nil || s.Mode().Perm() != 0700 {
			t.Fatal("private directory permissions")
		}
	}
}

func TestLocalLauncherRejectsRedirectedPrivateDirectory(t *testing.T) {
	root := t.TempDir()
	if err := os.Symlink(t.TempDir(), filepath.Join(root, "private")); err != nil {
		t.Fatal(err)
	}
	l, err := NewLocalLauncher(root, "test")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = l.Open(context.Background()); err == nil {
		t.Fatal("followed symlink")
	}
	if _, err := NewLocalLauncher(root, "../real"); err == nil {
		t.Fatal("accepted invalid mode")
	}
}

func TestAuthStatusThroughSyntheticExecutable(t *testing.T) {
	root := t.TempDir()
	l, err := NewLocalLauncher(root, "demo")
	if err != nil {
		t.Fatal(err)
	}
	l.executable = filepath.Join(root, "synthetic-codex")
	script := `#!/bin/sh
IFS= read -r line || exit 1
echo '{"id":1,"result":{}}'
IFS= read -r line || exit 1
IFS= read -r line || exit 1
echo '{"id":2,"result":{"account":{"type":"chatgpt"}}}'
`
	if err := os.WriteFile(l.executable, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	auth := NewAuth(l.Open)
	if view := auth.Status(t.Context()); view.Status != "signed_in" {
		t.Fatal(view.Error)
	}
}
