package drafts

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
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
	var a struct {
		Kind       string
		Low        float64   `json:"value_low"`
		High       *float64  `json:"value_high"`
		Supersedes *string   `json:"supersedes_key"`
		At         time.Time `json:"calibrated_at"`
	}
	if err := json.Unmarshal(raw, &a); err != nil {
		return "", err
	}
	for _, n := range []*float64{&a.Low, a.High} {
		if n == nil {
			continue
		}
		var msg string
		switch {
		case strings.HasPrefix(a.Kind, "hr_") && (*n < 30 || *n > 230):
			msg = "Heart rate anchor must be 30 to 230 bpm"
		case strings.HasPrefix(a.Kind, "speed_") && (*n <= 0 || *n > 10):
			msg = "Speed anchor must be above zero and at most 10 m/s"
		case strings.HasPrefix(a.Kind, "performance_") && *n <= 0:
			msg = "Performance anchor must be positive"
		}
		if msg != "" {
			return "", &Error{"invalid_anchor_value", msg, 422}
		}
	}
	var previous, from string
	err := tx.QueryRow(ctx, `SELECT a.anchor_key,a.valid_from::text FROM intensity_anchors a WHERE a.kind=$1 AND NOT EXISTS(SELECT 1 FROM intensity_anchors child WHERE child.kind=a.kind AND child.supersedes_key=a.anchor_key)
 ORDER BY a.valid_from DESC,a.calibrated_at DESC,a.anchor_key DESC LIMIT 1`, a.Kind).Scan(&previous, &from)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		if a.Supersedes != nil {
			return "", &Error{"anchor_supersede_required", "No predecessor exists for this anchor", 409}
		}
	case err != nil:
		return "", err
	case a.Supersedes == nil:
		return "", &Error{"anchor_supersede_required", "Specify the anchor being superseded", 409}
	case *a.Supersedes != previous:
		return "", &Error{"anchor_superseded", "The selected predecessor has a newer successor", 409}
	case p.rules.Today < from:
		return "", &Error{"anchor_backdate_conflict", "Successor cannot predate its predecessor", 422}
	}
	base := a.Kind + "-" + p.rules.Today
	key := base
	for n := 2; ; n++ {
		var exists bool
		if err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM intensity_anchors WHERE anchor_key=$1)", key).Scan(&exists); err != nil {
			return "", err
		}
		if !exists {
			break
		}
		key = fmt.Sprintf("%s-%d", base, n)
	}
	_, err = tx.Exec(ctx, `INSERT INTO intensity_anchors(id,anchor_key,kind,value_low,value_high,unit,protocol,confidence,status,calibrated_at,valid_from,review_after,source_activity_id,source_event_id,proposal_id,conditions,notes,supersedes_key)
 SELECT $1,$2,f.kind,f.value_low,f.value_high,f.unit,f.protocol,f.confidence,'active',f.calibrated_at,$3::date,(f.calibrated_at AT TIME ZONE $4)::date+84,f.source_activity_id,f.source_event_id,$5,f.conditions,f.notes,f.supersedes_key FROM jsonb_populate_record(NULL::intensity_anchors,$6::jsonb) f`, uuid.New(), key, p.rules.Today, p.rules.Timezone, p.ProposalID, raw)
	return key, err
}
