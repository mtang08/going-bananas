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
	"github.com/mtang08/going-bananas/backend-go/internal/metrics"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/recovery"
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
	mux.HandleFunc("GET /api/v1/metrics/recovery", h.respond(h.recovery))
	mux.HandleFunc("GET /api/v1/activities/{activity_id}/workout-history", h.respond(h.history))
	mux.HandleFunc("GET /api/v1/activities", h.respond(h.activities))
	mux.HandleFunc("GET /api/v1/activities/{activity_id}", h.respond(h.detail))
}

type query func(context.Context, pgx.Tx, *http.Request, time.Time, *time.Location) (any, error)

func (h Handler) respond(f query) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()
		now := time.Now()
		if h.Now != nil {
			now = h.Now()
		}
		var data any
		var revision int
		err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
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
		d, err := time.ParseInLocation(time.DateOnly, v, loc)
		if err != nil {
			fields = append(fields, object{"field": "query." + k, "message": "Input should be a valid date or datetime, input is too short"})
		}
		return d
	}
	end = parse(endKey, end)
	start := parse(startKey, end.AddDate(0, 0, 1-width))
	if len(fields) > 0 {
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
	cfg, err := metrics.Digest(recovery.Config)
	if err != nil {
		return nil, err
	}
	nights := []object{}
	for day := first; !day.After(last); day = day.AddDate(0, 0, 1) {
		d := day.Format(time.DateOnly)
		key := "night:" + d
		var value object
		var status string
		var quality *string
		var reasons, flags []string
		err := tx.QueryRow(ctx, `SELECT value,status,quality_status,reason_codes,quality_flags FROM metric_results WHERE metric_id=$1 AND method_version=$2 AND subject_key=$3 AND is_current AND config_hash=$4`, recovery.MetricID, recovery.MethodVersion, key, cfg).Scan(&value, &status, &quality, &reasons, &flags)
		if errors.Is(err, pgx.ErrNoRows) {
			res, err := recovery.Calculate(ctx, tx, key)
			if err != nil {
				return nil, err
			}
			value = res.Value.(map[string]any)
			status = res.Status
			if res.QualityStatus != "" {
				quality = &res.QualityStatus
			}
			reasons = res.ReasonCodes
			flags = res.QualityFlags
		} else if err != nil {
			return nil, err
		}
		if value == nil {
			value = object{}
		}
		value["local_date"] = d
		value["status"] = status
		value["quality_status"] = quality
		value["reason_codes"] = reasons
		value["quality_flags"] = flags
		nights = append(nights, value)
	}
	return object{"start": first.Format(time.DateOnly), "end": last.Format(time.DateOnly), "nights": nights}, nil
}
func limit(q url.Values, def, min, max int) (int, error) {
	raw, ok := parameter(q, "limit")
	if !ok {
		return def, nil
	}
	n, err := strconv.Atoi(raw)
	if err != nil {
		return 0, invalid("query.limit", "Input should be a valid integer, unable to parse string as an integer")
	}
	if n < min {
		return 0, invalid("query.limit", "Input should be greater than or equal to "+strconv.Itoa(min))
	}
	if n > max {
		return 0, invalid("query.limit", "Input should be less than or equal to "+strconv.Itoa(max))
	}
	return n, nil
}
