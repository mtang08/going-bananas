package assessment

import (
	"context"
	"errors"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

// check_assessment_db.py supplies a migrated throwaway schema with known seeded
// subject IDs. Ordinary go test never opens a database.
func TestAssessmentPostgres(t *testing.T) {
	dsn := os.Getenv("ASSESSMENT_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("run the scripts/test-db.py assessment")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatal("invalid test database")
	}
	if cfg.ConnConfig.Database != "garmin_test" || os.Getenv("APP_MODE") != "test" || !strings.HasPrefix(os.Getenv("PGOPTIONS"), "-csearch_path=go_parity_") {
		t.Fatal("expected isolated test schema")
	}
	pool, err := pgxpool.NewWithConfig(t.Context(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	now, err := time.Parse(time.RFC3339, os.Getenv("ASSESSMENT_NOW"))
	if err != nil {
		t.Fatal(err)
	}
	for _, key := range strings.Split(os.Getenv("ASSESSMENT_SUBJECTS"), ",") {
		uid := uuid.MustParse(key)
		err := pgx.BeginTxFunc(t.Context(), pool, pgx.TxOptions{}, func(tx pgx.Tx) error {
			ctx := context.Background()
			if err := db.New(tx).LockGlobalWriter(ctx); err != nil {
				return err
			}
			if os.Getenv("ASSESSMENT_INJECT") != "" {
				if _, err := tx.Exec(ctx, "UPDATE session_completions SET reason_note='synthetic in-flight command' WHERE session_uid=$1", uid); err != nil {
					return err
				}
			}
			_, err := Refresh(ctx, tx, uid, now)
			return err
		})
		if os.Getenv("ASSESSMENT_INJECT") != "" {
			var pgErr *pgconn.PgError
			if !errors.As(err, &pgErr) || pgErr.Message != "synthetic assessment failure" {
				t.Fatalf("expected injected failure, got %v", err)
			}
		} else if err != nil {
			t.Fatalf("%s: %v", key, err)
		}
	}
}
