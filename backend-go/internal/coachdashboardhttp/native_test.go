package coachdashboardhttp

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/coachdashboard"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/protocol"
)

// Lease an independent migrated calendar. Other HTTP and digest cases can use
// their fixtures without sharing pending proposals or changing its accepted head.
func nativePool(t *testing.T, dsn, python string) *pgxpool.Pool {
	t.Helper()
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatal("invalid synthetic connection")
	}
	// Testing cancels t.Context before cleanup. Keep the Python fixture alive
	// until EOF so its migration context can drop this private schema.
	lifetime, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	t.Cleanup(cancel)
	cmd := exec.CommandContext(lifetime, python, "testdata/native_fixture.py")
	ready, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	keepAlive, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_ = keepAlive.Close()
		if err := cmd.Wait(); err != nil {
			t.Errorf("native fixture process: %v", err)
		}
	})
	scanner := bufio.NewScanner(ready)
	schema := ""
	validSchema := regexp.MustCompile(`^go_parity_[a-f0-9]{32}$`)
	for scanner.Scan() {
		if value, ok := strings.CutPrefix(scanner.Text(), "READY "); ok && validSchema.MatchString(value) {
			schema = value
			break
		}
	}
	if schema == "" {
		t.Fatal("native fixture did not initialize", scanner.Err())
	}
	cfg.ConnConfig.RuntimeParams["search_path"] = schema
	cfg.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	pool, err := pgxpool.NewWithConfig(t.Context(), cfg)
	if err != nil {
		t.Fatal("connect to native fixture")
	}
	t.Cleanup(pool.Close)
	return pool
}

func TestNativeHTTPAgreementCreatesOnlyPendingProposal(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires disposable PostgreSQL runner")
	}
	python := os.Getenv("DASHBOARD_REFERENCE_PYTHON")
	pool := nativePool(t, dsn, python)
	root := t.TempDir()
	repo, err := filepath.Abs("../../..")
	if err != nil {
		t.Fatal(err)
	}
	// Copy only committed skill and KB material. The launcher and its synthetic
	// profile live entirely in this test's temporary directory.
	for _, rel := range []string{".codex/skills/going-bananas-coach", "running_coach_kb"} {
		dst := filepath.Join(root, rel)
		if err := os.MkdirAll(filepath.Dir(dst), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.CopyFS(dst, os.DirFS(filepath.Join(repo, rel))); err != nil {
			t.Fatal(err)
		}
	}
	bin := filepath.Join(root, "bin")
	if err := os.Mkdir(bin, 0700); err != nil {
		t.Fatal(err)
	}
	script, err := os.ReadFile("testdata/native_app_server.py")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(bin, "codex"), append([]byte("#!"+python+"\n"), script...), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin)

	start := func() (*httptest.Server, func()) {
		t.Helper()
		s := httptest.NewUnstartedServer(nil)
		_, port, err := net.SplitHostPort(s.Listener.Addr().String())
		if err != nil {
			t.Fatal(err)
		}
		cfg := LocalConfig{RepoRoot: root, PrivateDir: filepath.Join(root, "fixture"), Mode: "test", Port: port, VitePort: "5173", Now: func() time.Time { return time.Date(2026, 11, 16, 15, 0, 0, 0, time.UTC) }}
		local, err := NewNative(t.Context(), pool, cfg)
		if err != nil {
			s.Close()
			t.Fatal(err)
		}
		s.Config.Handler = local
		s.Start()
		closeServer := sync.OnceFunc(func() {
			s.Close()
			if err := local.Shutdown(context.Background()); err != nil {
				t.Error(err)
			}
		})
		t.Cleanup(closeServer)
		return s, closeServer
	}
	call := func(s *httptest.Server, method, suffix string, input any) coachdashboard.View {
		t.Helper()
		raw, err := json.Marshal(input)
		if err != nil {
			t.Fatal(err)
		}
		req, err := http.NewRequestWithContext(t.Context(), method, s.URL+path+suffix, strings.NewReader(string(raw)))
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("X-Local-Request", "1")
		req.Header.Set("Content-Type", "application/json")
		res, err := s.Client().Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = res.Body.Close() }()
		data, err := io.ReadAll(res.Body)
		if err != nil {
			t.Fatal(err)
		}
		if res.StatusCode != 200 {
			t.Fatalf("native HTTP status: %d, %s", res.StatusCode, data)
		}
		var envelope struct{ Data coachdashboard.View }
		if err := json.Unmarshal(data, &envelope); err != nil {
			t.Fatal(err)
		}
		return envelope.Data
	}
	wait := func(s *httptest.Server) coachdashboard.View {
		t.Helper()
		until := time.Now().Add(20 * time.Second)
		for {
			view := call(s, "GET", "", nil)
			if view.Status != "running" {
				if view.Status != "idle" {
					t.Fatalf("native turn %s: %v", view.Status, view.Error)
				}
				return view
			}
			if time.Now().After(until) {
				t.Fatal("native turn timed out")
			}
			time.Sleep(10 * time.Millisecond)
		}
	}
	s, closeFirst := start()
	// A damaged KB is a recoverable tool result. Restore the synthetic copy
	// and continue the same review to verify the transport survived.
	guide := filepath.Join(root, "running_coach_kb", "COACHING_GUIDE.md")
	original, err := os.ReadFile(guide)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(guide, []byte("Synthetic unverified KB change."), 0600); err != nil {
		t.Fatal(err)
	}
	call(s, "POST", "/messages", map[string]any{"client_message_id": uuid.NewString(), "text": "Could you review my running?"})
	failed := wait(s)
	if len(failed.Messages) != 2 || failed.Messages[1].Text != "Snapshot error: knowledge_unavailable" || failed.ProposalID != nil {
		t.Fatalf("expected recoverable knowledge error: %+v", failed)
	}
	if err := os.WriteFile(guide, original, 0600); err != nil {
		t.Fatal(err)
	}
	discussion := map[string]any{"client_message_id": uuid.NewString(), "text": "Could we add five minutes to my next easy run?"}
	call(s, "POST", "/messages", discussion)
	first := wait(s)
	closeFirst()
	if first.ID == nil || len(first.Messages) != 4 || !strings.Contains(first.Messages[3].Text, "35 minutes") || first.ProposalID != nil {
		t.Fatalf("unexpected discussion: %+v", first)
	}
	s, closeSecond := start()
	defer closeSecond()
	agreement := map[string]any{"thread_id": *first.ID, "client_message_id": uuid.NewString(), "text": "Yes, please save the 35-minute easy run for my review."}
	call(s, "POST", "/messages", agreement)
	pending := wait(s)
	if pending.ProposalID == nil || pending.ProposalRevision == nil || *pending.ProposalRevision != 1 || len(pending.Messages) != 6 || !strings.Contains(pending.Messages[5].Text, "/#proposal/"+*pending.ProposalID) {
		t.Fatalf("expected pending review: %+v", pending)
	}
	replay := call(s, "POST", "/messages", agreement)
	if replay.ProposalID == nil || *replay.ProposalID != *pending.ProposalID || replay.Status != "idle" || len(replay.Messages) != 6 {
		t.Fatal("replay repeated agreement")
	}

	var head, duration, count, before, after int
	var status string
	err = pool.QueryRow(t.Context(), `SELECT (SELECT calendar_head_version FROM app_state WHERE id=1),
 (SELECT planned_duration_s FROM calendar_session_revisions WHERE kind='run' ORDER BY revision DESC LIMIT 1),
 (SELECT count(*) FROM coach_proposals),p.status,(c.before->>'planned_duration_s')::int,(c.after->>'planned_duration_s')::int
 FROM coach_proposals p JOIN coach_proposal_changes c ON c.proposal_id=p.id AND c.change_id='c1' AND c.decision='pending' WHERE p.id=$1`, *pending.ProposalID).Scan(&head, &duration, &count, &status, &before, &after)
	if err != nil || head != 1 || duration != 1800 || count != 1 || status != "pending" || before != 1800 || after != 2100 {
		t.Fatalf("proposal/calendar mismatch: %d %d %d %s %v", head, duration, count, status, err)
	}
}

func TestNativeProposalSchemaPythonParity(t *testing.T) {
	python := os.Getenv("DASHBOARD_REFERENCE_PYTHON")
	if python == "" {
		t.Skip("requires Python reference environment")
	}
	p, err := filepath.Abs("../../../backend")
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.CommandContext(t.Context(), python, "-c", "import json,sys; sys.path.insert(0,sys.argv[1]); from app.services.proposals.schema import ProposalDoc; print(json.dumps(ProposalDoc.model_json_schema()))", p)
	expected, err := cmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	var got, want map[string]any
	if err := json.Unmarshal(expected, &want); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(protocol.Proposal(), &got); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatal("embedded dashboard schema differs from ProposalDoc.model_json_schema()")
	}
}
