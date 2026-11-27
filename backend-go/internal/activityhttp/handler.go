// Package activityhttp serves read-only activity and recovery endpoints.
package activityhttp

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/httpinput"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/recovery"
	refresh "github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
	"net/http"
	"net/url"
	"strconv"
	"time"
)

type object = map[string]any
type Handler struct {
	Pool *pgxpool.Pool
	Mode string
	Now  func() time.Time
}
type problem struct {
	status    int
	code, msg string
	fields    []object
}

func (p *problem) Error() string { return p.msg }
func invalid(field, reason string) *problem {
	return &problem{422, "validation_error", "Invalid request fields", []object{{"field": field, "message": reason}}}
}
func (h Handler) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/metrics/workout-progression", h.respond(h.progression, true))
	mux.HandleFunc("GET /api/v1/metrics/long-runs", h.respond(h.longRuns, true))
	mux.HandleFunc("GET /api/v1/metrics/recovery", h.respond(h.recovery, true))
	mux.HandleFunc("GET /api/v1/activities/{activity_id}/execution", h.respond(h.execution, true))
	mux.HandleFunc("GET /api/v1/activities/{activity_id}/workout-history", h.respond(h.history, true))
	mux.HandleFunc("GET /api/v1/activities", h.respond(h.activities, false))
	mux.HandleFunc("GET /api/v1/activities/{activity_id}", h.respond(h.detail, false))
}

type query func(context.Context, pgx.Tx, *http.Request, time.Time, *time.Location) (any, error)

func (h Handler) respond(f query, waitForWriter bool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()
		now := time.Now()
		if h.Now != nil {
			now = h.Now()
		}
		var data any
		var revision int
		opts := pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly}
		// Metric reads wait for in-flight source writers before acquiring their read snapshot.
		if waitForWriter {
			opts.IsoLevel = pgx.ReadCommitted
		}
		err := pgx.BeginTxFunc(ctx, h.Pool, opts, func(tx pgx.Tx) error {
			if waitForWriter {
				if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock_shared(71382413)"); err != nil {
					return err
				}
			}
			zone, err := db.New(tx).CalendarTimezone(ctx)
			if err != nil {
				return err
			}
			loc, err := time.LoadLocation(zone)
			if err != nil {
				return err
			}
			data, err = f(ctx, tx, r, now, loc)
			if err != nil {
				return err
			}
			return tx.QueryRow(ctx, "SELECT data_revision FROM app_state WHERE id=1").Scan(&revision)
		})
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Cache-Control", "no-store")
		id := w.Header().Get("X-Request-ID")
		if id == "" {
			id = uuid.NewString()
			w.Header().Set("X-Request-ID", id)
		}
		if err != nil {
			var p *problem
			if !errors.As(err, &p) {
				p = &problem{500, "internal_error", "Internal server error", nil}
			}
			if p.fields == nil {
				p.fields = []object{}
			}
			w.WriteHeader(p.status)
			_ = json.NewEncoder(w).Encode(object{"error": object{"code": p.code, "message": p.msg, "fields": p.fields, "retryable": p.status >= 500, "request_id": id}})
			return
		}
		_ = json.NewEncoder(w).Encode(object{"data": data, "mode": h.Mode, "schema_version": "v1", "data_revision": revision})
	}
}
func parameter(q url.Values, k string) (string, bool) {
	v := q[k]
	if len(v) == 0 {
		return "", false
	}
	return v[len(v)-1], true
}
func days(r *http.Request, startKey, endKey string, now time.Time, loc *time.Location, width, limit int) (time.Time, time.Time, error) {
	q := r.URL.Query()
	today := now.In(loc)
	end := time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, loc)
	var fields []object
	parse := func(k string, defaultDay time.Time) time.Time {
		v, ok := parameter(q, k)
		if !ok {
			return defaultDay
		}
		parsed, msg := httpinput.Date(v)
		if msg != "" {
			fields = append(fields, object{"field": "query." + k, "message": msg})
			return defaultDay
		}
		d, _ := time.ParseInLocation(time.DateOnly, parsed, loc)
		return d
	}
	end = parse(endKey, end)
	start := parse(startKey, end.AddDate(0, 0, 1-width))
	if len(fields) > 0 {
		if len(fields) == 2 {
			fields[0], fields[1] = fields[1], fields[0]
		}
		return start, end, &problem{422, "validation_error", "Invalid request fields", fields}
	}
	if start.After(end) || !end.Before(start.AddDate(0, 0, limit)) {
		if startKey == "start" {
			return start, end, &problem{422, "invalid_date_window", "Invalid date window", nil}
		}
		return start, end, &problem{422, "invalid_date_range", "Date range must be ordered and at most 366 days", nil}
	}
	return start, end, nil
}
func (h Handler) recovery(ctx context.Context, tx pgx.Tx, r *http.Request, now time.Time, loc *time.Location) (any, error) {
	first, last, err := days(r, "start", "end", now, loc, 7, 92)
	if err != nil {
		return nil, err
	}
	nights := []object{}
	for day := first; !day.After(last); day = day.AddDate(0, 0, 1) {
		d := day.Format(time.DateOnly)
		row, err := refresh.ReadResult(ctx, tx, recovery.MetricID, "night:"+d, now)
		if err != nil {
			return nil, err
		}
		value, _ := row["value"].(map[string]any)
		if value == nil {
			value = object{}
		}
		value["local_date"] = d
		for _, key := range []string{"status", "quality_status", "reason_codes", "quality_flags"} {
			value[key] = row[key]
		}
		nights = append(nights, value)
	}
	return object{"start": first.Format(time.DateOnly), "end": last.Format(time.DateOnly), "nights": nights}, nil
}
func limit(q url.Values, def, min, max int) (int, error) {
	raw, ok := parameter(q, "limit")
	if !ok {
		return def, nil
	}
	n, msg := httpinput.Integer(raw, min)
	if msg != "" {
		return 0, invalid("query.limit", msg)
	}
	if n > max {
		return 0, invalid("query.limit", "Input should be less than or equal to "+strconv.Itoa(max))
	}
	return n, nil
}

func bindingErrors(first, second error) error {
	if second == nil {
		return first
	}
	if first == nil {
		return second
	}
	var a, b *problem
	if errors.As(first, &a) && errors.As(second, &b) && b.code == "validation_error" {
		if a.code == "validation_error" {
			a.fields = append(a.fields, b.fields...)
			return a
		}
		return b
	}
	return first
}
