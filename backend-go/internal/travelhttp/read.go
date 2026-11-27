package travelhttp

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/mtang08/going-bananas/backend-go/internal/pydantic"
)

type syncAttempt struct {
	StartedAt  *string         `json:"started_at"`
	FinishedAt *string         `json:"finished_at"`
	Status     string          `json:"status"`
	ErrorCode  *string         `json:"error_code"`
	Counters   json.RawMessage `json:"counters"`
}

type statusView struct {
	Connected     bool           `json:"connected"`
	Window        map[string]int `json:"window"`
	LastSync      *syncAttempt   `json:"last_sync"`
	LastSuccessAt *string        `json:"last_success_at"`
}

func (h Handler) sendRead(w http.ResponseWriter, r *http.Request, fn func(pgx.Tx) (any, error)) {
	data, rev, err := h.read(r, fn)
	if err != nil {
		writeError(w, r, err)
		return
	}
	h.respond(w, r, http.StatusOK, data, rev)
}

// Status returns datetime values through Pydantic; the event views return preformatted strings.
func statusTime(raw *string) (*string, error) {
	if raw == nil {
		return nil, nil
	}
	// PostgreSQL JSON preserves the session-zone offset, as psycopg does.
	t, err := time.Parse(time.RFC3339Nano, *raw)
	if err != nil {
		return nil, err
	}
	v := *isoTime(&t, t.Location())
	if strings.HasSuffix(v, "+00:00") {
		v = strings.TrimSuffix(v, "+00:00") + "Z"
	}
	return &v, nil
}

func (h Handler) status(w http.ResponseWriter, r *http.Request) {
	h.sendRead(w, r, func(tx pgx.Tx) (any, error) {
		s := statusView{Connected: h.Provider != nil && h.Provider.Connected(), Window: map[string]int{"days_back": 30, "days_ahead": 180}}
		var a syncAttempt
		var started, finished, success *string
		err := tx.QueryRow(r.Context(), `SELECT to_jsonb(started_at)#>>'{}',to_jsonb(finished_at)#>>'{}',status,error_code,counters FROM import_batches WHERE source_kind='google_calendar' ORDER BY started_at DESC,id DESC LIMIT 1`).Scan(&started, &finished, &a.Status, &a.ErrorCode, &a.Counters)
		if err == nil {
			a.StartedAt, err = statusTime(started)
			if err != nil {
				return nil, err
			}
			a.FinishedAt, err = statusTime(finished)
			if err != nil {
				return nil, err
			}
			s.LastSync = &a
		} else if !errors.Is(err, pgx.ErrNoRows) {
			return nil, err
		}
		err = tx.QueryRow(r.Context(), `SELECT (SELECT to_jsonb(finished_at)#>>'{}' FROM import_batches WHERE source_kind='google_calendar' AND status='complete' ORDER BY finished_at DESC LIMIT 1)`).Scan(&success)
		if err != nil {
			return nil, err
		}
		s.LastSuccessAt, err = statusTime(success)
		return s, err
	})
}

func lastQuery(q url.Values, key string) (string, bool) {
	values := q[key]
	if len(values) == 0 {
		return "", false
	}
	return values[len(values)-1], true
}

var eventCategories = []string{"flight", "lodging", "ground_travel", "reservation", "out_of_office", "appointment", "work", "social", "other"}

func validCategory(s string) bool { return slices.Contains(eventCategories, s) }

func readValidation(fields ...Field) error {
	return &Problem{Status: 422, Code: "validation_error", Message: "Invalid request fields", Fields: fields}
}

func queryBool(q url.Values, key string) (bool, error) {
	raw, ok := lastQuery(q, key)
	if !ok {
		return false, nil
	}
	switch strings.ToLower(raw) {
	case "1", "true", "on", "t", "yes", "y":
		return true, nil
	case "0", "false", "off", "f", "no", "n":
		return false, nil
	}
	return false, readValidation(Field{Field: "query." + key, Message: "Input should be a valid boolean, unable to interpret input"})
}

type listRange struct{ start, end *time.Time }

func readRange(q url.Values) (listRange, error) {
	var dates listRange
	var invalidFields []Field
	for _, key := range []string{"start", "end"} {
		raw, ok := lastQuery(q, key)
		if !ok {
			continue
		}
		normalized, message := pydantic.Date(raw)
		if message != "" {
			invalidFields = append(invalidFields, Field{Field: "query." + key, Message: message})
			continue
		}
		day, _ := time.Parse(time.DateOnly, normalized)
		if key == "start" {
			dates.start = &day
		} else {
			dates.end = &day
		}
	}
	if len(invalidFields) > 0 {
		return dates, readValidation(invalidFields...)
	}
	return dates, nil
}

func (d listRange) bounds(today time.Time, ahead int) (time.Time, time.Time, error) {
	day := time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, time.UTC)
	start, end := day.AddDate(0, 0, -30), day.AddDate(0, 0, ahead)
	if d.start != nil {
		start = *d.start
	}
	if d.end != nil {
		end = *d.end
	}
	if start.After(end) || end.After(start.AddDate(0, 0, 400)) {
		return start, end, &Problem{Status: 422, Code: "invalid_date_range", Message: "Date range must be ordered and at most 400 days"}
	}
	return start, end, nil
}

func (h Handler) events(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	dates, rangeErr := readRange(q)
	removed, boolErr := queryBool(q, "include_removed")
	if rangeErr != nil || boolErr != nil {
		var fields []Field
		for _, err := range []error{rangeErr, boolErr} {
			var problem *Problem
			if errors.As(err, &problem) {
				fields = append(fields, problem.Fields...)
			}
		}
		writeError(w, r, readValidation(fields...))
		return
	}
	category, hasCategory := lastQuery(q, "category")
	h.sendRead(w, r, func(tx pgx.Tx) (any, error) {
		ctx := r.Context()
		home, err := athleteHome(ctx, tx)
		if err != nil {
			return nil, err
		}
		first, last, err := dates.bounds(h.now().In(home), 180)
		if err != nil {
			return nil, err
		}
		if hasCategory && category != "travel" && !validCategory(category) {
			return nil, readValidation()
		}
		items, err := listEvents(ctx, tx, home, first, last, removed, category)
		return map[string]any{"items": items}, err
	})
}

func listEvents(ctx context.Context, tx pgx.Tx, home *time.Location, first, last time.Time, removed bool, category string) ([]EventView, error) {
	start := time.Date(first.Year(), first.Month(), first.Day(), 0, 0, 0, 0, home)
	next := last.AddDate(0, 0, 1)
	end := time.Date(next.Year(), next.Month(), next.Day(), 0, 0, 0, 0, home)
	rows, err := tx.Query(ctx, eventSelect+` WHERE
		((NOT e.all_day AND e.start_at >= $1 AND e.start_at < $2) OR (e.all_day AND e.start_date BETWEEN $3 AND $4))
		AND ($5::boolean OR e.removed_at IS NULL)
		AND ($6::text='' OR e.category=$6 OR ($6='travel' AND e.category IN ('flight','lodging','ground_travel')))
		ORDER BY COALESCE(e.start_date,(e.start_at AT TIME ZONE $7)::date),COALESCE(e.start_at,e.start_date::timestamp AT TIME ZONE $7),e.id`,
		start, end, first, last, removed, category, home.String())
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []EventView{}
	for rows.Next() {
		e, err := scanEvent(rows, home)
		if err != nil {
			return nil, err
		}
		items = append(items, e)
	}
	return items, rows.Err()
}

func (h Handler) trips(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	dates, err := readRange(q)
	if err != nil {
		writeError(w, r, err)
		return
	}
	filter, _ := lastQuery(q, "status")
	h.sendRead(w, r, func(tx pgx.Tx) (any, error) {
		ctx := r.Context()
		home, err := athleteHome(ctx, tx)
		if err != nil {
			return nil, err
		}
		first, last, err := dates.bounds(h.now().In(home), 365)
		if err != nil {
			return nil, err
		}
		statuses := []string{"pending", "confirmed", "needs_review"}
		if filter != "" {
			statuses = strings.FieldsFunc(filter, func(r rune) bool { return r == ',' })
			if len(statuses) == 0 {
				return nil, readValidation()
			}
			for _, s := range statuses {
				if s != "pending" && s != "confirmed" && s != "needs_review" && s != "dismissed" {
					return nil, readValidation()
				}
			}
		}
		rows, err := tx.Query(ctx, tripSelect+` WHERE status=ANY($1::text[]) AND start_date<=$3 AND (end_date>=$2 OR (end_date IS NULL AND start_date >= $2::date-30)) ORDER BY start_date,id`, statuses, first, last)
		if err != nil {
			return nil, err
		}
		items, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (TripView, error) { return scanTrip(r) })
		if err != nil {
			return nil, err
		}
		if err := loadLegs(ctx, tx, items, home); err != nil {
			return nil, err
		}
		return map[string]any{"items": items}, nil
	})
}
