package drafts

import (
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func TestDashboardBoundDraft(t *testing.T) {
	pool := draftTestPool(t)
	pending := pendingTestDraft(t, pool, 1)
	ctx := t.Context()
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	writer := InTransaction(tx)
	draft, err := writer.ActiveProposal(ctx, testNow, testKBRoot)
	if err != nil || draft == nil || draft.ProposalID != pending.ID || !draft.IsCurrent {
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
	r, err := writer.Revise(ctx, draft.ProposalID, RevisionRequest{ExpectedRevision: draft.Revision, Reason: "Rule test", Document: updated}, testNow, NewValidator(testKBRoot))
	if err != nil || r.Status != "pending" {
		t.Fatalf("revise %v %v", r, err)
	}
	if _, err := writer.Discard(ctx, draft.ProposalID, r.Revision, testNow); err != nil {
		t.Fatal(err)
	}
	empty, err := writer.ActiveProposal(ctx, testNow, testKBRoot)
	if err != nil || empty != nil {
		t.Fatalf("discard %v %v", empty, err)
	}
	payload["headline"] = json.RawMessage(`"Dashboard new draft"`)
	fresh, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	newDraft, err := writer.Submit(ctx, fresh, testNow, NewValidator(testKBRoot))
	if err != nil || newDraft.ID == uuid.Nil || newDraft.ID == draft.ProposalID {
		t.Fatalf("submit %v %v", newDraft, err)
	}
	observer := Store{Pool: pool}
	before, err := observer.Load(ctx, draft.ProposalID)
	if err != nil || before.Revision != draft.Revision || before.Status != "pending" {
		t.Fatalf("outside observed uncommitted changes %v", err)
	}
	var problem *Error
	if _, err := observer.Load(ctx, newDraft.ID); !errors.As(err, &problem) || problem.Code != "proposal_not_found" {
		t.Fatalf("outside observed staged submission: %v", err)
	}
	if err := tx.Rollback(ctx); err != nil {
		t.Fatal(err)
	}
	restored, err := observer.ActiveProposal(ctx, testNow, testKBRoot)
	if err != nil || restored == nil || restored.ProposalID != draft.ProposalID || restored.Revision != draft.Revision || !restored.IsCurrent {
		t.Fatalf("rollback failed: %+v, %v", restored, err)
	}
	expired, err := observer.ActiveProposal(ctx, testNow.Add(25*time.Hour), testKBRoot)
	if err != nil || expired == nil || expired.IsCurrent || expired.ProposalID != draft.ProposalID {
		t.Fatalf("expired evidence should make the same draft non-current: %+v, %v", expired, err)
	}
}
