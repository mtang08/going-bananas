// Package garmincli composes native Garmin sync and worker operations.
package garmincli

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/replay"
	"github.com/mtang08/going-bananas/backend-go/internal/providerjobs"
)

type Config struct {
	Pool       *pgxpool.Pool
	PrivateDir string
	Refresh    replay.Refresh
	Now        func() time.Time
	// ReportFIT receives post-commit file failures independently of the sync job.
	ReportFIT func(error)
}

type Worker struct {
	runner providerjobs.Runner
}

// Open constructs a live worker using the configured Garmin key and SDK token cache.
func Open(ctx context.Context, mode string, cfg Config) (*Worker, error) {
	if mode != "real" {
		return nil, errors.New("real_mode_required")
	}
	if err := cfg.validate(); err != nil {
		return nil, err
	}
	key := os.Getenv("GARMIN_KEY_FILE")
	if key == "" {
		key = filepath.Join(cfg.PrivateDir, "garmin-key")
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if os.Getenv("GARMIN_API_KEY") == "" && os.Getenv("GARMIN_PERSONAL_API_KEY") == "" {
		info, err := os.Stat(key)
		if err != nil || !info.Mode().IsRegular() {
			return nil, errors.New("garmin_credential_missing")
		}
	}
	return New(cfg, &clientSource{cfg: garmin.Config{KeyFile: key, CacheFile: filepath.Join(cfg.PrivateDir, "garmin-token.json")}})
}

type Source interface {
	providerjobs.Source
	replay.FITSource
}

func (cfg Config) validate() error {
	if cfg.Refresh == nil {
		return errors.New("garmin_refresh_required")
	}
	if cfg.Pool == nil || cfg.PrivateDir == "" || cfg.ReportFIT == nil {
		return errors.New("invalid_garmin_worker_config")
	}
	return nil
}

func New(cfg Config, source Source) (*Worker, error) {
	if err := cfg.validate(); err != nil {
		return nil, err
	}
	if source == nil {
		return nil, errors.New("missing_garmin_source")
	}
	if cfg.Now == nil {
		cfg.Now = time.Now
	}
	importer := providerjobs.GarminImporter{PrivateDir: cfg.PrivateDir, AccountScope: "auto", Now: cfg.Now}
	r := providerjobs.Runner{Pool: cfg.Pool, Now: cfg.Now, Importer: importer, Source: source}
	r.RefreshPage = func(ctx context.Context, tx pgx.Tx, job providerjobs.Job, page providerjobs.PageResult) error {
		if len(page.Activities) == 0 && len(page.AffectedDates) == 0 && len(page.CoverageIDs) == 0 {
			return nil
		}
		scope := replay.RefreshScope{Activities: page.Activities, CoverageIDs: page.CoverageIDs}
		if job.Dataset == "activities" {
			scope.AffectedDates = page.AffectedDates
		} else {
			scope.RecoveryDates = page.AffectedDates
		}
		return cfg.Refresh(ctx, tx, scope)
	}
	r.RefreshCoverage = func(ctx context.Context, tx pgx.Tx, _ providerjobs.Job, id uuid.UUID, _ string) error {
		return cfg.Refresh(ctx, tx, replay.RefreshScope{CoverageIDs: []uuid.UUID{id}})
	}
	r.IngestFIT = func(ctx context.Context, records []garmin.Record) {
		err := replay.RunFIT(ctx, cfg.Pool, cfg.PrivateDir, source, records, cfg.Now(), cfg.Refresh)
		if err != nil {
			cfg.ReportFIT(err)
		}
	}
	return &Worker{runner: r}, nil
}

func (w *Worker) Work(ctx context.Context) error             { return w.runner.Work(ctx) }
func (w *Worker) RunOne(ctx context.Context) (string, error) { return w.runner.RunOne(ctx) }

// Sync queues one requested window per dataset and runs one job per window.
// queued is called after the queue transaction commits.
func (w *Worker) Sync(ctx context.Context, start, end *time.Time, queued func([]uuid.UUID) error) ([]string, error) {
	var jobs []providerjobs.Job
	err := pgx.BeginTxFunc(ctx, w.runner.Pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		var last time.Time
		if end != nil {
			last = *end
		} else {
			name, err := db.New(tx).CalendarTimezone(ctx)
			if err != nil {
				return err
			}
			zone, err := time.LoadLocation(name)
			if err != nil {
				return err
			}
			last = w.runner.Now().In(zone)
		}
		var err error
		jobs, err = providerjobs.EnqueueRequested(ctx, tx, start, last)
		return err
	})
	if err != nil {
		return nil, err
	}
	if queued != nil {
		ids := make([]uuid.UUID, len(jobs))
		for i, job := range jobs {
			ids[i] = job.ID
		}
		if err := queued(ids); err != nil {
			return nil, err
		}
	}
	statuses := make([]string, 0, len(jobs))
	for range jobs {
		status, err := w.RunOne(ctx)
		if err != nil {
			return statuses, err
		}
		statuses = append(statuses, status)
	}
	return statuses, nil
}
