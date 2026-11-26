package drafts

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// DecisionReceipt is persisted without the proposal ID, matching the Python
// ledger. Replays add the ID from the owning proposal.
type DecisionReceipt struct {
	Status          string      `json:"status"`
	CalendarVersion *int        `json:"calendar_version"`
	BlockVersionID  *uuid.UUID  `json:"block_version_id"`
	AnchorKeys      []string    `json:"anchor_keys"`
	StaleProposals  []uuid.UUID `json:"stale_proposals"`
}
type DecisionResult struct {
	ProposalID uuid.UUID `json:"proposal_id"`
	DecisionReceipt
}
type decisionEffects func(context.Context, pgx.Tx, PreparedDecision, *DecisionReceipt) error

func aliasDecision(ctx context.Context, tx pgx.Tx, id uuid.UUID, key, hash string, receipt DecisionReceipt) error {
	_, err := tx.Exec(ctx, "INSERT INTO coach_decision_keys(idempotency_key,proposal_id,decision_hash,result) VALUES($1,$2,$3,$4)", key, id, hash, receipt)
	return err
}
func readDecision(ctx context.Context, tx pgx.Tx, id uuid.UUID, r DecisionRequest, out *DecisionReceipt) (bool, string, error) {
	var revision int
	var status string
	var oldHash *string
	var saved json.RawMessage
	err := tx.QueryRow(ctx, "SELECT revision,status,decision_hash,decision_result FROM coach_proposals WHERE id=$1 FOR UPDATE", id).Scan(&revision, &status, &oldHash, &saved)
	if err != nil {
		return false, "", missing(err)
	}
	if status == "discarded" {
		return false, "", &Error{"proposal_discarded", "Discarded proposals cannot be decided", 409}
	}
	if r.Revision != revision {
		return false, "", &Error{"proposal_revision_conflict", "This proposal was revised. Reload and review the latest revision.", 409}
	}
	hash, err := r.hash(id)
	if err != nil {
		return false, "", err
	}
	var owner uuid.UUID
	var keyHash string
	err = tx.QueryRow(ctx, "SELECT proposal_id,decision_hash FROM coach_decision_keys WHERE idempotency_key=$1", r.Key).Scan(&owner, &keyHash)
	newKey := errors.Is(err, pgx.ErrNoRows)
	if err != nil && !newKey {
		return false, "", err
	}
	if !newKey && owner != id {
		return false, "", &Error{"idempotency_conflict", "Key belongs to another proposal", 409}
	}
	conflict := &Error{"decision_conflict", "Decision selection changed", 409}
	if !newKey && keyHash != hash {
		return false, "", conflict
	}
	switch status {
	case "accepted", "partially_accepted", "rejected":
		if oldHash == nil || *oldHash != hash || len(saved) == 0 {
			return false, "", conflict
		}
		if err := json.Unmarshal(saved, out); err != nil {
			return false, "", err
		}
		if newKey {
			err = aliasDecision(ctx, tx, id, r.Key, hash, *out)
		} else {
			err = nil
		}
		return true, hash, err
	case "pending":
		return false, hash, nil
	default:
		return false, "", &Error{"proposal_stale", "Proposal is no longer pending", 409}
	}
}

func (s Store) decide(ctx context.Context, id uuid.UUID, r DecisionRequest, now time.Time, kbRoot string, apply decisionEffects) (DecisionResult, error) {
	result := DecisionResult{ProposalID: id, DecisionReceipt: DecisionReceipt{AnchorKeys: []string{}, StaleProposals: []uuid.UUID{}}}
	var committedError error
	err := pgx.BeginTxFunc(ctx, s.Pool, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		if err := LockPlanning(ctx, tx); err != nil {
			return err
		}
		done, hash, err := readDecision(ctx, tx, id, r, &result.DecisionReceipt)
		if err != nil || done {
			return err
		}
		p, err := PrepareDecision(ctx, tx, id, r, now, kbRoot)
		if err != nil {
			var problem *Error
			if errors.As(err, &problem) && (problem.Code == "stale_evidence" || problem.Code == "snapshot_not_found" || problem.Code == "proposal_stale") {
				committedError = err
				if problem.Code == "snapshot_not_found" {
					committedError = &Error{"proposal_stale", "Proposal expired", 409}
				}
				_, err = tx.Exec(ctx, "UPDATE coach_proposals SET status='stale' WHERE id=$1", id)
			}
			return err
		}
		var total int
		err = tx.QueryRow(ctx, `SELECT jsonb_array_length(coalesce(payload->'changes','[]'::jsonb))+jsonb_array_length(coalesce(payload->'anchor_changes','[]'::jsonb))+
   CASE WHEN block_change IS NULL OR block_change='null'::jsonb THEN 0 ELSE 1 END FROM coach_proposals WHERE id=$1`, id).Scan(&total)
		if err != nil {
			return err
		}
		count := len(r.Accept) + len(r.Anchors)
		if r.Block {
			count++
		}
		switch count {
		case total:
			result.Status = "accepted"
		case 0:
			result.Status = "rejected"
		default:
			result.Status = "partially_accepted"
		}
		if result.Status != "rejected" {
			if err := apply(ctx, tx, p, &result.DecisionReceipt); err != nil {
				return err
			}
		}
		_, err = tx.Exec(ctx, "UPDATE coach_proposal_changes SET decision=CASE WHEN change_id=ANY($2::text[]) THEN 'accepted' ELSE 'rejected' END WHERE proposal_id=$1", id, r.Accept)
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx, "UPDATE coach_proposals SET status=$2,decided_at=$3,decision_idempotency_key=$4,decision_hash=$5,decision_result=$6 WHERE id=$1", id, result.Status, now, r.Key, hash, result.DecisionReceipt)
		if err != nil {
			return err
		}
		return aliasDecision(ctx, tx, id, r.Key, hash, result.DecisionReceipt)
	})
	if err != nil {
		return DecisionResult{}, err
	}
	if committedError != nil {
		return DecisionResult{}, committedError
	}
	return result, nil
}
