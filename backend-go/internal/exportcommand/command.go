// Package exportcommand previews a local Garmin account export and optionally imports it.
package exportcommand

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
	"github.com/mtang08/going-bananas/backend-go/internal/exportcli"
	"github.com/mtang08/going-bananas/backend-go/internal/garmincli"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

func run(args []string) error {
	mode := os.Getenv("APP_MODE")
	if mode != "real" {
		return errors.New("real_mode_required")
	}
	dsn := strings.Replace(os.Getenv("DATABASE_URL"), "postgresql+psycopg://", "postgresql://", 1)
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil || dsn == "" || !strings.HasSuffix(cfg.ConnConfig.Database, "_real") {
		return errors.New("invalid_real_database")
	}
	dir := os.Getenv("PRIVATE_DIR")
	if dir == "" {
		dir = "private"
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return errors.New("cannot_open_database")
	}
	defer pool.Close()
	return exportcli.Run(ctx, pool, dir, mode, args, os.Stdout, garmincli.SourceRefresh(time.Now, refresh.Runs))
}

func Main(args []string) int {
	if err := run(args); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}
