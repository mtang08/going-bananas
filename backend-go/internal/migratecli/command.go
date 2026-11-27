// Package migratecli initializes a fresh database or upgrades its stamped schema.
package migratecli

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/workspacemigrate"
	"os"
	"os/signal"
	"strings"
	"syscall"
)

func run(ctx context.Context, args []string) error {
	flags := flag.NewFlagSet("workspace-migrate", flag.ContinueOnError)
	backend := flags.String("backend-dir", "backend", "directory containing the historical Alembic configuration")
	check := flags.Bool("check", false, "report the required action without migrating")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return errors.New("unexpected migration arguments")
	}
	mode := os.Getenv("APP_MODE")
	if mode != "test" && mode != "demo" && mode != "real" {
		return errors.New("invalid APP_MODE")
	}
	dsn := os.Getenv("DATABASE_URL")
	dsn = strings.Replace(dsn, "postgresql+psycopg://", "postgresql://", 1)
	if !strings.HasPrefix(dsn, "postgresql://") {
		return errors.New("expected PostgreSQL DATABASE_URL")
	}
	cfg, err := pgx.ParseConfig(dsn)
	if err != nil || !strings.HasSuffix(cfg.Database, "_"+mode) {
		return errors.New("DATABASE_URL does not match APP_MODE")
	}
	conn, err := pgx.ConnectConfig(ctx, cfg)
	if err != nil {
		return errors.New("migration_database_unavailable")
	}
	defer func() { _ = conn.Close(context.Background()) }()
	result, err := workspacemigrate.Run(ctx, conn, *backend, dsn, *check)
	if err != nil {
		switch err.Error() {
		case "nonempty_unstamped_schema", "unknown_migration_revision", "invalid_workspace_schema", "historical_alembic_upgrade_failed":
			return err
		}
		return errors.New("workspace_migration_failed")
	}
	return json.NewEncoder(os.Stdout).Encode(result)
}
func Main(args []string) int {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	if err := run(ctx, args); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}
