package evidence

import (
	"context"
	"os"
	"reflect"
	"regexp"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

const (
	testOp  = "proceed_or_modify_today"
	testDay = "2026-11-19"
)

var testNow = time.Date(2026, 11, 19, 16, 22, 0, 123456000, time.UTC)

func evidenceTx(t *testing.T) pgx.Tx {
	t.Helper()
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires the isolated PostgreSQL dashboard runner")
	}
	cfg, err := pgx.ParseConfig(dsn)
	if err != nil || cfg.Database != "garmin_test" || (cfg.Host != "localhost" && cfg.Host != "127.0.0.1") ||
		!regexp.MustCompile(`^go_parity_[a-f0-9]{32}$`).MatchString(cfg.RuntimeParams["search_path"]) {
		t.Fatal("requires an isolated local PostgreSQL fixture")
	}
	ctx := t.Context()
	conn, err := pgx.ConnectConfig(ctx, cfg)
	if err != nil {
		t.Fatal("connect to synthetic evidence database")
	}
	t.Cleanup(func() { _ = conn.Close(context.Background()) })
	var schema string
	if err := conn.QueryRow(ctx, "SELECT current_schema()").Scan(&schema); err != nil || schema != cfg.RuntimeParams["search_path"] {
		t.Fatal("missing migrated fixture schema")
	}
	tx, err := conn.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = tx.Rollback(context.Background()) })
	executeEvidenceSQL(t, tx, "SET LOCAL TIME ZONE 'Asia/Kathmandu'")
	return tx
}

func executeEvidenceSQL(t *testing.T, tx pgx.Tx, statement string, args ...any) {
	t.Helper()
	if _, err := tx.Exec(t.Context(), statement, args...); err != nil {
		t.Fatal(err)
	}
}

func readEvidence(t *testing.T, tx pgx.Tx, now time.Time) Inputs {
	t.Helper()
	got, err := CollectInputs(t.Context(), tx, testOp, testDay, now)
	if err != nil {
		t.Fatal(err)
	}
	return got
}

func TestDecisionEvidenceWindows(t *testing.T) {
	tx := evidenceTx(t)
	executeEvidenceSQL(t, tx, `
INSERT INTO profile_versions(id,version,effective_at,timezone,anchor_confirmed,strength_days_confirmed,scheduled_strength_days,facts,preferences,unknowns)
VALUES(md5('evidence-profile')::uuid,1,'2026-11-01T21:00Z','America/Denver',false,false,'[]',
    '{"clinician_restriction":"synthetic","large_id":9007199254740993,"threshold":1.0}','{}','["unknown"]')`)
	executeEvidenceSQL(t, tx, `
INSERT INTO checkins_v2(id,idempotency_key,kind,observed_at,illness,gait_change) VALUES
    (md5('evidence-cutoff')::uuid,'evidence-cutoff','exception',$1::timestamptz-interval '72 hours','present','yes'),
    (md5('evidence-outside')::uuid,'evidence-outside','exception',$1::timestamptz-interval '72 hours 1 microsecond','present','yes'),
    (md5('evidence-future')::uuid,'evidence-future','exception',$1::timestamptz+interval '1 microsecond','present','yes');
`, testNow)
	executeEvidenceSQL(t, tx, `
INSERT INTO symptom_reports(id,checkin_id,site,side,severity,timing) VALUES
    (md5('evidence-symptom-in')::uuid,md5('evidence-cutoff')::uuid,'synthetic','left',2,'during'),
    (md5('evidence-symptom-out')::uuid,md5('evidence-outside')::uuid,'synthetic','left',9,'during'),
    (md5('evidence-symptom-future')::uuid,md5('evidence-future')::uuid,'synthetic','left',8,'during');
`)
	executeEvidenceSQL(t, tx, `
INSERT INTO prompts(id,kind,session_uid,opens_at,closes_at,status) VALUES
    (md5('evidence-prompt-cutoff')::uuid,'delayed_symptom',md5('evidence-session-cutoff')::uuid,$1::timestamptz-interval '120 days',$1,'open'),
    (md5('evidence-prompt-before')::uuid,'delayed_symptom',md5('evidence-session-before')::uuid,$1::timestamptz-interval '120 days 1 microsecond',$1,'open'),
    (md5('evidence-prompt-future')::uuid,'delayed_symptom',md5('evidence-session-future')::uuid,$1::timestamptz+interval '1 microsecond',NULL,'open'),
    (md5('evidence-prompt-rpe')::uuid,'rpe',md5('evidence-session-rpe')::uuid,$1::timestamptz-interval '1 hour',NULL,'open')
`, testNow)
	got := readEvidence(t, tx, testNow)
	guard := row{"window_hours": 72, "gait_change_yes": true, "illness_present": true,
		"max_symptom_severity": float64(2), "clinical_restriction_active": true}
	if !reflect.DeepEqual(got.SafetyGuard, guard) {
		t.Errorf("safety guard got %v want %v", got.SafetyGuard, guard)
	}
	prompts := got.Sources["delayed_response_prompts"].([]row)
	if len(prompts) != 1 || prompts[0]["status"] != "expired" ||
		prompts[0]["closes_at"] != "2026-11-19T16:22:00.123456+00:00" {
		t.Errorf("delayed prompt window got %v", prompts)
	}
	// At the next microsecond the older report leaves the window and the
	// future report becomes eligible, without changing any database rows.
	later := readEvidence(t, tx, testNow.Add(time.Microsecond))
	if later.SafetyGuard["max_symptom_severity"] != float64(8) {
		t.Errorf("advanced safety guard got %v", later.SafetyGuard)
	}
	prompts = later.Sources["delayed_response_prompts"].([]row)
	if len(prompts) != 1 || prompts[0]["status"] != "open" {
		t.Errorf("advanced delayed prompt window got %v", prompts)
	}
}
