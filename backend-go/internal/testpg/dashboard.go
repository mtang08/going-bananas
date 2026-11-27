// Package testpg opens disposable PostgreSQL fixtures for Go integration tests.
package testpg

import (
	"context"
	"errors"
	"os"
	"regexp"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var dashboardSchema = regexp.MustCompile(`^go_parity_[a-f0-9]{32}$`)

func DashboardConfig(t *testing.T) *pgxpool.Config {
	t.Helper()
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires the isolated PostgreSQL dashboard runner")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		t.Fatal("invalid dashboard test connection")
	}
	conn := cfg.ConnConfig
	if conn.Database != "garmin_test" || (conn.Host != "localhost" && conn.Host != "127.0.0.1") ||
		!dashboardSchema.MatchString(conn.RuntimeParams["search_path"]) {
		t.Fatal("requires an isolated loopback dashboard test schema")
	}
	cfg.AfterConnect = CheckDashboardSchema
	return cfg
}

func CheckDashboardSchema(ctx context.Context, conn *pgx.Conn) error {
	var schema string
	if err := conn.QueryRow(ctx, "SELECT current_schema()").Scan(&schema); err != nil ||
		schema != conn.Config().RuntimeParams["search_path"] {
		return errors.New("missing dashboard test schema")
	}
	return nil
}

// DashboardTx keeps all fixture writes inside a transaction that is rolled back.
func DashboardTx(t *testing.T) pgx.Tx {
	t.Helper()
	ctx := t.Context()
	cfg := DashboardConfig(t)
	conn, err := pgx.ConnectConfig(ctx, cfg.ConnConfig)
	if err != nil {
		t.Fatal("open dashboard test connection")
	}
	t.Cleanup(func() { _ = conn.Close(context.Background()) })
	if err := CheckDashboardSchema(ctx, conn); err != nil {
		t.Fatal(err)
	}
	tx, err := conn.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = tx.Rollback(context.Background()) })
	return tx
}
