// Command strong-import previews a local Strong CSV. Pass -apply to import it.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/strong"
)

func run() error {
	apply := flag.Bool("apply", false, "apply imported workouts to the synthetic workspace")
	flag.Parse()
	if flag.NArg() != 1 {
		return errors.New("usage: strong-import [-apply] FILE.csv")
	}
	mode, root := os.Getenv("APP_MODE"), os.Getenv("PRIVATE_DIR")
	if (mode != "demo" && mode != "test") || root == "" {
		return errors.New("select a test or demo workspace with PRIVATE_DIR")
	}
	dsn := strings.Replace(os.Getenv("DATABASE_URL"), "postgresql+psycopg://", "postgresql://", 1)
	if dsn == "" {
		return errors.New("DATABASE_URL is required")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil || !strings.HasSuffix(cfg.ConnConfig.Database, "_"+mode) {
		return errors.New("database name must match synthetic mode")
	}
	ctx := context.Background()
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return errors.New("cannot open synthetic database")
	}
	defer pool.Close()
	result, err := strong.Import(ctx, pool, root, flag.Arg(0), *apply)
	if err != nil {
		var safe strong.Error
		if errors.As(err, &safe) {
			return safe
		}
		return errors.New("strong_import_failed")
	}
	return json.NewEncoder(os.Stdout).Encode(result)
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
