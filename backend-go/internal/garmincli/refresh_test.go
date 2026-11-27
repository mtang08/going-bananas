package garmincli

import (
	"os"
	"slices"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/replay"
)

// The fixture owns a temporary coverage table in its own transaction.
func TestCoverageDelta(t *testing.T) {
	dsn := os.Getenv("PROPOSAL_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires the integration schema")
	}
	cfg, err := pgx.ParseConfig(dsn)
	if err != nil || os.Getenv("APP_MODE") != "test" || cfg.Database != "garmin_test" || (cfg.Host != "127.0.0.1" && cfg.Host != "localhost") {
		t.Fatal("expected synthetic loopback test database")
	}
	ctx := t.Context()
	conn, err := pgx.ConnectConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = conn.Close(ctx) }()
	tx, err := conn.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	_, err = tx.Exec(ctx, `CREATE TEMP TABLE coverage_intervals(id uuid,dataset text,start_date date,end_date date,status text,fully_enumerated boolean)`)
	if err != nil {
		t.Fatal(err)
	}
	add := func(dataset, start, end, status string) uuid.UUID {
		id := uuid.New()
		if _, err := tx.Exec(ctx, "INSERT INTO pg_temp.coverage_intervals VALUES($1,$2,$3::text::date,$4::text::date,$5,true)", id, dataset, start, end, status); err != nil {
			t.Fatal(err)
		}
		return id
	}
	add("activities", "2026-11-09", "2026-11-11", "complete")
	first := add("activities", "2026-11-10", "2026-11-15", "complete")
	second := add("activities", "2026-11-14", "2026-11-15", "complete")
	partial := add("activities", "2026-11-08", "2026-11-09", "partial")
	sleep := add("sleep", "2026-11-08", "2026-11-09", "complete")
	for _, tc := range []struct {
		ids      []uuid.UUID
		complete bool
		want     []string
	}{
		{[]uuid.UUID{first, second}, true, []string{"coverage_date:2026-11-12", "coverage_date:2026-11-13", "coverage_date:2026-11-14", "coverage_date:2026-11-15"}},
		{[]uuid.UUID{second}, true, nil}, {[]uuid.UUID{partial, sleep}, false, nil},
	} {
		keys, complete, err := scopeKeys(ctx, tx, replay.RefreshScope{CoverageIDs: tc.ids})
		if err != nil || complete != tc.complete || !slices.Equal(keys, tc.want) {
			t.Fatalf("keys %v complete %v err %v", keys, complete, err)
		}
	}
}
