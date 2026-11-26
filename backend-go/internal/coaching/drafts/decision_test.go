package drafts

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/mtang08/going-bananas/backend-go/internal/calendar"
	"os"
	"regexp"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// The differential harness supplies a Python-compatible pending draft, a fresh
// migrated schema and a pinned clock. It checks the resulting receipts itself.
func TestRejectDecisionLedger(t *testing.T) {
	dsn := os.Getenv("COACHING_DECISION_TEST_URL")
	if dsn == "" {
		t.Skip("check_lifecycle.py supplies an isolated proposal")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var name, schema string
	if err := pool.QueryRow(ctx, "SELECT current_database(), current_schema()").Scan(&name, &schema); err != nil {
		t.Fatal(err)
	}
	if name != "garmin_test" || !regexp.MustCompile(`^go_drafts_[0-9a-f]{32}$`).MatchString(schema) {
		t.Fatal("requires isolated test database/schema")
	}
	id := uuid.MustParse(os.Getenv("COACHING_DECISION_TEST_ID"))
	now, err := time.Parse(time.RFC3339, os.Getenv("COACHING_DECISION_TEST_NOW"))
	if err != nil {
		t.Fatal(err)
	}
	store := Store{Pool: pool}
	apply := func(context.Context, pgx.Tx, PreparedDecision, *DecisionReceipt) error {
		return errors.New("unexpected writes from a rejection")
	}
	req := DecisionRequest{Revision: 1, Key: "reject-1", Reject: []string{"c1"}}
	for _, key := range []string{"reject-1", "reject-1", "reject-2"} {
		req.Key = key
		got, err := store.decide(ctx, id, req, now, "../../../../running_coach_kb", apply)
		if err != nil || got.Status != "rejected" || got.ProposalID != id || got.CalendarVersion != nil {
			t.Fatalf("receipt %v %v", got, err)
		}
	}
	req.Accept, req.Reject = req.Reject, nil
	_, err = store.decide(ctx, id, req, now, "../../../../running_coach_kb", apply)
	var p *Error
	if !errors.As(err, &p) || p.Code != "decision_conflict" {
		t.Fatalf("selection conflict %v", err)
	}
}

func TestAcceptDecisionLedger(t *testing.T) {
	dsn := os.Getenv("COACHING_DECISION_TEST_URL")
	if dsn == "" {
		t.Skip("check_lifecycle.py supplies isolated proposal")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var name, schema string
	if err := pool.QueryRow(ctx, "SELECT current_database(),current_schema()").Scan(&name, &schema); err != nil {
		t.Fatal(err)
	}
	if name != "garmin_test" || !regexp.MustCompile(`^go_drafts_[0-9a-f]{32}$`).MatchString(schema) {
		t.Fatal("requires isolated schema")
	}
	id := uuid.MustParse(os.Getenv("COACHING_DECISION_TEST_ID"))
	now, err := time.Parse(time.RFC3339, os.Getenv("COACHING_DECISION_TEST_NOW"))
	if err != nil {
		t.Fatal(err)
	}
	var req DecisionRequest
	if err := json.Unmarshal([]byte(os.Getenv("COACHING_DECISION_TEST_REQUEST")), &req); err != nil {
		t.Fatal(err)
	}
	injected := errors.New("injected refresh failure")
	store := Store{Pool: pool}
	_, err = store.Decide(ctx, id, req, now, "../../../../running_coach_kb", func(context.Context, pgx.Tx, calendar.PlanScope, []uuid.UUID) error { return injected })
	if !req.Block && !errors.Is(err, injected) {
		t.Fatalf("expected injected refresh rollback: %v", err)
	}
	for i := range 2 {
		called := false
		_, err = store.Decide(ctx, id, req, now, "../../../../running_coach_kb", func(ctx context.Context, tx pgx.Tx, scope calendar.PlanScope, matched []uuid.UUID) error {
			called = true
			if len(scope.PlanUIDs) != len(req.Accept) {
				t.Fatalf("refresh plans %v", scope.PlanUIDs)
			}
			return nil
		})
		if err != nil || called != (i == 0 && !req.Block) {
			t.Fatalf("decision %d refresh=%t err=%v", i, called, err)
		}
	}
}
