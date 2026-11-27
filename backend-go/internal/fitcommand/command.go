// Package fitcommand backfills live FIT files and reprocesses retained archives.
package fitcommand

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/garmincli"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

func run(args []string) error {
	mode := os.Getenv("APP_MODE")
	if mode != "real" && mode != "demo" && mode != "test" {
		return errors.New("invalid_app_mode")
	}
	if len(args) > 0 && args[0] == "fit-backfill" && mode != "real" {
		return errors.New("real_mode_required")
	}
	dsn := strings.Replace(os.Getenv("DATABASE_URL"), "postgresql+psycopg://", "postgresql://", 1)
	db, err := pgxpool.ParseConfig(dsn)
	if err != nil || dsn == "" || !strings.HasSuffix(db.ConnConfig.Database, "_"+mode) {
		return errors.New("invalid_mode_database")
	}
	dir := os.Getenv("PRIVATE_DIR")
	if dir == "" {
		dir = "private"
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	pool, err := pgxpool.NewWithConfig(ctx, db)
	if err != nil {
		return errors.New("cannot_open_database")
	}
	defer pool.Close()
	return garmincli.RunFITCommand(ctx, mode, garmincli.Config{Pool: pool, PrivateDir: dir, Refresh: garmincli.SourceRefresh(time.Now, refresh.Runs)}, args, os.Stdout, nil)
}
func Main(args []string) int {
	if err := run(args); err != nil {
		_ = json.NewEncoder(os.Stderr).Encode(map[string]string{"error": err.Error()})
		return 2
	}
	return 0
}
