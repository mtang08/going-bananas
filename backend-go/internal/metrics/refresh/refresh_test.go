package refresh

import (
	"os"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/calendar"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

func TestScopeDatabase(t *testing.T) {
	dsn := os.Getenv("ASSESSMENT_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("run guarded assessment DB comparison")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil || cfg.ConnConfig.Database != "garmin_test" || os.Getenv("APP_MODE") != "test" || !strings.HasPrefix(os.Getenv("PGOPTIONS"), "-csearch_path=go_parity_") {
		t.Fatal("requires isolated test schema")
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
	err = pgx.BeginTxFunc(t.Context(), pool, pgx.TxOptions{}, func(tx pgx.Tx) error {
		if err := db.New(tx).LockGlobalWriter(t.Context()); err != nil {
			return err
		}
		switch os.Getenv("ASSESSMENT_SCOPE") {
		case "plan":
			return PlanMetrics(now, nil)(t.Context(), tx, calendar.PlanScope{Dates: []string{"2026-11-22"}}, nil)
		case "manual":
			return CompletionMetrics(now, nil)(t.Context(), tx, calendar.CompletionTargets{ManualOnly: true, Change: calendar.CompletionChange{SessionUID: uuid.MustParse("00000000-0000-0000-0000-000000000001")}})
		default:
			return ScopeMetrics(t.Context(), tx, strings.Split(os.Getenv("ASSESSMENT_SCOPE"), ";"), nil, now, false, nil)
		}
	})
	if err != nil {
		t.Fatal(err)
	}
}
