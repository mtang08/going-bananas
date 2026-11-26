package coachdashboard

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func TestDashboardToolsPostgres(t *testing.T) {
	pool := workflowPool(t)
	ctx := t.Context()
	// A synthetic pending domain makes callback rollback and stable ID visible independently of review state.
	_, err := pool.Exec(ctx, "CREATE TABLE dashboard_tool_fixture(id uuid PRIMARY KEY,revision integer NOT NULL)")
	requireOK(t, err)
	t.Cleanup(func() {
		_, err := pool.Exec(context.Background(), "DROP TABLE dashboard_tool_fixture")
		if err != nil {
			t.Error(err)
		}
	})
	store := NewStore(pool, "test-tools")
	snapshot, proposal := uuid.New(), uuid.New()
	approvedID := ""
	handlers := ToolHandlers{
		Active: func(ctx context.Context, tx pgx.Tx) (*ActiveDraft, error) {
			var rev int
			err := tx.QueryRow(ctx, "SELECT revision FROM dashboard_tool_fixture WHERE id=$1", proposal).Scan(&rev)
			if errors.Is(err, pgx.ErrNoRows) {
				return nil, nil
			}
			if err != nil {
				return nil, err
			}
			return &ActiveDraft{ID: proposal, SnapshotID: snapshot, Revision: rev, Operation: "review_rolling_plan", View: Object{"proposal": Object{"id": proposal.String(), "revision": rev}}}, nil
		},
		Snapshot: func(_ context.Context, _ pgx.Tx, op string) (Object, error) {
			return Object{"snapshot_id": snapshot.String(), "operation": op}, nil
		},
		Query: func(_ context.Context, _ pgx.Tx, _ Object) (any, error) {
			return []Object{{"label": "synthetic", "gps_stream": "private"}}, nil
		},
		Findings: func(_ context.Context, _ pgx.Tx, include string) (Object, error) {
			return Object{"include": include, "private_note": "private"}, nil
		},
		Schema: func(_ context.Context, _ pgx.Tx) (Object, error) { return Object{"type": "object"}, nil },
		AuthorizePending: func(_ context.Context, _ pgx.Tx, msg Message) (bool, error) {
			return msg.ClientMessageID != nil && *msg.ClientMessageID == approvedID, nil
		},
		SavePending: func(ctx context.Context, tx pgx.Tx, req PendingRequest) (PendingResult, error) {
			var rev int
			err := tx.QueryRow(ctx, `INSERT INTO dashboard_tool_fixture VALUES($1,1)
				ON CONFLICT(id) DO UPDATE SET revision=dashboard_tool_fixture.revision+1 RETURNING revision`, proposal).Scan(&rev)
			status := "pending"
			if req.Document["synthetic_stale"] == true {
				status = "stale"
			}
			return PendingResult{ID: proposal, Revision: rev, Status: status}, err
		},
	}
	tools := NewDashboardTools(store, handlers)
	if len(tools.Definitions()) != 6 {
		t.Fatal("incorrect tool definitions")
	}
	call := func(id, name string, args Object, code string) Object {
		t.Helper()
		value, err := tools.Call(ctx, id, name, args)
		requireOK(t, err)
		if field(value, "error") != code {
			t.Fatalf("%s: expected %q got %v", name, code, value)
		}
		return value
	}
	start := func(key, text string) *TurnLease {
		t.Helper()
		lease, err := store.Enqueue(ctx, Guard{}, key, text, "")
		requireOK(t, err)
		if lease == nil {
			t.Fatal("missing turn")
		}
		t.Cleanup(lease.Close)
		return lease
	}
	doc := Object{"snapshot_id": snapshot.String(), "operation": "review_rolling_plan"}
	args := Object{"document": doc}
	first := start(uuid.NewString(), "Discuss my week.")
	call(first.ID, "accept_proposal", Object{}, "unknown_tool")
	call(first.ID, "save_pending_proposal", args, "active_proposal_required")
	call(first.ID, "active_proposal", Object{}, "")
	call(first.ID, "save_pending_proposal", args, "snapshot_required")
	call(first.ID, "coaching_snapshot", Object{"operation": "review_rolling_plan"}, "")
	call(first.ID, "save_pending_proposal", args, "athlete_agreement_required")
	call(first.ID, "save_pending_proposal", Object{"document": doc, "athlete_approved": true}, "invalid_tool_arguments")
	if v := call(first.ID, "proposal_schema", Object{}, ""); v["activation"] != "manual" {
		t.Fatal("schema lost manual activation")
	}
	if v := call(first.ID, "review_findings", Object{}, ""); v["private_note"] != nil || v["include"] != "active" {
		t.Fatal("findings response")
	}
	call(first.ID, "coaching_query", Object{"name": "long_run_history", "start": "2026-01-01", "end": "2026-05-01"}, "invalid_date_window")
	q := call(first.ID, "coaching_query", Object{"name": "explain_metric", "result_id": snapshot.String()}, "")
	if rec := q["data"].([]any)[0].(Object); rec["gps_stream"] != nil || rec["label"] != "synthetic" {
		t.Fatal("query privacy")
	}
	requireOK(t, store.Finish(ctx, first.ID, uuid.NewString(), "Discussed.", nil))
	first.Close()
	call(first.ID, "active_proposal", Object{}, "interrupted")
	approvedID = uuid.NewString()
	second := start(approvedID, "Save the agreed plan.")
	doc["synthetic_stale"] = true
	call(second.ID, "save_pending_proposal", args, "stale_evidence")
	var n int
	requireOK(t, pool.QueryRow(ctx, "SELECT count(*) FROM dashboard_tool_fixture").Scan(&n))
	if n != 0 {
		t.Fatal("failed validation committed a pending draft")
	}
	delete(doc, "synthetic_stale")
	saved := call(second.ID, "save_pending_proposal", args, "")
	if saved["proposal_id"] != proposal.String() || saved["revision"] != 1 {
		t.Fatal("incorrect pending draft identity")
	}
	call(second.ID, "save_pending_proposal", args, "active_proposal_exists")
	revision := Object{"document": doc, "expected_revision": 1, "reason": "athlete correction", "proposal_id": proposal.String()}
	_, err = pool.Exec(ctx, "UPDATE dashboard_tool_fixture SET revision=2")
	requireOK(t, err)
	call(second.ID, "save_pending_proposal", revision, "proposal_revision_conflict")
	revision["expected_revision"] = 2
	call(second.ID, "save_pending_proposal", revision, "proposal_revision_conflict")
	call(second.ID, "active_proposal", Object{}, "")
	call(second.ID, "save_pending_proposal", revision, "")
	_, err = pool.Exec(ctx, "DELETE FROM dashboard_tool_fixture")
	requireOK(t, err)
	call(second.ID, "save_pending_proposal", revision, "proposal_decided")
	_, err = store.Cancel(ctx, Guard{})
	requireOK(t, err)
	call(second.ID, "save_pending_proposal", revision, "interrupted")
	second.Close()
	replay, err := store.Enqueue(ctx, Guard{}, approvedID, "Save the agreed plan.", "")
	requireOK(t, err)
	if replay != nil {
		replay.Close()
		t.Fatal("duplicate created a second authorized turn")
	}
	r, err := store.Review(ctx)
	requireOK(t, err)
	if r.ProposalID != proposal.String() || r.ProposalRevision != 3 || r.ObservedRevision != 3 {
		t.Fatal("stable linked draft lost on cancellation")
	}
	requireOK(t, store.NewReview(ctx, Guard{Set: true, ID: r.ID}))
	third := start(uuid.NewString(), "Another discussion")
	call(third.ID, "save_pending_proposal", args, "active_proposal_required")
	call(third.ID, "active_proposal", Object{}, "")
	call(third.ID, "save_pending_proposal", args, "snapshot_required")
}

func TestToolQueryArgumentBounds(t *testing.T) {
	for _, a := range []Object{
		{"name": "activity_execution", "activity_id": "invalid"},
		{"name": "long_run_history", "start": "2026-02-01", "end": "2026-01-01"},
		{"name": "calendar_diff", "from_version": -1, "to_version": 0},
		{"name": "explain_metric", "result_id": uuid.NewString(), "start": "2026-01-01"},
		{"name": "accept_proposal"},
	} {
		if validateQuery(a) == nil {
			t.Fatal("accepted invalid query", a)
		}
	}
	if _, err := pendingArgs(Object{"document": Object{}, "reason": strings.Repeat("x", 501)}); err == nil {
		t.Fatal("accepted partial revision")
	}
}

func TestToolCallAndCancelShareTransaction(t *testing.T) {
	pool := workflowPool(t)
	store := NewStore(pool, "test-tool-cancel-race")
	ctx := t.Context()
	lease, err := store.Enqueue(ctx, Guard{}, uuid.NewString(), "Read the training log.", "")
	requireOK(t, err)
	defer lease.Close()
	entered, release := make(chan struct{}), make(chan struct{})
	tools := NewDashboardTools(store, ToolHandlers{Findings: func(ctx context.Context, _ pgx.Tx, _ string) (Object, error) {
		close(entered)
		select {
		case <-release:
			return Object{}, nil
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}})
	done := make(chan error, 1)
	callCtx, stopCall := context.WithTimeout(ctx, 5*time.Second)
	defer stopCall()
	go func() { _, err := tools.Call(callCtx, lease.ID, "review_findings", Object{}); done <- err }()
	waitSignal(t, entered)
	cancelCtx, stopCancel := context.WithTimeout(ctx, 100*time.Millisecond)
	_, err = store.Cancel(cancelCtx, Guard{})
	stopCancel()
	close(release)
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("cancellation crossed live tool transaction: %v", err)
	}
	requireOK(t, <-done)
	_, err = store.Cancel(ctx, Guard{})
	requireOK(t, err)
	reply, err := tools.Call(ctx, lease.ID, "review_findings", Object{})
	requireOK(t, err)
	if reply["error"] != "interrupted" {
		t.Fatal("cancelled turn entered a second domain callback")
	}
}
