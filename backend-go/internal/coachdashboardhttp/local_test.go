package coachdashboardhttp

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/coachdashboard"
)

func TestLocalHTTPExecutablePostgres(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires disposable PostgreSQL runner")
	}
	poolCfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatal("invalid dashboard test configuration")
	}
	poolCfg.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	pool, err := pgxpool.NewWithConfig(t.Context(), poolCfg)
	if err != nil {
		t.Fatal("connect to dashboard test database")
	}
	defer pool.Close()
	root := t.TempDir()
	cfg := LocalConfig{RepoRoot: root, PrivateDir: filepath.Join(root, "mode-data"), Mode: "demo", VitePort: "5173"}
	write := func(path string, data []byte, mode os.FileMode) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, data, mode); err != nil {
			t.Fatal(err)
		}
	}
	const reviewID = "223580c9-c13a-4712-9fd1-b17587ad591b"
	write(filepath.Join(cfg.PrivateDir, "coach-chat", "demo", "state.json"), []byte(`{"review":{"id":"`+reviewID+`","status":"idle","codex_thread_id":"private-fixture-thread","messages":[]},"receipts":{}}`), 0600)
	skill := filepath.Join(root, ".codex", "skills", "going-bananas-coach")
	for file, content := range map[string]string{"SKILL.md": "fixture skill\n", "references/coaching-workflows.md": "fixture workflow\n", "references/proposal-format.md": "fixture format\n"} {
		write(filepath.Join(skill, file), []byte(content), 0600)
	}
	python := os.Getenv("DASHBOARD_FIXTURE_PYTHON")
	if !filepath.IsAbs(python) {
		t.Fatal("fixture Python must be absolute")
	}
	instructions, err := coachdashboard.LoadInstructions(root)
	const references = "\n\nfixture skill\n\n\nfixture workflow\n\n\nfixture format\n"
	if err != nil || !strings.HasSuffix(instructions, references) {
		t.Fatal("missing ordered coaching references", err)
	}
	for _, clause := range []string{
		"Use it after the athlete agrees to the plan or explicitly authorizes publishing.",
		"report the pending status. The athlete applies it in the review page.",
		"accept, undo, or discard any proposal or calendar state through chat.",
	} {
		if !strings.Contains(instructions, clause) {
			t.Errorf("missing coaching instruction %q", clause)
		}
	}
	script, err := os.ReadFile("testdata/local_app_server.py")
	if err != nil {
		t.Fatal(err)
	}
	bin := filepath.Join(root, "bin")
	write(filepath.Join(bin, "codex"), append([]byte("#!"+python+"\n"), script...), 0700)
	t.Setenv("PATH", bin)
	var calls atomic.Int32
	handlers := coachdashboard.ToolHandlers{Active: func(ctx context.Context, tx pgx.Tx) (*coachdashboard.ActiveDraft, error) {
		var identity string
		err := tx.QueryRow(ctx, "SELECT id::text FROM coach_chat_reviews WHERE mode='demo' AND current").Scan(&identity)
		if err == nil && identity != reviewID {
			return nil, fmt.Errorf("unexpected review %q", identity)
		}
		calls.Add(1)
		return nil, err
	}}
	server := httptest.NewUnstartedServer(nil)
	defer server.Close()
	_, port, err := net.SplitHostPort(server.Listener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	cfg.Port = port
	skillFile := filepath.Join(skill, "SKILL.md")
	if err := os.Remove(skillFile); err != nil {
		t.Fatal(err)
	}
	local, err := NewLocal(t.Context(), pool, cfg, handlers)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = local.Shutdown(context.Background()) }()
	server.Config.Handler = local
	server.Start()
	call := func(method, suffix, body string) coachdashboard.View {
		t.Helper()
		req, err := http.NewRequestWithContext(t.Context(), method, server.URL+path+suffix, strings.NewReader(body))
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("X-Local-Request", "1")
		req.Header.Set("Content-Type", "application/json")
		resp, err := server.Client().Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = resp.Body.Close() }()
		raw, err := io.ReadAll(resp.Body)
		if err != nil || resp.StatusCode != 200 || bytes.Contains(raw, []byte("private-fixture-thread")) {
			t.Fatalf("HTTP %d: %v", resp.StatusCode, err)
		}
		var envelope struct{ Data coachdashboard.View }
		if err := json.Unmarshal(raw, &envelope); err != nil {
			t.Fatal(err)
		}
		return envelope.Data
	}
	v := call("GET", "", "")
	if v.ID == nil || *v.ID != reviewID || len(v.Messages) != 0 {
		t.Fatal("missing imported review")
	}
	const msg = `{"thread_id":"` + reviewID + `","client_message_id":"88e5a733-b032-43ff-8b9b-078672bdc07c","text":"Review the week","intent":"sunday_review"}`
	wait := func() coachdashboard.View {
		t.Helper()
		end := time.Now().Add(10 * time.Second)
		for {
			view := call("GET", "", "")
			if view.Status != "running" {
				return view
			}
			if time.Now().After(end) {
				t.Fatal("dashboard turn did not finish")
			}
			time.Sleep(5 * time.Millisecond)
		}
	}
	if auth := call("GET", "/auth", ""); auth.Status != "signed_in" {
		t.Fatal("missing skill blocked account status")
	}
	call("POST", "/messages", strings.Replace(msg, "88e5a733", "88e5a734", 1))
	if failed := wait(); failed.Status != "failed" || failed.Error == nil || failed.Error.Code != "turn_failed" || len(failed.Messages) != 1 || calls.Load() != 0 {
		t.Fatal("missing skill should retain the message and fail only the turn")
	}
	write(skillFile, []byte("fixture skill\n"), 0600)
	call("POST", "/messages", msg)
	v = wait()
	if v.Status != "idle" || len(v.Messages) != 3 || v.Messages[2].Text != "Fixture review complete." {
		t.Fatalf("turn failed: %s %v", v.Status, v.Error)
	}
	replay := call("POST", "/messages", msg)
	if len(replay.Messages) != 3 || replay.Status != "idle" || calls.Load() != 1 {
		t.Fatal("replay repeated synthetic turn")
	}
	write(skillFile, []byte("updated fixture skill\n"), 0600)
	call("POST", "/messages", strings.Replace(msg, "88e5a733", "88e5a735", 1))
	edited := wait()
	if edited.Status != "idle" || len(edited.Messages) != 5 || edited.Messages[4].Text != "Updated fixture review complete." {
		t.Fatal("turn did not use edited instructions", edited.Error)
	}
}
