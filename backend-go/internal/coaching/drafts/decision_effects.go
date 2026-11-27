package drafts

import (
	"context"
	"encoding/json"
	"errors"
	"slices"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/calendar"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

// Decide applies the athlete's explicit selection and stores its replay receipt
// in the same writer transaction as the calendar and derived facts.
func (s Store) Decide(ctx context.Context, id uuid.UUID, r DecisionRequest, now time.Time, kbRoot string, metrics calendar.PlanMetrics) (DecisionResult, error) {
	return s.decide(ctx, id, r, now, kbRoot, func(ctx context.Context, tx pgx.Tx, p PreparedDecision, receipt *DecisionReceipt) error {
		return applyDecision(ctx, tx, p, receipt, now, metrics)
	})
}
func proposalEdits(p PreparedDecision) ([]calendar.PlanEdit, error) {
	var d struct {
		Changes []changeRequest `json:"changes"`
	}
	if err := json.Unmarshal(p.parsed.Payload, &d); err != nil {
		return nil, err
	}
	var edits []calendar.PlanEdit
	for _, ch := range d.Changes {
		c, ok := p.Changes[ch.ID]
		if !ok || ch.Op == "add" && slices.Contains(ch.Flags, "strength_omission") {
			continue
		}
		if (c.Operation == "modify" || c.Operation == "move") && ch.After != nil {
			before := p.rules.HeadSessions[ch.SessionUID]
			same := true
			for key, v := range ch.After.raw {
				if !sameJSON(v, before.raw[key]) {
					same = false
					break
				}
			}
			if same {
				continue
			}
		}
		edits = append(edits, calendar.PlanEdit{ChangeID: ch.ID, Op: c.Operation, SessionUID: c.SessionUID, Fields: c.After})
	}
	return edits, nil
}
func applyDecision(ctx context.Context, tx pgx.Tx, p PreparedDecision, receipt *DecisionReceipt, now time.Time, metrics calendar.PlanMetrics) error {
	var doc struct {
		Headline string
		Anchors  []json.RawMessage `json:"anchor_changes"`
	}
	if err := json.Unmarshal(p.parsed.Document, &doc); err != nil {
		return err
	}
	changed := false
	scope := calendar.PlanScope{}
	block := p.current.BlockID
	if p.Selection.Block {
		id, updated, err := saveBlock(ctx, tx, p, now)
		if err != nil {
			return err
		}
		changed = updated
		block = &id
		receipt.BlockVersionID = &id
	}
	tz, err := time.LoadLocation(p.rules.Timezone)
	if err != nil {
		return err
	}
	for _, raw := range doc.Anchors {
		var a struct {
			Kind string
			At   time.Time `json:"calibrated_at"`
		}
		if err := json.Unmarshal(raw, &a); err != nil {
			return err
		}
		if _, ok := p.Anchors[a.Kind+"-"+a.At.In(tz).Format(time.DateOnly)]; !ok {
			continue
		}
		key, err := saveAnchor(ctx, tx, p, raw)
		if err != nil {
			return err
		}
		changed = true
		scope.Since = p.rules.Today
		scope.Dates = append(scope.Dates, p.rules.Today)
		receipt.AnchorKeys = append(receipt.AnchorKeys, key)
	}
	edits, err := proposalEdits(p)
	if err != nil {
		return err
	}
	if len(edits) > 0 {
		checker := prescriptionCheck(p.rules, false)
		batch := calendar.EditBatch{Head: p.Selection.Head, Kind: "proposal_accept", Actor: "coach", Reason: &doc.Headline, Today: p.rules.Today, ProposalID: &p.ProposalID, BlockVersionID: block, Edits: edits}
		result, err := calendar.ApplyEdits(ctx, tx, batch, checker)
		if err != nil {
			var prob *calendar.Problem
			if errors.As(err, &prob) {
				status := 422
				if prob.Code == "session_not_found" {
					status = 404
				}
				return &Error{prob.Code, prob.Message, status}
			}
			return err
		}
		scope.PlanUIDs = result.PlanUIDs
		scope.Dates = append(scope.Dates, result.Dates...)
		receipt.CalendarVersion = &result.Version
		receipt.StaleProposals = result.Stale
		changed = true
		for key, uid := range result.Created {
			if _, err := tx.Exec(ctx, "UPDATE coach_proposal_changes SET session_uid=$1 WHERE proposal_id=$2 AND change_id=$3", uid, p.ProposalID, key); err != nil {
				return err
			}
		}
	}
	if err := reviewEffects(ctx, tx, p, receipt, now); err != nil {
		return err
	}
	if !changed {
		return nil
	}
	rows, err := tx.Query(ctx, "UPDATE coach_proposals SET status='stale' WHERE status='pending' AND id<>$1 RETURNING id", p.ProposalID)
	if err != nil {
		return err
	}
	remaining, err := pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
	if err != nil {
		return err
	}
	receipt.StaleProposals = append(receipt.StaleProposals, remaining...)
	if _, err := db.New(tx).BumpDataRevision(ctx); err != nil {
		return err
	}
	return calendar.RefreshPlans(ctx, tx, scope, now, metrics)
}
