package goals_test

import (
	"context"
	"errors"
	"os"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/mtang08/going-bananas/backend-go/internal/goals"
)

// Clone only the two migrated tables needed for the mutation into a disposable
// schema. Every write, including failure injection, is local to this test.
func goalFixture(t *testing.T) (*pgxpool.Pool, uuid.UUID) {
	t.Helper()
	dsn := os.Getenv("GOAL_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires GOAL_TEST_DATABASE_URL and a migrated synthetic database")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatal("invalid goal test database configuration")
	}
	if cfg.ConnConfig.Database != "garmin_test" || (cfg.ConnConfig.Host != "127.0.0.1" && cfg.ConnConfig.Host != "localhost") {
		t.Fatal("goal tests require a dedicated loopback garmin_test database")
	}
	ctx := t.Context()
	source, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(source.Close)
	var name string
	if err := source.QueryRow(ctx, "SELECT current_database()").Scan(&name); err != nil || name != "garmin_test" {
		t.Fatalf("verify synthetic database: %v", err)
	}
	schema := pgx.Identifier{"go_goals_" + uuid.NewString()}.Sanitize()
	if _, err := source.Exec(ctx, "CREATE SCHEMA "+schema); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if _, err := source.Exec(context.Background(), "DROP SCHEMA "+schema+" CASCADE"); err != nil {
			t.Errorf("remove disposable goal fixture: %v", err)
		}
	})
	for _, table := range []string{"goals", "app_state"} {
		if _, err := source.Exec(ctx, "CREATE TABLE "+schema+"."+table+" (LIKE "+table+" INCLUDING CONSTRAINTS INCLUDING INDEXES)"); err != nil {
			t.Fatal(err)
		}
	}
	child := cfg.Copy()
	child.AfterConnect = func(ctx context.Context, conn *pgx.Conn) error {
		_, err := conn.Exec(ctx, "SET search_path TO "+schema)
		return err
	}
	pool, err := pgxpool.NewWithConfig(ctx, child)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	id := uuid.New()
	if _, err := pool.Exec(ctx, "INSERT INTO goals(id,text,horizon,priority,status,version) VALUES($1,'First','season',1,'active',1)", id); err != nil {
		t.Fatal(err)
	}
	if _, err := pool.Exec(ctx, "INSERT INTO app_state(id,data_revision,calendar_head_version) VALUES(1,7,3)"); err != nil {
		t.Fatal(err)
	}
	return pool, id
}

func TestPatchGoalsPostgres(t *testing.T) {
	pool, id := goalFixture(t)
	store := goals.New(pool)
	ctx := t.Context()
	for _, tc := range []struct {
		id    uuid.UUID
		patch goals.Patch
		want  error
	}{
		{uuid.New(), goals.Patch{ExpectedVersion: 99, HasNull: true}, goals.ErrNotFound},
		{id, goals.Patch{ExpectedVersion: 99, HasNull: true}, goals.ErrVersionConflict},
		{id, goals.Patch{ExpectedVersion: 1, HasNull: true}, goals.ErrNullField},
	} {
		if _, err := store.Patch(ctx, tc.id, tc.patch); !errors.Is(err, tc.want) {
			t.Fatalf("got %v, want %v", err, tc.want)
		}
	}
	result, err := store.Patch(ctx, id, goals.Patch{ExpectedVersion: 1})
	if err != nil || result.Goal.Version != 2 || result.DataRevision != 8 {
		t.Fatalf("version-only edit: %+v, %v", result, err)
	}
	start := make(chan struct{})
	results := make(chan error, 2)
	for _, title := range []string{"A", "B"} {
		go func() {
			<-start
			_, err := store.Patch(ctx, id, goals.Patch{ExpectedVersion: 2, Text: &title})
			results <- err
		}()
	}
	close(start)
	var successes, conflicts int
	for range 2 {
		err := <-results
		switch {
		case err == nil:
			successes++
		case errors.Is(err, goals.ErrVersionConflict):
			conflicts++
		default:
			t.Fatal(err)
		}
	}
	if successes != 1 || conflicts != 1 {
		t.Fatalf("got %d successful edits, %d conflicts", successes, conflicts)
	}
	// Fail the revision update after the goal UPDATE succeeds.
	if _, err := pool.Exec(ctx, "ALTER TABLE app_state ADD CHECK (data_revision <= 9)"); err != nil {
		t.Fatal(err)
	}
	title := "rolled back"
	result, err = store.Patch(ctx, id, goals.Patch{ExpectedVersion: 3, Text: &title})
	var pgErr *pgconn.PgError
	if !errors.As(err, &pgErr) || pgErr.Code != "23514" || result != (goals.Result{}) {
		t.Fatalf("expected an atomic failure from the revision check, got %+v, %v", result, err)
	}
	var actual string
	var version, revision, head int
	if err := pool.QueryRow(ctx, "SELECT text, version, data_revision, calendar_head_version FROM goals, app_state WHERE goals.id=$1 AND app_state.id=1", id).Scan(&actual, &version, &revision, &head); err != nil {
		t.Fatal(err)
	}
	if (actual != "A" && actual != "B") || version != 3 || revision != 9 || head != 3 {
		t.Fatalf("unexpected committed state: %q, version %d, revision %d, calendar %d", actual, version, revision, head)
	}
}

func TestPatchWaitsForPythonGlobalWriter(t *testing.T) {
	pool, id := goalFixture(t)
	ctx := t.Context()
	locked, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := locked.Rollback(context.Background()); err != nil {
			t.Errorf("release writer lock: %v", err)
		}
	})
	// app.db.global_write_lock acquires this exact database-wide key, even
	// for a writer editing an unrelated goal or another source table.
	if _, err := locked.Exec(ctx, "SELECT pg_advisory_xact_lock(71382413)"); err != nil {
		t.Fatal(err)
	}
	cfg := pool.Config()
	cfg.ConnConfig.RuntimeParams["lock_timeout"] = "150ms"
	cfg.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	writer, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(writer.Close)
	_, err = goals.New(writer).Patch(ctx, id, goals.Patch{ExpectedVersion: 1})
	var pgErr *pgconn.PgError
	if !errors.As(err, &pgErr) || pgErr.Code != "55P03" {
		t.Fatalf("expected timeout waiting for Python's advisory lock, got %v", err)
	}
}

func TestPatchEqualValuesAndFieldUpdates(t *testing.T) {
	pool, id := goalFixture(t)
	cfg := pool.Config()
	cfg.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	writer, err := pgxpool.NewWithConfig(t.Context(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(writer.Close)
	store := goals.New(writer)
	text, horizon, priority, status := "First", "season", 1, "active"
	patch := goals.Patch{ExpectedVersion: 1, Text: &text, Horizon: &horizon, Priority: &priority, Status: &status}
	equal, err := store.Patch(t.Context(), id, patch)
	want := goals.Goal{ID: id, Text: text, Horizon: horizon, Priority: priority, Status: status, Version: 2}
	if err != nil || equal.Goal != want || equal.DataRevision != 8 {
		t.Fatalf("equal-values update: %+v, %v", equal, err)
	}
	text, horizon, priority, status = "Revised", "long_term", 3, "paused"
	patch.ExpectedVersion = 2
	updated, err := store.Patch(t.Context(), id, patch)
	want = goals.Goal{ID: id, Text: text, Horizon: horizon, Priority: priority, Status: status, Version: 3}
	if err != nil || updated.Goal != want || updated.DataRevision != 9 {
		t.Fatalf("changed fields: %+v, %v", updated, err)
	}
}
