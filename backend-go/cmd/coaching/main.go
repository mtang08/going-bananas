// Command coaching exercises the pending-draft lifecycle against a synthetic database.
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
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drafts"
)

func run(ctx context.Context, args []string, w io.Writer) error {
	if len(args) == 0 {
		return errors.New("usage: coaching load|discard -id UUID [-revision N]")
	}
	flags := flag.NewFlagSet(args[0], flag.ContinueOnError)
	idArg := flags.String("id", "", "saved proposal ID")
	revision := flags.Int("revision", 0, "expected draft revision")
	if err := flags.Parse(args[1:]); err != nil {
		return err
	}
	id, err := uuid.Parse(*idArg)
	if err != nil {
		return errors.New("valid proposal -id required")
	}
	mode := os.Getenv("APP_MODE")
	if mode != "test" && mode != "demo" {
		return errors.New("APP_MODE must be test or demo")
	}
	dsn := strings.Replace(os.Getenv("DATABASE_URL"), "postgresql+psycopg://", "postgresql://", 1)
	if dsn == "" {
		return errors.New("DATABASE_URL is required")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil || !strings.HasSuffix(cfg.ConnConfig.Database, "_"+mode) {
		return errors.New("database must match the synthetic application mode")
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return errors.New("could not open synthetic database")
	}
	defer pool.Close()
	s := drafts.Store{Pool: pool}
	var result any
	switch args[0] {
	case "load":
		result, err = s.Load(ctx, id)
	case "discard":
		if *revision < 1 {
			return errors.New("positive -revision required")
		}
		result, err = s.Discard(ctx, id, *revision, time.Now().UTC())
	default:
		return errors.New("unknown coaching operation")
	}
	if err != nil {
		return err
	}
	return json.NewEncoder(w).Encode(result)
}

func main() {
	if err := run(context.Background(), os.Args[1:], os.Stdout); err != nil {
		var decision *drafts.Error
		if errors.As(err, &decision) {
			_ = json.NewEncoder(os.Stderr).Encode(decision)
		} else {
			fmt.Fprintln(os.Stderr, "Coaching command failed:", err)
		}
		os.Exit(1)
	}
}
