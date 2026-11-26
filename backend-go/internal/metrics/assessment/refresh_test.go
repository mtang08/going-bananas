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
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/spacing"
)

// check_assessment_db.py supplies a migrated throwaway schema with known seeded
// subject IDs. Ordinary go test never opens a database.
func TestPythonDatabase(t *testing.T) {
	dsn := os.Getenv("ASSESSMENT_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("run the isolated assessment comparison")
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
	if mode := os.Getenv("ASSESSMENT_SPACING"); mode != "" {
		err := pgx.BeginTxFunc(t.Context(), pool, pgx.TxOptions{}, func(tx pgx.Tx) error {
			if err := db.New(tx).LockGlobalWriter(t.Context()); err != nil {
				return err
			}
			switch mode {
			case "date":
				return spacing.RefreshDates(t.Context(), tx, []string{"2026-11-11"}, now)
			default:
				_, err := spacing.RefreshCompletions(t.Context(), tx, []uuid.UUID{uuid.MustParse(os.Getenv("ASSESSMENT_SUBJECTS"))}, mode == "association", now)
				return err
			}
		})
		if err != nil {
			t.Fatal(err)
		}
		return
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
