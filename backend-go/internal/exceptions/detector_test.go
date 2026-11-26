package exceptions

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func TestFindingLifecycle(t *testing.T) {
	dsn := os.Getenv("PROPOSAL_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires a migrated synthetic PostgreSQL schema")
	}
	cfg, err := pgx.ParseConfig(dsn)
	if err != nil || cfg.Database != "garmin_test" || (cfg.Host != "127.0.0.1" && cfg.Host != "localhost") || !strings.Contains(os.Getenv("PGOPTIONS"), "search_path=go_parity_") {
		t.Fatal("expected disposable local parity schema")
	}
	ctx := t.Context()
	conn, err := pgx.ConnectConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = conn.Close(context.Background()) })
	tx, err := conn.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = tx.Rollback(context.Background()) })
	if _, err := tx.Exec(ctx, "CREATE TEMP TABLE exception_findings (LIKE exception_findings INCLUDING ALL); CREATE TEMP TABLE exception_patches (LIKE exception_patches INCLUDING ALL); CREATE TEMP TABLE events (LIKE events INCLUDING ALL)"); err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 11, 21, 12, 0, 0, 0, time.UTC)
	c := Candidate{Code: "SYM_NEW_SITE", Category: "symptoms_illness", Severity: "observe", Key: "site:ankle|na", Summary: "synthetic", At: now, Evidence: []Evidence{}}
	run := func(at time.Time, found ...Candidate) map[string]any {
		t.Helper()
		v, err := maintain(ctx, tx, at, at.Format(time.DateOnly), found)
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
	first := run(now, c)
	id := first["new_finding_ids"].([]uuid.UUID)[0]
	// The active finding can be addressed without losing its source identity.
	c.Severity = "caution"
	outCaution := run(now.Add(time.Minute), c)
	if recs := outCaution["review_recommended"].([]recommendation); len(recs) != 1 || recs[0].Operation != "exception_review" {
		t.Fatal(recs)
	}
	if _, err := tx.Exec(ctx, "UPDATE exception_findings SET status='addressed' WHERE id=$1", id); err != nil {
		t.Fatal(err)
	}
	addressed := run(now.Add(2*time.Minute), c)
	if len(addressed["new_finding_ids"].([]uuid.UUID)) != 0 || len(addressed["review_recommended"].([]recommendation)) != 0 {
		t.Fatal(addressed)
	}
	c.Severity = "escalate"
	raised := run(now.Add(time.Hour), c)
	recs := raised["review_recommended"].([]recommendation)
	if len(recs) != 1 || recs[0].Operation != "review_training_block" || recs[0].IDs[0] != id || !strings.Contains(recs[0].Reason, "symptom") {
		t.Fatal(recs)
	}
	c.Severity = "observe"
	out := run(now.Add(2*time.Hour), c)
	if len(out["new_finding_ids"].([]uuid.UUID)) != 0 || len(out["review_recommended"].([]recommendation)) != 1 {
		t.Fatal(out)
	}
	if _, err := tx.Exec(ctx, "UPDATE exception_findings SET status='dismissed',closed_at=$2 WHERE id=$1", id, now); err != nil {
		t.Fatal(err)
	}
	out = run(now.Add(3*time.Hour), c)
	if len(out["new_finding_ids"].([]uuid.UUID)) != 0 || len(out["review_recommended"].([]recommendation)) != 0 {
		t.Fatal(out)
	}
	c.At = now.Add(time.Minute)
	reopened := run(now.Add(4*time.Hour), c)["new_finding_ids"].([]uuid.UUID)
	if len(reopened) != 1 || reopened[0] == id {
		t.Fatal(reopened)
	}
	run(now.AddDate(0, 0, 15))
	var status string
	var version int
	if err := tx.QueryRow(ctx, "SELECT status,version FROM exception_findings WHERE id=$1", reopened[0]).Scan(&status, &version); err != nil || status != "expired" || version != 2 {
		t.Fatal(status, version, err)
	}
	// A failed later candidate must not leave the earlier insert durable.
	save, err := tx.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	firstCandidate := c
	firstCandidate.Key = "rollback-first"
	bad := c
	bad.Key = "rollback-second"
	bad.Severity = "invalid"
	if _, err := maintain(ctx, save, now, now.Format(time.DateOnly), []Candidate{firstCandidate, bad}); err == nil {
		t.Fatal("missing injected DB failure")
	}
	if err := save.Rollback(ctx); err != nil {
		t.Fatal(err)
	}
	var count int
	if err := tx.QueryRow(ctx, "SELECT count(*) FROM exception_findings WHERE entity_key='rollback-first'").Scan(&count); err != nil || count != 0 {
		t.Fatal(count, err)
	}

}
