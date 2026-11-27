package demoseed

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Run handles the seed-demo subcommand for the configured synthetic workspace.
func Run(ctx context.Context, args []string, out io.Writer) error {
	if len(args) != 0 {
		return errors.New("usage: seed-demo")
	}
	if os.Getenv("APP_MODE") != "demo" {
		return errors.New("demo_mode_required")
	}
	url := strings.Replace(os.Getenv("DATABASE_URL"), "postgresql+psycopg://", "postgresql://", 1)
	if !strings.HasPrefix(url, "postgresql://") {
		return errors.New("demo_database_required")
	}
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil || !strings.HasSuffix(cfg.ConnConfig.Database, "_demo") {
		return errors.New("demo_database_required")
	}
	dir := os.Getenv("PRIVATE_DIR")
	if dir == "" {
		return errors.New("demo_private_dir_required")
	}
	physical, err := filepath.EvalSymlinks(dir)
	if err != nil {
		return errors.New("demo_private_dir_unavailable")
	}
	if filepath.Base(physical) != "demo" {
		return errors.New("expected demo private directory")
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return errors.New("demo_database_unavailable")
	}
	defer pool.Close()
	counts, err := Seed(ctx, pool, physical, time.Now().UTC())
	if err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(counts)
}
