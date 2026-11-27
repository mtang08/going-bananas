// Package workercommand runs one requested Garmin sync or its continuous worker.
package workercommand

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/garmincli"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

func run(args []string) (int, error) {
	mode := os.Getenv("APP_MODE")
	if mode != "real" {
		return 1, errors.New("real_mode_required")
	}
	dsn := strings.Replace(os.Getenv("DATABASE_URL"), "postgresql+psycopg://", "postgresql://", 1)
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil || dsn == "" || !strings.HasSuffix(cfg.ConnConfig.Database, "_real") {
		return 1, errors.New("invalid_real_database")
	}
	dir := os.Getenv("PRIVATE_DIR")
	if dir == "" {
		dir = "private"
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return 1, errors.New("cannot_open_database")
	}
	defer pool.Close()
	return garmincli.Run(ctx, mode, garmincli.Config{Pool: pool, PrivateDir: dir, Refresh: garmincli.SourceRefresh(time.Now, refresh.Runs), ReportFIT: func(error) { fmt.Fprintln(os.Stderr, "FIT import failed") }}, args, os.Stdout)
}

func Main(args []string) int {
	code, err := run(args)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
	}
	return code
}
