// Command gcal-replay applies downloaded Calendar pages to a synthetic workspace.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/travel"
)

func run() error {
	input := flag.String("input", "", "synthetic JSON delivery")
	flag.Parse()
	if *input == "" || flag.NArg() != 0 {
		return errors.New("usage: gcal-replay -input manifest.json")
	}
	mode := os.Getenv("APP_MODE")
	if (mode != "demo" && mode != "test") || os.Getenv("PRIVATE_DIR") == "" {
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
	f, err := os.Open(*input)
	if err != nil {
		return errors.New("cannot open replay manifest")
	}
	defer func() { _ = f.Close() }()
	dec := json.NewDecoder(f)
	dec.DisallowUnknownFields()
	var d travel.Delivery
	if err := dec.Decode(&d); err != nil || !errors.Is(dec.Decode(new(any)), io.EOF) {
		return errors.New("invalid replay manifest")
	}
	ctx := context.Background()
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return errors.New("cannot open synthetic database")
	}
	defer pool.Close()
	result, err := travel.Apply(ctx, pool, d)
	if err != nil {
		if errors.Is(err, travel.ErrInvalidResponse) || errors.Is(err, travel.ErrMissingFetchTime) {
			return err
		}
		return errors.New("gcal_replay_failed")
	}
	return json.NewEncoder(os.Stdout).Encode(result)
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
