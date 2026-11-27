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
