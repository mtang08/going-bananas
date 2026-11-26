package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"strconv"
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
		date, msg := weeklyDate(values[len(values)-1])
		if msg != "" {
			w.WriteHeader(422)
			_ = json.NewEncoder(w).Encode(api.ErrorEnvelope{Error: api.ErrorDetail{Code: "validation_error", RequestId: id, Message: "Invalid request fields", Fields: []api.ValidationField{{Field: "query.week_start", Message: msg}}}})
			return
		}
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

func weeklyDate(value string) (time.Time, string) {
	const invalid = "Input should be a valid date or datetime, "
	if date, err := time.Parse(time.DateOnly, value); err == nil && date.Year() > 0 {
		return date, ""
	}
	var date time.Time
	if seconds, err := strconv.ParseInt(value, 10, 64); err == nil {
		if seconds < -20_000_000_000 || seconds > 20_000_000_000 {
			date = time.UnixMilli(seconds).UTC()
		} else {
			date = time.Unix(seconds, 0).UTC()
		}
	} else if len(value) >= 16 && strings.ContainsRune("Tt_ ", rune(value[10])) {
		dateText := value[:10] + "T" + value[11:]
		for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05", "2006-01-02T15:04", "2006-01-02T15:04Z07:00"} {
			if d, err := time.Parse(layout, dateText); err == nil {
				date = d
				break
			}
		}
	}
	if !date.IsZero() && date.Year() > 0 && date.Year() <= 9999 {
		if date.Hour() == 0 && date.Minute() == 0 && date.Second() == 0 && date.Nanosecond() == 0 {
			return date, ""
		}
		return time.Time{}, "Datetimes provided to dates should have zero time - e.g. be exact dates"
	}
	if len(value) < 10 {
		return time.Time{}, invalid + "input is too short"
	}
	if _, err := strconv.Atoi(value[:4]); err != nil {
		return time.Time{}, invalid + "invalid character in year"
	}
	return time.Time{}, invalid + "invalid date"
}
