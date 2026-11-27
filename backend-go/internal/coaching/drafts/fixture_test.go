package drafts

import (
	"context"
	"encoding/json"
	"os"
	"regexp"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/snapshots"
	"github.com/mtang08/going-bananas/backend-go/internal/workspacemigrate"
)

const testKBRoot = "../../../../running_coach_kb"

var testNow = time.Date(2026, 11, 16, 15, 0, 0, 0, time.UTC)

func draftTestPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("run scripts/test-db.py dashboard for synthetic PostgreSQL")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatal("invalid dashboard test database configuration")
	}
	if cfg.ConnConfig.Database != "garmin_test" || (cfg.ConnConfig.Host != "127.0.0.1" && cfg.ConnConfig.Host != "localhost") {
		t.Fatal("requires a dedicated loopback garmin_test database")
	}
	ctx := t.Context()
	admin, err := pgx.ConnectConfig(ctx, cfg.ConnConfig.Copy())
	if err != nil {
		t.Fatal("connect to dashboard test database")
	}
	t.Cleanup(func() { _ = admin.Close(context.Background()) })
	var name, parent string
	if err := admin.QueryRow(ctx, "SELECT current_database(), current_schema()").Scan(&name, &parent); err != nil ||
		name != "garmin_test" || !regexp.MustCompile(`^go_parity_[0-9a-f]{32}$`).MatchString(parent) {
		t.Fatal("requires a disposable dashboard schema")
	}

	schema := "go_draft_test_" + uuid.NewString()
	quoted := pgx.Identifier{schema}.Sanitize()
	if err := pgx.BeginTxFunc(ctx, admin, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, "CREATE SCHEMA "+quoted)
		return err
	}); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := pgx.BeginTxFunc(ctx, admin, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
			_, err := tx.Exec(ctx, "DROP SCHEMA "+quoted+" CASCADE")
			return err
		}); err != nil {
			t.Error(err)
		}
	})
	cfg.ConnConfig.RuntimeParams["search_path"] = quoted
	cfg.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal("connect to disposable draft schema")
	}
	t.Cleanup(pool.Close)
	conn, err := pool.Acquire(ctx)
	if err != nil {
		t.Fatal("open disposable draft schema")
	}
	defer conn.Release()
	result, err := workspacemigrate.Run(ctx, conn.Conn(), "", "", false)
	if err != nil || result.Action != "baseline" {
		t.Fatalf("provision disposable draft schema: %+v, %v", result, err)
	}
	return pool
}

func pendingTestDraft(t *testing.T, pool *pgxpool.Pool, changes int) Receipt {
	t.Helper()
	ctx := t.Context()
	const operation = "proceed_or_modify_today"
	day := testNow.Format(time.DateOnly)
	var snapshot map[string]any
	err := pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		var err error
		snapshot, err = snapshots.Build(ctx, tx, operation, day, testNow, testKBRoot)
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	edits := []map[string]any{
		{"change_id": "c1", "op": "add", "reason": "Recovery day",
			"after": map[string]any{"local_date": day, "kind": "rest", "intent": "Recovery"}},
		{"change_id": "c2", "op": "add", "reason": "Optional rest",
			"after": map[string]any{"local_date": day, "kind": "rest", "intent": "Optional rest", "slot": 1}},
	}
	document, err := json.Marshal(map[string]any{
		"schema_version": "coach_proposal.v2", "operation": operation, "snapshot_id": snapshot["snapshot_id"],
		"base_calendar_version": 0, "base_block_version_id": nil, "headline": "Synthetic recovery",
		"why":             []map[string]string{{"kind": "observation", "text": "Synthetic session"}},
		"uncertainty":     []string{"Synthetic uncertainty"},
		"change_triggers": []map[string]string{{"when": "Energy drops", "then": "Rest"}},
		"next_check":      map[string]string{"on": day, "check": "Review response"},
		"confidence":      map[string]string{"decision": "moderate", "evidence": "moderate", "data": "moderate"},
		"changes":         edits[:changes],
		"evidence_ids":    []string{}, "policy_ids": []string{}, "recipe_ids": []string{},
		"skill_version": "running-coach.v1",
	})
	if err != nil {
		t.Fatal(err)
	}
	receipt, err := (Store{Pool: pool}).Submit(ctx, document, testNow, NewValidator(testKBRoot))
	if err != nil || receipt.Status != "pending" || receipt.Revision != 1 {
		t.Fatalf("submit synthetic draft: %+v, %v", receipt, err)
	}
	return receipt.Receipt
}
