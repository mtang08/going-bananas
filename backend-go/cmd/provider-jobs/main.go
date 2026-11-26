// Command provider-jobs exercises the Garmin job runner in a synthetic workspace.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/replay"
	"github.com/mtang08/going-bananas/backend-go/internal/providerjobs"
)

func run() error {
	dataset := flag.String("dataset", "", "dataset for enqueue")
	first := flag.String("start", "", "first requested date")
	last := flag.String("end", "", "last requested date")
	stamp := flag.String("now", "", "optional synthetic UTC clock")
	flag.Parse()
	if flag.NArg() != 1 || (flag.Arg(0) != "enqueue" && flag.Arg(0) != "run" && flag.Arg(0) != "worker") {
		return errors.New("supply enqueue, run, or worker")
	}
	dir := os.Getenv("PRIVATE_DIR")
	dsn := strings.Replace(os.Getenv("DATABASE_URL"), "postgresql+psycopg://", "postgresql://", 1)
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil || os.Getenv("APP_MODE") != "test" || dir == "" || cfg.ConnConfig.Database != "garmin_test" ||
		(cfg.ConnConfig.Host != "localhost" && cfg.ConnConfig.Host != "127.0.0.1") {
		return errors.New("expected local garmin_test and a synthetic PRIVATE_DIR")
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return errors.New("cannot open test database")
	}
	defer pool.Close()
	if flag.Arg(0) == "enqueue" {
		start, e1 := time.Parse(time.DateOnly, *first)
		end, e2 := time.Parse(time.DateOnly, *last)
		if e1 != nil || e2 != nil {
			return errors.New("invalid date")
		}
		var job providerjobs.Job
		err = pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
			job, err = providerjobs.Enqueue(ctx, tx, *dataset, start, end)
			return err
		})
		if err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]any{"id": job.ID, "status": job.Status})
	}
	u, err := url.Parse(os.Getenv("GARMIN_PERSONAL_API_BASE_URL"))
	if err != nil || u.Scheme != "http" || u.Hostname() != "127.0.0.1" || u.User != nil || u.Port() == "" {
		return errors.New("expected loopback synthetic Garmin HTTP service")
	}
	// This offline command always uses a fixture key, independent of caller credentials.
	if err := os.Setenv("GARMIN_API_KEY", "synthetic-provider-jobs"); err != nil {
		return err
	}
	source, err := garmin.Open(ctx, garmin.Config{CacheFile: filepath.Join(dir, "fixture-auth", "bearer.json")})
	if err != nil {
		return err
	}
	now := time.Now
	if *stamp != "" {
		instant, err := time.Parse(time.RFC3339, *stamp)
		if err != nil {
			return errors.New("invalid test clock")
		}
		now = func() time.Time { return instant }
	}
	importer := providerjobs.GarminImporter{PrivateDir: dir, AccountScope: "auto", Now: now}
	runner := providerjobs.Runner{Pool: pool, Source: source, Importer: importer, Now: now}
	runner.IngestFIT = func(ctx context.Context, records []garmin.Record) {
		if err := replay.RunFIT(ctx, pool, dir, source, records, now(), nil); err != nil {
			fmt.Fprintln(os.Stderr, "FIT import failed")
		}
	}
	if flag.Arg(0) == "worker" {
		err := runner.Work(ctx)
		if errors.Is(err, context.Canceled) {
			return nil
		}
		return err
	}
	status, err := runner.RunOne(ctx)
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]string{"status": status})
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
