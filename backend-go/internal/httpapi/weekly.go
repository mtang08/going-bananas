package httpapi

import (
	"context"
	"encoding/json"
	"github.com/mtang08/going-bananas/backend-go/internal/httpinput"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/weeklydigest"
	"github.com/mtang08/going-bananas/backend-go/internal/weeklyprojection"
)

const (
	WeeklyProjectionPath = "/api/v1/calendar/weekly-projection"
	WeeklyDigestPath     = "/api/v1/calendar/weekly-digest"
)

type Weekly struct {
	Pool *pgxpool.Pool
	Mode api.AppMode
	Now  func() time.Time
}

func (h Weekly) Register(mux *http.ServeMux) {
	for _, path := range []string{WeeklyProjectionPath, WeeklyDigestPath} {
		mux.HandleFunc(path, h.serve)
		mux.HandleFunc(path+"/{$}", h.serve)
	}
}
func (h Weekly) serve(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	id := requestID(ctx)
	w.Header().Set("Content-Type", "application/json")
	path := strings.TrimSuffix(r.URL.Path, "/")
	if path != WeeklyProjectionPath && path != WeeklyDigestPath {
		fail(w, r, 404, "not_found", "API route not found")
		return
	}
	if r.URL.Path != path {
		u := *r.URL
		u.Path = path
		http.Redirect(w, r, u.String(), http.StatusTemporaryRedirect)
		return
	}
	if r.Method != http.MethodGet {
		fail(w, r, 405, "method_not_allowed", "Request failed")
		return
	}
	start := ""
	if values := r.URL.Query()["week_start"]; path == WeeklyDigestPath && len(values) > 0 {
		day, msg := httpinput.Date(values[len(values)-1])
		if msg != "" {
			w.WriteHeader(422)
			_ = json.NewEncoder(w).Encode(api.ErrorEnvelope{Error: api.ErrorDetail{Code: "validation_error", RequestId: id, Message: "Invalid request fields", Fields: []api.ValidationField{{Field: "query.week_start", Message: msg}}}})
			return
		}
		date, _ := time.Parse(time.DateOnly, day)
		if date.Weekday() != time.Monday {
			fail(w, r, 422, "invalid_week_start", "Week start must be a Monday")
			return
		}
		start = date.Format(time.DateOnly)
	}
	var data any
	var revision int
	err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
		now := time.Now()
		if h.Now != nil {
			now = h.Now()
		}
		var err error
		if path == WeeklyProjectionPath {
			data, err = weeklyprojection.Load(ctx, tx, now)
		} else {
			data, err = loadHTTPWeek(ctx, tx, start, now)
		}
		if err != nil {
			return err
		}
		return tx.QueryRow(ctx, "SELECT COALESCE((SELECT data_revision FROM app_state WHERE id=1),0)").Scan(&revision)
	})
	if err != nil {
		internalError(w, r, err)
		return
	}
	_ = json.NewEncoder(w).Encode(map[string]any{"schema_version": "v1", "mode": h.Mode, "data_revision": revision, "data": data})
}

func loadHTTPWeek(ctx context.Context, tx pgx.Tx, start string, now time.Time) (map[string]any, error) {
	if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock_shared(71382413)"); err != nil {
		return nil, err
	}
	name, err := db.New(tx).CalendarTimezone(ctx)
	if err != nil {
		return nil, err
	}
	zone, err := time.LoadLocation(name)
	if err != nil {
		return nil, err
	}
	today := now.In(zone)
	if start == "" {
		start = today.AddDate(0, 0, -(int(today.Weekday())+6)%7).Format(time.DateOnly)
	}
	return weeklydigest.LoadWeek(ctx, tx, start, today.Format(time.DateOnly), now)
}
