// Package reference supplies the Python schema, live fact collector, and
// coaching rules while their native replacements are being ported. It runs
// only in synthetic mode and can only read the exported Go transaction snapshot.
package reference

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drafts"
)

type Adapter struct{ Root, Python string }

func (a Adapter) run(ctx context.Context, op string, in, out any) error {
	mode := os.Getenv("APP_MODE")
	if mode != "demo" && mode != "test" {
		return errors.New("reference adapter requires synthetic mode")
	}
	b, err := json.Marshal(in)
	if err != nil {
		return err
	}
	cmd := exec.CommandContext(ctx, a.Python, filepath.Join(a.Root, "scripts/rewrite/coaching/reference_validation.py"), op)
	cmd.Stdin = bytes.NewReader(b)
	raw, err := cmd.Output()
	if err != nil {
		return errors.New("reference validation failed")
	}
	return json.Unmarshal(raw, out)
}

func (a Adapter) Validate(ctx context.Context, tx pgx.Tx, raw json.RawMessage, now time.Time) (drafts.Validation, error) {
	var v drafts.Validation
	if err := a.run(ctx, "parse", raw, &v); err != nil || v.Document == nil {
		return v, err
	}
	var d drafts.DocumentBase
	if err := json.Unmarshal(v.Document, &d); err != nil {
		return v, err
	}
	s, err := drafts.LoadSnapshot(ctx, tx, d.SnapshotID)
	if err != nil {
		return v, err
	}
	kb, idx, err := coaching.VerifySelection(filepath.Join(a.Root, "running_coach_kb"), s.Selection)
	if err != nil {
		return v, &drafts.Error{Code: "knowledge_unavailable", Message: "Verified knowledge is unavailable", Status: 503}
	}
	var exported string
	if err := tx.QueryRow(ctx, "SELECT pg_export_snapshot()").Scan(&exported); err != nil {
		return v, err
	}
	in := map[string]any{"snapshot": exported, "now": now, "document": v.Payload, "knowledge": kb, "index": idx}
	var response struct {
		Context drafts.RuleContext     `json:"rule_context"`
		Groups  drafts.ReferenceGroups `json:"groups"`
		Current drafts.CurrentEvidence `json:"current"`
		Changes []drafts.Change        `json:"changes"`
	}
	if err := a.run(ctx, "rules", in, &response); err != nil {
		return v, err
	}
	v.Changes = response.Changes
	v.Status, v.Issues, err = drafts.Freshness(s, d, response.Current, kb, now)
	if err == nil && v.Status == "pending" {
		v.Issues, err = drafts.ValidateRules(v.Document, v.Payload, response.Context, idx, response.Groups)
		if len(v.Issues) > 0 {
			v.Status = "invalid"
		}
	}
	return v, err
}
