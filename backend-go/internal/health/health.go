// Package health provides application health probes and the startup metrics pass.
package health

import (
	"context"
	"net/http"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/httpresponse"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
	"github.com/mtang08/going-bananas/backend-go/internal/prompts"
)

const expectedHead = "0028_coach_chat_reviews"

type Handler struct {
	Pool *pgxpool.Pool
	Mode string
}

func (h Handler) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/health/live", func(w http.ResponseWriter, _ *http.Request) {
		httpresponse.Success(w, h.Mode, 0, map[string]any{"status": "ok", "dashboard_coach": true})
	})
	mux.HandleFunc("GET /api/v1/health/ready", h.ready)
}

func (h Handler) ready(w http.ResponseWriter, r *http.Request) {
	var revision int
	var current bool
	err := h.Pool.QueryRow(r.Context(), `SELECT coalesce((SELECT data_revision FROM app_state WHERE id=1),0),
 (SELECT count(*)=1 AND bool_and(version_num=$1) FROM alembic_version)`, expectedHead).Scan(&revision, &current)
	if err != nil || !current {
		httpresponse.Envelope(w, http.StatusServiceUnavailable, h.Mode, 0, map[string]any{"status": "unavailable", "database": false})
		return
	}
	httpresponse.Success(w, h.Mode, revision, map[string]any{"status": "ok", "database": true})
}

type StartupResult struct {
	AsOf       string `json:"as_of"`
	NewResults int    `json:"new_results"`
	MS         int64  `json:"ms"`
}

// Startup refreshes derived rows in the selected database. Sync recovery belongs
// to the worker holding the session advisory lock. This pass uses no private files.
func Startup(ctx context.Context, pool *pgxpool.Pool, _, _ string, now time.Time) (StartupResult, error) {
	started := time.Now()
	var result StartupResult
	err := pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		q := db.New(tx)
		if err := q.LockGlobalWriter(ctx); err != nil {
			return err
		}
		name, err := q.CalendarTimezone(ctx)
		if err != nil {
			return err
		}
		zone, err := time.LoadLocation(name)
		if err != nil {
			return err
		}
		day := now.In(zone)
		result.AsOf = day.Format(time.DateOnly)
		const countSQL = "SELECT count(*) FROM metric_results"
		var before, after int
		if err = tx.QueryRow(ctx, countSQL).Scan(&before); err != nil {
			return err
		}
		if err = refresh.EnsureWindows(ctx, tx, day, now, nil); err != nil {
			return err
		}
		if _, err = prompts.Generate(ctx, tx, now); err != nil {
			return err
		}
		if err = tx.QueryRow(ctx, countSQL).Scan(&after); err != nil {
			return err
		}
		result.NewResults = after - before
		return nil
	})
	if err != nil {
		return StartupResult{}, err
	}
	result.MS = time.Since(started).Round(time.Millisecond).Milliseconds()
	return result, nil
}
