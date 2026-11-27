package drafts

import (
	"context"
	"errors"
	"reflect"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/calendar"
)

type draftDecisionState struct {
	head, dataRevision, versions, sessions, keys int
	status                                       string
}

func readDraftDecisionState(t *testing.T, pool *pgxpool.Pool, proposal uuid.UUID) draftDecisionState {
	t.Helper()
	var s draftDecisionState
	err := pool.QueryRow(t.Context(), `SELECT calendar_head_version, data_revision,
		(SELECT count(*) FROM calendar_versions), (SELECT count(*) FROM calendar_session_revisions),
		(SELECT count(*) FROM coach_decision_keys WHERE proposal_id=$1),
		(SELECT status FROM coach_proposals WHERE id=$1)
		FROM app_state WHERE id=1`, proposal).Scan(&s.head, &s.dataRevision, &s.versions, &s.sessions, &s.keys, &s.status)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func TestRejectDecisionLedger(t *testing.T) {
	pool := draftTestPool(t)
	pending := pendingTestDraft(t, pool, 1)
	id := pending.ID
	ctx := t.Context()
	store := Store{Pool: pool}
	before := readDraftDecisionState(t, pool, id)
	apply := func(context.Context, pgx.Tx, PreparedDecision, *DecisionReceipt) error {
		return errors.New("unexpected writes from a rejection")
	}
	req := DecisionRequest{Revision: pending.Revision, Key: "reject-1", Reject: []string{"c1"}}
	var original DecisionResult
	for i, key := range []string{"reject-1", "reject-1", "reject-2"} {
		req.Key = key
		got, err := store.decide(ctx, id, req, testNow, testKBRoot, apply)
		if err != nil || got.Status != "rejected" || got.ProposalID != id || got.CalendarVersion != nil {
			t.Fatalf("receipt: %+v, %v", got, err)
		}
		if i == 0 {
			original = got
		} else if !reflect.DeepEqual(got, original) {
			t.Fatalf("replay receipt: %+v, want %+v", got, original)
		}
	}
	req.Accept, req.Reject = req.Reject, nil
	_, err := store.decide(ctx, id, req, testNow, testKBRoot, apply)
	var p *Error
	if !errors.As(err, &p) || p.Code != "decision_conflict" {
		t.Fatalf("selection conflict: %v", err)
	}
	before.keys += 2
	before.status = "rejected"
	if got := readDraftDecisionState(t, pool, id); got != before {
		t.Fatalf("rejection state: %+v, want %+v", got, before)
	}
	draft, err := store.Load(ctx, id)
	if err != nil || draft.Changes["c1"].Decision != "rejected" || draft.Changes["c1"].SessionUID != nil {
		t.Fatalf("rejected change: %+v, %v", draft.Changes["c1"], err)
	}
}

func TestAcceptDecisionLedger(t *testing.T) {
	for _, tc := range []struct {
		status         string
		accept, reject []string
	}{
		{status: "partially_accepted", accept: []string{"c1"}, reject: []string{"c2"}},
		{status: "accepted", accept: []string{"c1", "c2"}},
	} {
		t.Run(tc.status, func(t *testing.T) {
			pool := draftTestPool(t)
			pending := pendingTestDraft(t, pool, 2)
			id := pending.ID
			ctx := t.Context()
			store := Store{Pool: pool}
			before := readDraftDecisionState(t, pool, id)
			req := DecisionRequest{Head: before.head, Revision: pending.Revision, Key: "accept-original", Accept: tc.accept, Reject: tc.reject}
			injected := errors.New("injected refresh failure")
			_, err := store.Decide(ctx, id, req, testNow, testKBRoot, func(context.Context, pgx.Tx, calendar.PlanScope, []uuid.UUID) error {
				return injected
			})
			if !errors.Is(err, injected) {
				t.Fatalf("expected injected refresh rollback: %v", err)
			}
			if got := readDraftDecisionState(t, pool, id); got != before {
				t.Fatalf("refresh failure persisted state: %+v, want %+v", got, before)
			}

			calls := 0
			refresh := func(_ context.Context, _ pgx.Tx, scope calendar.PlanScope, _ []uuid.UUID) error {
				calls++
				if len(scope.PlanUIDs) != len(req.Accept) {
					t.Errorf("refresh scope: %+v", scope)
				}
				return nil
			}
			first, err := store.Decide(ctx, id, req, testNow, testKBRoot, refresh)
			if err != nil || first.ProposalID != id || first.Status != tc.status || first.CalendarVersion == nil || *first.CalendarVersion != before.head+1 {
				t.Fatalf("decision receipt: %+v, %v", first, err)
			}
			for _, key := range []string{"accept-original", "accept-alias"} {
				req.Key = key
				got, err := store.Decide(ctx, id, req, testNow, testKBRoot, refresh)
				if err != nil || !reflect.DeepEqual(got, first) {
					t.Fatalf("replay receipt: %+v, %v; want %+v", got, err, first)
				}
			}
			if calls != 1 {
				t.Fatalf("refreshed %d times across apply and replays", calls)
			}
			want := before
			want.head++
			want.dataRevision++
			want.versions++
			want.sessions += len(req.Accept)
			want.keys += 2
			want.status = tc.status
			if got := readDraftDecisionState(t, pool, id); got != want {
				t.Fatalf("accepted state: %+v, want %+v", got, want)
			}
			draft, err := store.Load(ctx, id)
			if err != nil {
				t.Fatal(err)
			}
			for _, key := range tc.accept {
				c := draft.Changes[key]
				if c.Decision != "accepted" || c.SessionUID == nil {
					t.Fatalf("accepted change: %+v", c)
				}
			}
			for _, key := range tc.reject {
				c := draft.Changes[key]
				if c.Decision != "rejected" || c.SessionUID != nil {
					t.Fatalf("unselected change: %+v", c)
				}
			}
		})
	}
}

func TestAcceptPlanningDecisionLedger(t *testing.T) {
	t.Run("anchor", func(t *testing.T) {
		pool := draftTestPool(t)
		ctx := t.Context()
		const key = "hr_threshold_lower-2026-11-16"
		pending := submitTestDraft(t, pool, "recalibrate_intensity", map[string]any{
			"anchor_changes": []map[string]any{{
				"kind": "hr_threshold_lower", "value_low": 165, "unit": "bpm",
				"calibrated_at": testNow, "protocol": "manual", "confidence": "moderate",
			}},
		})
		store := Store{Pool: pool}
		req := DecisionRequest{Revision: pending.Revision, Key: "accept-anchor", Anchors: []string{key}}
		calls := 0
		refresh := func(_ context.Context, _ pgx.Tx, scope calendar.PlanScope, _ []uuid.UUID) error {
			calls++
			if scope.Since != "2026-11-16" || len(scope.PlanUIDs) != 0 {
				t.Errorf("anchor refresh scope: %+v", scope)
			}
			return nil
		}
		for range 2 {
			result, err := store.Decide(ctx, pending.ID, req, testNow, testKBRoot, refresh)
			if err != nil || result.Status != "accepted" || result.CalendarVersion != nil ||
				!reflect.DeepEqual(result.AnchorKeys, []string{key}) {
				t.Fatalf("anchor receipt: %+v, %v", result, err)
			}
		}
		var found int
		err := pool.QueryRow(ctx, "SELECT count(*) FROM intensity_anchors WHERE anchor_key=$1 AND value_low=165", key).Scan(&found)
		if err != nil || found != 1 || calls != 1 {
			t.Fatalf("anchor applies and refreshes once: rows=%d refreshes=%d err=%v", found, calls, err)
		}
	})

	t.Run("block", func(t *testing.T) {
		pool := draftTestPool(t)
		ctx := t.Context()
		fields := map[string]any{
			"status": "active", "objective": "Build",
			"why":                  []map[string]string{{"kind": "inference", "text": "Ready"}},
			"maintained_qualities": []any{}, "non_goals": []any{}, "eligible_recipe_ids": []string{"REC001", "REC009"},
			"progression_dimension": "duration", "constraints": []any{},
			"start_date": "2026-11-16", "review_date": "2026-12-28", "indicators": []any{},
			"early_review_triggers": []any{}, "objective_status": "unresolved",
			"benchmark": map[string]string{"kind": "time_trial", "protocol": "5 km solo time trial",
				"planned_date": "2026-12-20", "progress_if": "Under 22:00", "consolidate_if": "Over 22:30"},
		}
		blockChange := map[string]any{"decision": "start", "block_uid": nil, "version_fields": fields}
		pending := submitTestDraft(t, pool, "review_training_block", map[string]any{"block_change": blockChange})
		store := Store{Pool: pool}
		req := DecisionRequest{Revision: pending.Revision, Key: "accept-block", Block: true}
		first, err := store.Decide(ctx, pending.ID, req, testNow, testKBRoot, nil)
		if err != nil || first.Status != "accepted" || first.BlockVersionID == nil || first.CalendarVersion != nil {
			t.Fatalf("block receipt: %+v, %v", first, err)
		}
		got, err := store.Decide(ctx, pending.ID, req, testNow, testKBRoot, nil)
		if err != nil || !reflect.DeepEqual(got, first) {
			t.Fatalf("block replay: %+v, %v; want %+v", got, err, first)
		}
		var blockID uuid.UUID
		if err := pool.QueryRow(ctx, "SELECT block_uid FROM block_versions WHERE proposal_id=$1 AND id=$2 AND version=1", pending.ID, first.BlockVersionID).Scan(&blockID); err != nil {
			t.Fatal(err)
		}
		blockChange["decision"], blockChange["block_uid"] = "continue", blockID
		continuation := map[string]any{"base_block_version_id": first.BlockVersionID, "block_change": blockChange}
		pending = submitTestDraft(t, pool, "review_training_block", continuation)
		req.Key, req.Revision = "continue-block", pending.Revision
		same, err := store.Decide(ctx, pending.ID, req, testNow, testKBRoot, nil)
		if err != nil || same.Status != "accepted" || same.BlockVersionID == nil || *same.BlockVersionID != *first.BlockVersionID {
			t.Fatalf("unchanged block continues the existing version: %+v, %v", same, err)
		}
		fields["eligible_recipe_ids"] = []string{"REC009", "REC001"}
		pending = submitTestDraft(t, pool, "review_training_block", continuation)
		req.Key, req.Revision = "reorder-block", pending.Revision
		reordered, err := store.Decide(ctx, pending.ID, req, testNow, testKBRoot, nil)
		if err != nil || reordered.Status != "accepted" || reordered.BlockVersionID == nil || *reordered.BlockVersionID == *first.BlockVersionID {
			t.Fatalf("reordered recipes create another block version: %+v, %v", reordered, err)
		}
		var recipes []string
		err = pool.QueryRow(ctx, "SELECT eligible_recipe_ids FROM block_versions WHERE id=$1 AND block_uid=$2 AND version=2", reordered.BlockVersionID, blockID).Scan(&recipes)
		if err != nil || !reflect.DeepEqual(recipes, []string{"REC009", "REC001"}) {
			t.Fatalf("expected authored recipe order: %v, %v", recipes, err)
		}
		var versions, decisions int
		err = pool.QueryRow(ctx, `SELECT (SELECT count(*) FROM block_versions WHERE block_uid=$1),
			(SELECT count(*) FROM block_decisions WHERE block_uid=$1)`, blockID).Scan(&versions, &decisions)
		if err != nil || versions != 2 || decisions != 2 {
			t.Fatalf("expected one start and one changed continuation: versions=%d decisions=%d err=%v", versions, decisions, err)
		}
	})
}
