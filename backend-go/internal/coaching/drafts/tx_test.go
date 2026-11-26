package drafts

import (
	"context"
	"encoding/json"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"os"
	"regexp"
	"testing"
	"time"
)

func TestDashboardBoundDraft(t *testing.T) {
	url := os.Getenv("COACHING_TX_TEST_URL")
	if url == "" {
		t.Skip("requires isolated pending dashboard fixture")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	pool, err := pgxpool.New(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var db, schema string
	if err := pool.QueryRow(ctx, "SELECT current_database(),current_schema()").Scan(&db, &schema); err != nil {
		t.Fatal(err)
	}
	if db != "garmin_test" || !regexp.MustCompile(`^go_drafts_[0-9a-f]{32}$`).MatchString(schema) {
		t.Fatal("requires isolated fixture")
	}
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	writer := InTransaction(tx)
	const root = "../../../../running_coach_kb"
	now := time.Now().UTC()
	draft, err := writer.ActiveProposal(ctx, now, root)
	if err != nil || draft == nil || !draft.IsCurrent {
		t.Fatalf("active=%v err=%v", draft, err)
	}
	var payload map[string]json.RawMessage
	if err := json.Unmarshal(draft.Document, &payload); err != nil {
		t.Fatal(err)
	}
	payload["headline"] = json.RawMessage(`"Dashboard staged change"`)
	updated, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	r, err := writer.Revise(ctx, draft.ProposalID, RevisionRequest{ExpectedRevision: draft.Revision, Reason: "Rule test", Document: updated}, now, NewValidator(root))
	if err != nil || r.Status != "pending" {
		t.Fatalf("revise %v %v", r, err)
	}
	if _, err := writer.Discard(ctx, draft.ProposalID, r.Revision, now); err != nil {
		t.Fatal(err)
	}
	empty, err := writer.ActiveProposal(ctx, now, root)
	if err != nil || empty != nil {
		t.Fatalf("discard %v %v", empty, err)
	}
	payload["headline"] = json.RawMessage(`"Dashboard new draft"`)
	fresh, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	newDraft, err := writer.Submit(ctx, fresh, now, NewValidator(root))
	if err != nil || newDraft.ID == uuid.Nil || newDraft.ID == draft.ProposalID {
		t.Fatalf("submit %v %v", newDraft, err)
	}
	observer := Store{Pool: pool}
	before, err := observer.Load(ctx, draft.ProposalID)
	if err != nil || before.Revision != draft.Revision || before.Status != "pending" {
		t.Fatalf("outside observed uncommitted changes %v", err)
	}
	if err := tx.Rollback(ctx); err != nil {
		t.Fatal(err)
	}
	restored, err := observer.ActiveProposal(ctx, now, root)
	if err != nil || restored == nil || restored.ProposalID != draft.ProposalID || restored.Revision != draft.Revision {
		t.Fatalf("rollback failed: %v", err)
	}
}
