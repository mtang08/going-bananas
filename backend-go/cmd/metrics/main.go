// Command metrics recomputes registered metrics and previews or applies session assessments.
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
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/health"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

func assessSnapshot(ctx context.Context, tx pgx.Tx, uid uuid.UUID) (map[string]any, error) {
	var snapshot map[string]any
	err := tx.QueryRow(ctx, `SELECT jsonb_build_object('completion_status',c.status,'completion_version',c.version,'interval',
 (SELECT jsonb_build_object('status',m.status,'reason_codes',m.reason_codes,'quality_flags',m.quality_flags,'step_completion_ratio',m.value->'step_completion_ratio','config_hash',m.config_hash)
 FROM metric_results m WHERE m.metric_id='work_interval_execution' AND m.method_version='v2' AND m.subject_key=c.activity_id::text AND m.is_current),
 'planned_actual',(SELECT jsonb_build_object('status',m.status,'overall_status',m.value->'overall_status','components',m.value->'components','reason_codes',m.reason_codes,'config_hash',m.config_hash)
 FROM metric_results m WHERE m.metric_id='planned_actual_session' AND m.method_version='v2' AND m.is_current AND m.subject_key=c.session_uid::text))
 FROM session_completions c WHERE session_uid=$1`, uid).Scan(&snapshot)
	return snapshot, err
}

func assess(ctx context.Context, pool *pgxpool.Pool, uid uuid.UUID, apply bool, now time.Time) (any, error) {
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err = db.New(tx).LockGlobalWriter(ctx); err != nil {
		return nil, err
	}
	var activity *uuid.UUID
	err = tx.QueryRow(ctx, "SELECT activity_id FROM session_completions WHERE session_uid=$1", uid).Scan(&activity)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, errors.New("completion_not_found")
	}
	if err != nil {
		return nil, err
	}
	before, err := assessSnapshot(ctx, tx, uid)
	if err != nil {
		return nil, err
	}
	if err := refresh.AssessCompletion(now)(ctx, tx, uid); err != nil {
		return nil, err
	}
	after, err := assessSnapshot(ctx, tx, uid)
	if err != nil {
		return nil, err
	}
	if apply {
		if err := tx.Commit(ctx); err != nil {
			return nil, err
		}
	}
	return map[string]any{"activity_id": activity, "session_uid": uid, "applied": apply, "before": before, "after": after}, nil
}

func run(ctx context.Context, pool *pgxpool.Pool, args []string, now time.Time, out io.Writer) error {
	if len(args) == 0 {
		return errors.New("unknown_command")
	}
	flags := flag.NewFlagSet(args[0], flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	var execute func() (any, error)
	switch args[0] {
	case "metrics-assess-session":
		uid := flags.String("session-uid", "", "completion session UUID")
		apply := flags.Bool("apply", false, "persist assessment")
		execute = func() (any, error) {
			id, err := uuid.Parse(*uid)
			if err != nil {
				return nil, errors.New("invalid_session_uid")
			}
			return assess(ctx, pool, id, *apply, now)
		}
	case "metrics-refresh-today":
		execute = func() (any, error) { return health.Startup(ctx, pool, "", "", now) }
	case "metrics-recompute":
		metric := flags.String("metric", "all", "registered metric or all")
		since := flags.String("since", "", "first local date")
		until := flags.String("until", "", "last local date")
		execute = func() (any, error) {
			var result refresh.RecomputeSummary
			err := pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
				var err error
				result, err = refresh.Recompute(ctx, tx, *metric, *since, *until, now)
				return err
			})
			return result, err
		}
	default:
		return errors.New("unknown_command")
	}
	if err := flags.Parse(args[1:]); err != nil || flags.NArg() != 0 {
		return errors.New("invalid_arguments")
	}
	result, err := execute()
	if err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(result)
}

func main() {
	mode := os.Getenv("APP_MODE")
	dsn := strings.Replace(os.Getenv("DATABASE_URL"), "postgresql+psycopg://", "postgresql://", 1)
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil || dsn == "" || (mode != "test" && mode != "demo") || !strings.HasSuffix(cfg.ConnConfig.Database, "_"+mode) {
		fmt.Fprintln(os.Stderr, `{"error":"invalid_workspace"}`)
		os.Exit(2)
	}
	ctx := context.Background()
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err == nil {
		err = run(ctx, pool, os.Args[1:], time.Now().UTC(), os.Stdout)
		pool.Close()
	}
	if err != nil {
		code := "metrics_command_failed"
		switch err.Error() {
		case "invalid_metric", "invalid_date_window", "completion_not_found", "invalid_session_uid", "invalid_arguments", "unknown_command":
			code = err.Error()
		}
		_ = json.NewEncoder(os.Stderr).Encode(map[string]string{"error": code})
		os.Exit(2)
	}
}
