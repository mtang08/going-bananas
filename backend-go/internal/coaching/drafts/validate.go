package drafts

import (
	"context"
	"encoding/json"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
)

// ValidateNormalized applies current source facts and verified knowledge to a
// structurally valid document. It also projects persisted per-change before/after rows.
func ValidateNormalized(ctx context.Context, tx pgx.Tx, v Validation, now time.Time, kbRoot string) (Validation, error) {
	var d DocumentBase
	if err := json.Unmarshal(v.Document, &d); err != nil {
		return v, err
	}
	s, err := LoadSnapshot(ctx, tx, d.SnapshotID)
	if err != nil {
		return v, err
	}
	kb, idx, err := coaching.VerifySelection(kbRoot, s.Selection)
	if err != nil {
		return v, &Error{"knowledge_unavailable", "Verified knowledge is unavailable", 503}
	}
	rules, current, err := LoadRuleContext(ctx, tx, s, now)
	if err != nil {
		return v, err
	}
	v.Changes, err = projectChanges(v.Payload, rules)
	if err != nil {
		return v, err
	}
	v.Status, v.Issues, err = Freshness(s, d, current, kb, now)
	if err != nil || v.Status != "pending" {
		return v, err
	}
	v.Issues, err = ValidateRules(v.Document, v.Payload, rules, idx)
	if len(v.Issues) > 0 {
		v.Status = "invalid"
	}
	return v, err
}
