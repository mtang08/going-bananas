package drafts

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/anchors"
	"strings"
	"time"
)

func saveBlock(ctx context.Context, tx pgx.Tx, p PreparedDecision, now time.Time) (uuid.UUID, bool, error) {
	var doc struct {
		Block struct {
			Decision string          `json:"decision"`
			Fields   json.RawMessage `json:"version_fields"`
		} `json:"block_change"`
		Evidence   []string `json:"evidence_ids"`
		Policies   []string `json:"policy_ids"`
		Confidence struct {
			Decision string `json:"decision"`
		} `json:"confidence"`
	}
	if err := json.Unmarshal(p.parsed.Document, &doc); err != nil {
		return uuid.Nil, false, err
	}
	fields := doc.Block.Fields
	var block uuid.UUID
	version := 0
	if old := p.current.BlockID; old != nil {
		var equal bool
		err := tx.QueryRow(ctx, "SELECT block_uid,version,NOT EXISTS (SELECT 1 FROM jsonb_each($2::jsonb) field WHERE (to_jsonb(v)->field.key) IS DISTINCT FROM field.value) FROM block_versions v WHERE id=$1", old, fields).Scan(&block, &version, &equal)
		if err != nil {
			return uuid.Nil, false, err
		}
		if equal {
			return *old, false, nil
		}
	} else {
		block = uuid.New()
		if _, err := tx.Exec(ctx, "INSERT INTO blocks(id,block_uid) VALUES($1,$2)", uuid.New(), block); err != nil {
			return uuid.Nil, false, err
		}
	}
	id := uuid.New()
	_, err := tx.Exec(ctx, `INSERT INTO block_versions(id,block_uid,version,proposal_id,status,objective,why,maintained_qualities,non_goals,eligible_recipe_ids,progression_dimension,constraints,start_date,review_date,indicators,early_review_triggers,objective_status,benchmark,target_event_id,build_outline)
 SELECT $1,$2,$3,$4,f.status,f.objective,f.why,f.maintained_qualities,f.non_goals,f.eligible_recipe_ids,f.progression_dimension,f.constraints,f.start_date,f.review_date,f.indicators,f.early_review_triggers,f.objective_status,f.benchmark,f.target_event_id,f.build_outline FROM jsonb_populate_record(NULL::block_versions,$5::jsonb) f`, id, block, version+1, p.ProposalID, fields)
	if err != nil {
		return uuid.Nil, false, err
	}
	var reasons struct {
		Why []struct{ Kind, Text string } `json:"why"`
	}
	if err := json.Unmarshal(fields, &reasons); err != nil {
		return uuid.Nil, false, err
	}
	lines := make([]string, 0, len(reasons.Why))
	for _, w := range reasons.Why {
		lines = append(lines, w.Kind+": "+w.Text)
	}
	_, err = tx.Exec(ctx, `INSERT INTO block_decisions(id,block_uid,decision,from_version,to_version,rationale,evidence_ids,policy_ids,confidence,proposal_id,decided_at)
 VALUES($1,$2,$3,nullif($4,0),$5,$6,$7,$8,$9,$10,$11)`, uuid.New(), block, doc.Block.Decision, version, version+1, strings.Join(lines, "\n"), doc.Evidence, doc.Policies, doc.Confidence.Decision, p.ProposalID, now)
	return id, true, err
}

func saveAnchor(ctx context.Context, tx pgx.Tx, p PreparedDecision, raw json.RawMessage) (string, error) {
	var input anchors.Input
	if err := json.Unmarshal(raw, &input); err != nil {
		return "", err
	}
	input.ValidFrom = p.rules.Today
	input.ProposalID = &p.ProposalID
	result, err := anchors.Create(ctx, tx, input, p.rules.Timezone)
	var problem *anchors.Problem
	if errors.As(err, &problem) {
		return "", &Error{problem.Code, problem.Message, problem.Status}
	}
	return result.Key, err
}
