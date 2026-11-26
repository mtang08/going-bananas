// Package reference supplies Python proposal schema normalization to synthetic commands.
// All database reads, domain rules, and writes execute in Go.
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
	return drafts.ValidateNormalized(ctx, tx, v, now, filepath.Join(a.Root, "running_coach_kb"))
}
