package coachdashboard

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"reflect"
	"regexp"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

// The runner creates and migrates an isolated schema for each invocation.
func workflowPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires DASHBOARD_TEST_DATABASE_URL from the synthetic dashboard runner")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatal("invalid dashboard test database configuration")
	}
	if cfg.ConnConfig.Database != "garmin_test" || (cfg.ConnConfig.Host != "127.0.0.1" && cfg.ConnConfig.Host != "localhost") {
		t.Fatal("dashboard tests require a dedicated loopback garmin_test database")
	}
	pool, err := pgxpool.NewWithConfig(t.Context(), cfg)
	if err != nil {
		t.Fatal("open dashboard test database")
	}
	t.Cleanup(pool.Close)
	var schema string
	if err := pool.QueryRow(t.Context(), "SELECT COALESCE(current_schema(), '')").Scan(&schema); err != nil {
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) {
			t.Fatalf("checking fixture schema: postgres %s %s", pgErr.Code, pgErr.Message)
		}
		t.Fatalf("checking fixture schema: %T", err)
	}
	if !regexp.MustCompile("^go_parity_[a-f0-9]{32}$").MatchString(schema) {
		t.Fatalf("dashboard tests require the runner's disposable schema, got %q", schema)
	}
	return pool
}

type scriptedTurn struct {
	run   func(context.Context, TurnRequest) (string, error)
	count atomic.Int32
}

func (s *scriptedTurn) RunTurn(ctx context.Context, turn TurnRequest) (string, error) {
	s.count.Add(1)
	return s.run(ctx, turn)
}

func requireOK(t *testing.T, err error) {
	t.Helper()
	if err != nil {
		t.Fatal(err)
	}
}

func requireProblem(t *testing.T, err error, code string) {
	t.Helper()
	var problem *Problem
	if !errors.As(err, &problem) || problem.Code != code {
		t.Fatalf("wanted %s, got %v", code, err)
	}
}

func workflowView(t *testing.T, gateway *Gateway, status string) View {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
	defer cancel()
	for {
		review, err := gateway.View(ctx)
		requireOK(t, err)
		if review.Status == status {
			return review
		}
		select {
		case <-ctx.Done():
			t.Fatalf("wanted %s, got %s (%v)", status, review.Status, review.Error)
		case <-time.After(10 * time.Millisecond):
		}
	}
}

func waitSignal(t *testing.T, signal <-chan struct{}) {
	t.Helper()
	select {
	case <-signal:
	case <-time.After(5 * time.Second):
		t.Fatal("timed out waiting for the fake app-server")
	}
}

func planState(t *testing.T, pool *pgxpool.Pool) [3]int64 {
	t.Helper()
	var state [3]int64
	err := pool.QueryRow(t.Context(), `SELECT
		COALESCE((SELECT calendar_head_version FROM app_state WHERE id=1), 0),
		(SELECT count(*) FROM calendar_session_revisions),
		(SELECT count(*) FROM coach_proposals)`).Scan(&state[0], &state[1], &state[2])
	requireOK(t, err)
	return state
}

func TestDashboardWorkflowPostgres(t *testing.T) {
	pool := workflowPool(t)
	ctx := t.Context()
	before := planState(t, pool)
	const text = "Can we adjust the next easy run?"
	const thread = "synthetic-private-thread"
	app := &scriptedTurn{run: func(_ context.Context, turn TurnRequest) (string, error) {
		if turn.Message != "The athlete selected Sunday Review.\n\n"+text || turn.ThreadID != "" {
			return "", errors.New("incorrect opening turn")
		}
		if err := turn.OnThread(thread); err != nil {
			return "", err
		}
		return "We can discuss the next easy run.", nil
	}}
	first := NewGateway(NewStore(pool, "test"), app)
	blank := workflowView(t, first, "idle")
	if blank.ID != nil || len(blank.Messages) != 0 || app.count.Load() != 0 {
		t.Fatal("opening the dashboard should show an empty review without starting a turn")
	}
	clientID := uuid.NewString()
	initial := Guard{Set: true}
	requireOK(t, first.Send(ctx, initial, clientID, text, "sunday_review"))
	discussion := workflowView(t, first, "idle")
	if discussion.ID == nil || len(discussion.Messages) != 2 || discussion.Messages[0].Text != text || discussion.Messages[1].Text != "We can discuss the next easy run." {
		t.Fatalf("discussion transcript: %+v", discussion.Messages)
	}
	public, err := json.Marshal(discussion)
	requireOK(t, err)
	if bytes.Contains(public, []byte(thread)) {
		t.Fatal("private provider thread appeared in the public review")
	}
	requireOK(t, first.Shutdown(ctx))

	started := make(chan struct{})
	interrupted := make(chan struct{})
	resumedApp := &scriptedTurn{run: func(ctx context.Context, turn TurnRequest) (string, error) {
		switch turn.Message {
		case "Looks good. Save it.":
			if turn.ThreadID != thread {
				return "", errors.New("missing provider thread on resume")
			}
			return "Your request was received.", nil
		case "Hold this turn":
			if err := turn.OnDelta("Checking the training log"); err != nil {
				return "", err
			}
			close(started)
			<-ctx.Done()
			close(interrupted)
			return "", ctx.Err()
		default:
			return "", &Problem{Code: "auth_required", Message: "Sign in to continue."}
		}
	}}
	gateway := NewGateway(NewStore(pool, "test"), resumedApp)
	t.Cleanup(func() { requireOK(t, gateway.Shutdown(context.Background())) })
	if reloaded := workflowView(t, gateway, "idle"); !reflect.DeepEqual(reloaded, discussion) {
		t.Fatal("review changed after gateway restart")
	}
	requireOK(t, gateway.Send(ctx, initial, clientID, text, "sunday_review"))
	requireProblem(t, gateway.Send(ctx, initial, clientID, text, "today_run"), "chat_message_conflict")
	if resumedApp.count.Load() != 0 {
		t.Fatal("replaying a completed turn started the app-server")
	}
	current := Guard{Set: true, ID: *discussion.ID}
	saveID := uuid.NewString()
	requireOK(t, gateway.Send(ctx, current, saveID, "Looks good. Save it.", ""))
	saved := workflowView(t, gateway, "idle")
	requireOK(t, gateway.Send(ctx, current, saveID, "Looks good. Save it.", ""))
	if len(saved.Messages) != 4 || resumedApp.count.Load() != 1 || planState(t, pool) != before {
		t.Fatal("save request or replay changed plan state or duplicated a turn")
	}

	holdID := uuid.NewString()
	requireOK(t, gateway.Send(ctx, current, holdID, "Hold this turn", ""))
	waitSignal(t, started)
	requireOK(t, gateway.Send(ctx, current, holdID, "Hold this turn", ""))
	running := workflowView(t, gateway, "running")
	if len(running.Messages) != 6 || running.Messages[5].Text != "Checking the training log" {
		t.Fatal("in-flight replay lost the streamed reply or duplicated a message")
	}
	requireProblem(t, gateway.Send(ctx, current, holdID, "Different text", ""), "chat_message_conflict")
	requireProblem(t, gateway.Send(ctx, current, uuid.NewString(), "One more thing", ""), "chat_running")
	requireOK(t, gateway.Cancel(ctx, current))
	waitSignal(t, interrupted)
	stopped := workflowView(t, gateway, "cancelled")
	if len(stopped.Messages) != 5 || stopped.Messages[4].Text != "Hold this turn" {
		t.Fatal("cancellation should retain the athlete message and discard partial output")
	}
	requireOK(t, gateway.New(ctx, current))
	next := workflowView(t, gateway, "idle")
	if next.ID == nil || *next.ID == *discussion.ID || len(next.Messages) != 0 {
		t.Fatal("new review should have a fresh ID and an empty transcript")
	}
	var archived int
	requireOK(t, pool.QueryRow(ctx, "SELECT count(*) FROM coach_chat_reviews WHERE mode=$1 AND id=$2 AND NOT current", "test", *discussion.ID).Scan(&archived))
	if archived != 1 {
		t.Fatal("previous review was not archived")
	}
	requireProblem(t, gateway.Cancel(ctx, current), "chat_review_changed")
	requireOK(t, gateway.Send(ctx, current, holdID, "Hold this turn", ""))
	if resumedApp.count.Load() != 2 || len(workflowView(t, gateway, "idle").Messages) != 0 {
		t.Fatal("an archived receipt started a turn in the new review")
	}

	noAuth := "Review training this week"
	requireOK(t, gateway.Send(ctx, Guard{Set: true, ID: *next.ID}, uuid.NewString(), noAuth, ""))
	failed := workflowView(t, gateway, "failed")
	if failed.Error == nil || failed.Error.Code != "auth_required" || len(failed.Messages) != 1 || failed.Messages[0].Text != noAuth {
		t.Fatal("authentication failure should keep the athlete's message and expose auth_required")
	}
	if planState(t, pool) != before {
		t.Fatal("dashboard conversation changed proposal or calendar state")
	}
}

func TestDashboardLostTurnPostgres(t *testing.T) {
	pool := workflowPool(t)
	ctx := t.Context()
	store := NewStore(pool, "test-interruption")
	clientID := uuid.NewString()
	const text = "Review my week"
	type result struct {
		lease *TurnLease
		err   error
	}
	start := make(chan struct{})
	results := make(chan result, 2)
	for range 2 {
		go func() {
			<-start
			lease, err := store.Enqueue(ctx, Guard{Set: true}, clientID, text, "")
			results <- result{lease, err}
		}()
	}
	close(start)
	var active *TurnLease
	for range 2 {
		r := <-results
		requireOK(t, r.err)
		if r.lease != nil {
			t.Cleanup(r.lease.Close)
			if active != nil {
				t.Fatal("concurrent copies of one message acquired two turn leases")
			}
			active = r.lease
		}
	}
	if active == nil {
		t.Fatal("message was never scheduled")
	}
	requireOK(t, store.SaveThread(ctx, active.ID, "synthetic-resume"))
	active.Close() // Simulate the connection disappearing without finalizing the turn.
	restored := NewStore(pool, "test-interruption")
	review, err := restored.Review(ctx)
	requireOK(t, err)
	if review.Status != "failed" || review.Error == nil || review.Error.Code != "interrupted" || len(review.Messages) != 1 {
		t.Fatal("orphaned turn did not retain the athlete message and report interruption")
	}
	replay, err := restored.Enqueue(ctx, Guard{Set: true}, clientID, text, "")
	requireOK(t, err)
	if replay != nil {
		replay.Close()
		t.Fatal("recovering a receipt started a second turn")
	}
	next, err := restored.Enqueue(ctx, Guard{Set: true, ID: review.ID}, uuid.NewString(), "Try again", "")
	requireOK(t, err)
	if next == nil {
		t.Fatal("explicit retry did not acquire a turn")
	}
	defer next.Close()
	if next.ThreadID != "synthetic-resume" {
		t.Fatal("explicit retry lost its provider resume ID")
	}
	requireOK(t, store.Finish(ctx, active.ID, uuid.NewString(), "late stale reply", nil))
	requireOK(t, restored.Finish(ctx, next.ID, uuid.NewString(), "Retried.", nil))
	review, err = restored.Review(ctx)
	requireOK(t, err)
	if review.Status != "idle" || len(review.Messages) != 3 || review.Messages[2].Text != "Retried." {
		t.Fatal("late completion from an orphaned turn changed the transcript")
	}
}
