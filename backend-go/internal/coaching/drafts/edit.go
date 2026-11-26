package drafts

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
)

type Issue struct {
	Code    string `json:"code"`
	Path    string `json:"path"`
	Message string `json:"message"`
}

type CommandError struct {
	ErrorInfo Error   `json:"error"`
	Issues    []Issue `json:"issues"`
}

func (e *CommandError) Error() string { return e.ErrorInfo.Error() }
func (e *CommandError) Unwrap() error { return &e.ErrorInfo }

type EditResult struct {
	Receipt
	Issues []Issue `json:"issues"`
}

type RevisionRequest struct {
	ExpectedRevision int             `json:"expected_revision"`
	Reason           string          `json:"reason"`
	Document         json.RawMessage `json:"document"`
}

type Validation struct {
	Document json.RawMessage `json:"document"` // Full normalized fields including defaults.
	Payload  json.RawMessage `json:"payload"`  // Original authored field set, after normalization.
	Status   string          `json:"status"`
	Issues   []Issue         `json:"issues"`
	Changes  []Change        `json:"changes"`
}
type Validator func(context.Context, pgx.Tx, json.RawMessage, time.Time) (Validation, error)

func decodeObject(raw []byte) (map[string]any, error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var obj map[string]any
	err := dec.Decode(&obj)
	if err == nil && obj == nil {
		err = errors.New("expected JSON object")
	}
	return obj, err
}

func hashObject(obj map[string]any) (string, error) {
	b, err := coaching.CanonicalJSON(obj)
	if err != nil {
		return "", err
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:]), nil
}

func (s Store) Submit(ctx context.Context, raw json.RawMessage, now time.Time, validate Validator) (EditResult, error) {
	var result EditResult
	err := pgx.BeginTxFunc(ctx, s.Pool, pgx.TxOptions{IsoLevel: pgx.ReadCommitted, AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		if err := LockPlanning(ctx, tx); err != nil {
			return err
		}
		obj, err := decodeObject(raw)
		if err != nil {
			return err
		}
		hash, err := hashObject(obj)
		if err != nil {
			return err
		}
		err = tx.QueryRow(ctx, "SELECT id,revision,status,coalesce(validation_errors,'[]'::jsonb) FROM coach_proposals WHERE input_hash=$1", hash).Scan(&result.ID, &result.Revision, &result.Status, &result.Issues)
		if err == nil {
			return nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		var active uuid.UUID
		var rev int
		err = tx.QueryRow(ctx, "SELECT id,revision FROM coach_proposals WHERE status IN ('pending','stale','invalid') FOR UPDATE").Scan(&active, &rev)
		if err == nil {
			return &CommandError{Error{"active_proposal_exists", fmt.Sprintf("Proposal %s is still open. Review or discard it before submitting another.", active), 409}, []Issue{{"active_proposal_id", "active_proposal_id", active.String()}, {"active_revision", "active_revision", fmt.Sprint(rev)}}}
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		v, err := validate(ctx, tx, raw, now)
		if err != nil {
			return err
		}
		if v.Document == nil {
			return &CommandError{Error{"invalid_proposal", "Proposal schema invalid", 422}, v.Issues}
		}
		result = EditResult{Receipt{uuid.New(), 1, v.Status}, v.Issues}
		if err := writeDocument(ctx, tx, result.Receipt, v, now, hash, true); err != nil {
			return err
		}
		return saveRevision(ctx, tx, result.Receipt, now, "Original proposal", v.Payload, []string{}, []string{}, nil)
	})
	if err != nil {
		return EditResult{}, err
	}
	return result, nil
}

func changeMap(obj map[string]any) map[string]any {
	result := map[string]any{}
	for _, r := range asSlice(obj["changes"]) {
		v, _ := r.(map[string]any)
		id, _ := v["change_id"].(string)
		result[id] = v
	}
	return result
}
func asSlice(v any) []any { items, _ := v.([]any); return items }

func differences(before, after map[string]any, exclude string) []string {
	changed := map[string]bool{}
	for k, v := range before {
		if k != exclude && !reflect.DeepEqual(v, after[k]) {
			changed[k] = true
		}
	}
	for k, v := range after {
		if k != exclude && !reflect.DeepEqual(v, before[k]) {
			changed[k] = true
		}
	}
	keys := make([]string, 0, len(changed))
	for k := range changed {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	return keys
}

func (s Store) Revise(ctx context.Context, id uuid.UUID, req RevisionRequest, now time.Time, validate Validator) (EditResult, error) {
	var result EditResult
	err := pgx.BeginTxFunc(ctx, s.Pool, pgx.TxOptions{IsoLevel: pgx.ReadCommitted, AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		if err := LockPlanning(ctx, tx); err != nil {
			return err
		}
		var old json.RawMessage
		err := tx.QueryRow(ctx, "SELECT id,revision,status,payload FROM coach_proposals WHERE id=$1 FOR UPDATE", id).Scan(&result.ID, &result.Revision, &result.Status, &old)
		if err != nil {
			return missing(err)
		}
		switch result.Status {
		case "pending", "invalid", "stale":
		default:
			return &Error{"proposal_decided", "This proposal has a decision. Propose changes to the current calendar instead.", 409}
		}
		if strings.TrimSpace(req.Reason) == "" {
			return &Error{"invalid_revision", "Explain the requested revision", 422}
		}
		obj, err := decodeObject(req.Document)
		if err != nil {
			return err
		}
		hash, err := hashObject(map[string]any{"expected_revision": req.ExpectedRevision, "reason": req.Reason, "document": obj})
		if err != nil {
			return err
		}
		result.Issues = []Issue{}
		if req.ExpectedRevision != result.Revision {
			var replay bool
			err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM coach_proposal_revisions WHERE proposal_id=$1 AND revision=$2 AND request_hash=$3)", id, result.Revision, hash).Scan(&replay)
			if err != nil {
				return err
			}
			if req.ExpectedRevision+1 == result.Revision && replay {
				return nil
			}
			return &Error{"proposal_revision_conflict", "This proposal was revised. Read the latest draft before editing.", 409}
		}
		v, err := validate(ctx, tx, req.Document, now)
		if err != nil {
			return err
		}
		if v.Document == nil {
			return &CommandError{Error{"invalid_proposal", "Revision schema invalid; existing draft unchanged", 422}, v.Issues}
		}
		if v.Status != "pending" {
			e := Error{"invalid_proposal", "Revision failed validation; existing draft unchanged", 422}
			if v.Status == "stale" {
				e.Code, e.Status = "stale_evidence", 409
			}
			return &CommandError{e, v.Issues}
		}
		var same bool
		if err := tx.QueryRow(ctx, "SELECT $1::jsonb=$2::jsonb", old, v.Payload).Scan(&same); err != nil {
			return err
		}
		if same && result.Status == "pending" {
			return nil
		}
		before, err := decodeObject(old)
		if err != nil {
			return err
		}
		after, err := decodeObject(v.Payload)
		if err != nil {
			return err
		}
		result.Revision++
		result.Status = "pending"
		if err := writeDocument(ctx, tx, result.Receipt, v, now, "", false); err != nil {
			return err
		}
		return saveRevision(ctx, tx, result.Receipt, now, strings.TrimSpace(req.Reason), v.Payload, differences(changeMap(before), changeMap(after), ""), differences(before, after, "changes"), &hash)
	})
	if err != nil {
		return EditResult{}, err
	}
	return result, nil
}

const documentFields = `operation,snapshot_id,base_calendar_version,base_block_version_id,
headline,why,uncertainty,change_triggers,next_check,coach_note,confidence,evidence_ids,
policy_ids,recipe_ids,escalation,block_change,anchor_changes,skill_version`

func writeDocument(ctx context.Context, tx pgx.Tx, r Receipt, v Validation, now time.Time, hash string, insert bool) error {
	args := []any{r.ID, v.Document, r.Status, r.Revision, v.Payload, v.Issues}
	var err error
	if insert {
		_, err = tx.Exec(ctx, "INSERT INTO coach_proposals (id,status,revision,payload,validation_errors,submitted_at,input_hash,"+documentFields+") SELECT $1::uuid,$3::varchar,$4::integer,$5::jsonb,$6::jsonb,$7::timestamptz,$8::varchar,"+documentFields+" FROM jsonb_populate_record(NULL::coach_proposals,$2::jsonb)", append(args, now, hash)...)
	} else {
		_, err = tx.Exec(ctx, "UPDATE coach_proposals SET (status,revision,payload,validation_errors,legacy_text,"+documentFields+")=(SELECT $3::varchar,$4::integer,$5::jsonb,$6::jsonb,NULL::text,"+documentFields+" FROM jsonb_populate_record(NULL::coach_proposals,$2::jsonb)) WHERE id=$1", args...)
		if err == nil {
			_, err = tx.Exec(ctx, "DELETE FROM coach_proposal_changes WHERE proposal_id=$1", r.ID)
		}
	}
	if err != nil {
		return err
	}
	for _, c := range v.Changes {
		if _, err := tx.Exec(ctx, `INSERT INTO coach_proposal_changes(id,proposal_id,change_id,op,session_uid,before,after,reason,decision)
			VALUES($1,$2,$3,$4,$5,$6,$7,$8,'pending')`, uuid.New(), r.ID, c.ID, c.Operation, c.SessionUID, c.Before, c.After, c.Reason); err != nil {
			return err
		}
	}
	return nil
}

func saveRevision(ctx context.Context, tx pgx.Tx, r Receipt, now time.Time, reason string, payload json.RawMessage, ids, fields []string, hash *string) error {
	_, err := tx.Exec(ctx, `INSERT INTO coach_proposal_revisions(proposal_id,revision,saved_at,reason,payload,changed_change_ids,changed_fields,request_hash) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`, r.ID, r.Revision, now, reason, payload, ids, fields, hash)
	return err
}
