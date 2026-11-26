package calendar

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"reflect"
	"regexp"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type reportCase struct {
	Name, Error    string
	UID            uuid.UUID
	Fail           bool
	Stored         map[string]any
	Revision, Head int
	Body           struct {
		Expected int          `json:"expected_version"`
		Status   ReportStatus `json:"status"`
		Reason   *string      `json:"modification_reason"`
		Note     *string      `json:"reason_note"`
	}
}

// scripts/rewrite/check_self_reports.py runs the corresponding Python service
// commands and supplies their durable outcomes from an independent schema.
func TestSelfReportsPostgres(t *testing.T) {
	path := os.Getenv("COMPLETION_CASES")
	if path == "" {
		t.Skip("requires the migrated Python comparison fixture")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cases []reportCase
	if err := json.Unmarshal(raw, &cases); err != nil || len(cases) == 0 {
		t.Fatalf("invalid corpus: %v", err)
	}
	ctx := t.Context()
	cfg, err := pgxpool.ParseConfig("")
	if err != nil || cfg.ConnConfig.Database != "garmin_test" || (cfg.ConnConfig.Host != "127.0.0.1" && cfg.ConnConfig.Host != "localhost") {
		t.Fatal("expected the local garmin_test database")
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	var schema string
	if err := pool.QueryRow(ctx, "SELECT current_schema()").Scan(&schema); err != nil || !regexp.MustCompile(`^go_parity_[0-9a-f]{32}$`).MatchString(schema) {
		t.Fatal("expected a disposable schema")
	}
	now := time.Date(2026, 3, 9, 3, 30, 0, 0, time.UTC)
	injected := errors.New("injected refresh failure")
	for _, tc := range cases {
		t.Run(tc.Name, func(t *testing.T) {
			input := SelfReport{ExpectedVersion: tc.Body.Expected, Status: tc.Body.Status, ModificationReason: tc.Body.Reason, ReasonNote: tc.Body.Note}
			var refreshed bool
			change, err := SaveSelfReport(ctx, pool, tc.UID, input, now, func(ctx context.Context, tx pgx.Tx, change CompletionChange) error {
				refreshed = true
				// This refresh sees the source write and its revision on its own transaction.
				var exists bool
				if err := tx.QueryRow(ctx, "SELECT EXISTS(SELECT FROM session_completions WHERE session_uid=$1)", tc.UID).Scan(&exists); err != nil {
					return err
				}
				if exists != (change.After != nil) {
					t.Fatal("refresh did not see source mutation")
				}
				if tc.Fail {
					return injected
				}
				return nil
			})
			code := ""
			var problem *Problem
			switch {
			case errors.As(err, &problem):
				code = problem.Code
			case errors.Is(err, injected):
				code = "refresh_failure"
			case err != nil:
				t.Fatal(err)
			}
			if code != tc.Error {
				t.Fatalf("got %q, Python returned %q", code, tc.Error)
			}
			if tc.Name == "clear prior recording" && (!change.PreviousRecordingDay.Valid || change.PreviousRecordingDay.Time.Format(time.DateOnly) != "2026-03-07" || change.PlanDay.Time.Format(time.DateOnly) != "2026-03-08" || !change.Before.ActivityID.Valid) {
				t.Fatalf("missing old link or dates: %+v", change)
			}
			if tc.Name == "unchanged retry at current version" && refreshed {
				t.Fatal("unchanged association refreshed")
			}
			var stored map[string]any
			var rev, head int
			err = pool.QueryRow(ctx, `SELECT (SELECT to_jsonb(c)-'id'-'updated_at' FROM session_completions c WHERE session_uid=$1),
				data_revision,calendar_head_version FROM app_state WHERE id=1`, tc.UID).Scan(&stored, &rev, &head)
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(stored, tc.Stored) || rev != tc.Revision || head != tc.Head {
				t.Fatalf("Go row=%v revision=%d head=%d; Python row=%v revision=%d head=%d", stored, rev, head, tc.Stored, tc.Revision, tc.Head)
			}
		})
	}
	runConcurrentReports(t, pool, now)
}

func runConcurrentReports(t *testing.T, pool *pgxpool.Pool, now time.Time) {
	t.Helper()
	ctx := t.Context()
	uid := uuid.New()
	if _, err := SaveSelfReport(ctx, pool, uid, SelfReport{Status: Skipped}, now, nil); err == nil {
		t.Fatal("missing refresh accepted")
	}
	var initial int
	if err := pool.QueryRow(ctx, "SELECT data_revision FROM app_state WHERE id=1").Scan(&initial); err != nil {
		t.Fatal(err)
	}
	start := make(chan struct{})
	results := make(chan error, 2)
	for range 2 {
		go func() {
			<-start
			_, err := SaveSelfReport(ctx, pool, uid, SelfReport{Status: Skipped}, now, func(context.Context, pgx.Tx, CompletionChange) error { return nil })
			results <- err
		}()
	}
	close(start)
	var successes, conflicts int
	for range 2 {
		err := <-results
		var p *Problem
		switch {
		case err == nil:
			successes++
		case errors.As(err, &p) && p.Code == "version_conflict":
			conflicts++
		default:
			t.Fatal(err)
		}
	}
	var version, revision int
	if err := pool.QueryRow(ctx, "SELECT version,data_revision FROM session_completions CROSS JOIN app_state WHERE session_uid=$1 AND app_state.id=1", uid).Scan(&version, &revision); err != nil {
		t.Fatal(err)
	}
	if successes != 1 || conflicts != 1 || version != 1 || revision != initial+1 {
		t.Fatalf("concurrent writes: successes=%d conflicts=%d row version=%d dataset revision change=%d", successes, conflicts, version, revision-initial)
	}
}
