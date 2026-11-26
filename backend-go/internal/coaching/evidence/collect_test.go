package evidence

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/canonicaljson"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching"
)

func TestPythonDecisionInputs(t *testing.T) {
	path := os.Getenv("EVIDENCE_REFERENCE")
	if path == "" {
		t.Skip("scripts/rewrite/coaching/check_evidence.py supplies the migrated synthetic database and Python result")
	}
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Operation, AsOf string
		Now             time.Time
		SavedHash       string
		Fresh           bool
		Selection       []coaching.SelectionEntry
		Sources         map[string]json.RawMessage
		Guard, Schedule json.RawMessage
		CurrentHash     string
	}
	if err := json.Unmarshal(b, &fixture); err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	c, err := pgx.Connect(ctx, os.Getenv("EVIDENCE_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close(ctx) }()
	tx, err := c.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var db, schema string
	if err := tx.QueryRow(ctx, "select current_database(),current_schema()").Scan(&db, &schema); err != nil || db != "garmin_test" || !strings.HasPrefix(schema, "go_evidence_") {
		t.Fatalf("expected synthetic DB/schema: %v", err)
	}
	got, err := CollectInputs(ctx, tx, fixture.Operation, fixture.AsOf, fixture.Now)
	if err != nil {
		t.Fatal(err)
	}
	compare := func(k string, v any, want []byte) {
		t.Helper()
		raw, err := canonicaljson.Coaching(v)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(raw, want) {
			t.Errorf("canonical mismatch in %s: got %s, want %s", k, raw, want)
		}
	}
	if len(fixture.Sources) != len(got.Sources) {
		t.Errorf("source keys: got %d want %d", len(got.Sources), len(fixture.Sources))
	}
	for key, expected := range fixture.Sources {
		value, exists := got.Sources[key]
		if !exists {
			t.Errorf("missing %s", key)
			continue
		}
		compare(key, value, expected)
	}
	compare("confirmed_strength_sessions", got.ConfirmedStrengthSessions, fixture.Schedule)
	compare("safety_guard", got.SafetyGuard, fixture.Guard)
	kb, _, err := coaching.VerifySelection("../../../../running_coach_kb", fixture.Selection)
	if err != nil {
		t.Fatal(err)
	}
	_, hash, err := coaching.Fingerprint(got.Sources, kb)
	if err != nil {
		t.Fatal(err)
	}
	if hash != fixture.CurrentHash || (hash == fixture.SavedHash) != fixture.Fresh {
		t.Errorf("freshness mismatch for Python-created snapshot: current=%s saved=%s fresh=%t", hash, fixture.SavedHash, fixture.Fresh)
	}
}
