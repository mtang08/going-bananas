package refresh

import (
	"errors"
	"fmt"
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
	cfg.MaxConns = 1
	pool, err := pgxpool.NewWithConfig(t.Context(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	now, err := time.Parse(time.RFC3339, os.Getenv("ASSESSMENT_NOW"))
	if err != nil {
		t.Fatal(err)
	}
	if mode := os.Getenv("ASSESSMENT_SCOPE"); mode == "read-stored" || mode == "read-preview" {
		err = pgx.BeginTxFunc(t.Context(), pool, pgx.TxOptions{AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
			for _, metric := range []string{"work_interval_execution", "intensity_time_distribution", "aerobic_efficiency", "session_rpe_load", "symptom_response_timeline", "long_run_exposure", "recovery_multisignal_summary"} {
				key := "00000000-0000-0000-0000-0000000000fc"
				if metric == "recovery_multisignal_summary" {
					key = "night:2026-11-22"
				}
				row, err := ReadResult(t.Context(), tx, metric, key, now)
				if err != nil {
					return err
				}
				if row == nil || row["metric_id"] != metric || (row["id"] == nil) != (mode == "read-preview") {
					return fmt.Errorf("read result %s identity mismatch", metric)
				}
			}
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
		return
	}
	if os.Getenv("ASSESSMENT_SCOPE") == "marker" {
		testRevisionMarker(t, pool)
		return
	}
	err = pgx.BeginTxFunc(t.Context(), pool, pgx.TxOptions{}, func(tx pgx.Tx) error {
		if err := db.New(tx).LockGlobalWriter(t.Context()); err != nil {
			return err
		}
		switch os.Getenv("ASSESSMENT_SCOPE") {
		case "link", "link-fail":
			uid := uuid.MustParse("00000000-0000-0000-0000-0000000000fb")
			activity := uuid.MustParse("00000000-0000-0000-0000-0000000000fc")
			_, err := calendar.SaveRecordingLink(t.Context(), tx, uid, calendar.RecordingLink{ActivityID: &activity}, now, AssessCompletion(now), calendar.DerivedRefresh(now, CompletionMetrics(now, nil)))
			return err
		case "plan":
			return PlanMetrics(now, nil)(t.Context(), tx, calendar.PlanScope{Dates: []string{"2026-11-22"}}, nil)
		case "manual":
			return CompletionMetrics(now, nil)(t.Context(), tx, calendar.CompletionTargets{ManualOnly: true, Change: calendar.CompletionChange{SessionUID: uuid.MustParse("00000000-0000-0000-0000-000000000001")}})
		default:
			return ScopeMetrics(t.Context(), tx, strings.Split(os.Getenv("ASSESSMENT_SCOPE"), ";"), nil, now, false, nil)
		}
	})
	if os.Getenv("ASSESSMENT_SCOPE") == "link-fail" {
		if err == nil || !strings.Contains(err.Error(), "synthetic linked metric failure") {
			t.Fatalf("expected injected metric error, got %v", err)
		}
		return
	}
	if err != nil {
		t.Fatal(err)
	}
}

func testRevisionMarker(t *testing.T, pool *pgxpool.Pool) {
	ctx := t.Context()
	var start int32
	var initialPID int
	if err := pool.QueryRow(ctx, "SELECT data_revision,pg_backend_pid() FROM app_state WHERE id=1").Scan(&start, &initialPID); err != nil {
		t.Fatal(err)
	}
	bump := func(tx pgx.Tx, want int32) error {
		n, err := db.New(tx).BumpDataRevision(ctx)
		if err == nil && n != want {
			return fmt.Errorf("revision %d; expected %d", n, want)
		}
		return err
	}
	injected := errors.New("synthetic rollback")
	for i := range 3 {
		err := pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{}, func(tx pgx.Tx) error {
			var pid int
			if err := tx.QueryRow(ctx, "SELECT pg_backend_pid()").Scan(&pid); err != nil {
				return err
			}
			if pid != initialPID {
				return errors.New("fixture must reuse physical connection")
			}
			want := start + 1
			if i == 2 {
				want++
			}
			if i == 0 {
				if err := bump(tx, want); err != nil {
					return err
				}
				return injected
			}
			err := pgx.BeginFunc(ctx, tx, func(nested pgx.Tx) error {
				if err := bump(nested, want); err != nil {
					return err
				}
				return injected
			})
			if !errors.Is(err, injected) {
				return fmt.Errorf("nested rollback: %w", err)
			}
			if err := bump(tx, want); err != nil {
				return err
			}
			if err := pgx.BeginFunc(ctx, tx, func(nested pgx.Tx) error { return bump(nested, want) }); err != nil {
				return err
			}
			return bump(tx, want)
		})
		if i == 0 && errors.Is(err, injected) {
			continue
		}
		if err != nil {
			t.Fatal(err)
		}
	}
}
