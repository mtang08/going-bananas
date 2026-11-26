// Package calendarhttp adapts manual calendar and anchor commands for the local
// synthetic API. All source writes and derived refreshes share one transaction.
package calendarhttp

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/anchors"
	"github.com/mtang08/going-bananas/backend-go/internal/calendar"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drafts"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/jsonmodel"
	"io"
	"net/http"
	"time"
)

//go:embed model.json
var schema []byte
var models = jsonmodel.Load(schema, nil)

type Handler struct {
	Pool    *pgxpool.Pool
	Mode    string
	Metrics calendar.PlanMetrics
	Now     func() time.Time
}

func (h Handler) Register(mux *http.ServeMux) {
	if h.Mode != "test" && h.Mode != "demo" {
		return
	}
	for path, name := range map[string]string{"POST /api/v1/calendar/bootstrap": "BootstrapInput", "POST /api/v1/calendar/edits": "EditsInput", "POST /api/v1/calendar/rollback": "RollbackInput", "POST /api/v1/anchors": "AnchorInput", "GET /api/v1/anchors": "list"} {
		mux.HandleFunc(path, func(w http.ResponseWriter, r *http.Request) { h.serve(w, r, name) })
	}
}

type field struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}

func send(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func fail(w http.ResponseWriter, status int, code, msg string, fields []field) {
	if fields == nil {
		fields = []field{}
	}
	send(w, status, map[string]any{"error": map[string]any{"code": code, "message": msg, "fields": fields, "retryable": status >= 500, "request_id": w.Header().Get("X-Request-ID")}})
}
func domainError(w http.ResponseWriter, err error) {
	var p *calendar.Problem
	var a *anchors.Problem
	var d *drafts.Error
	switch {
	case errors.As(err, &p):
		status := 422
		switch p.Code {
		case "calendar_exists", "calendar_head_moved":
			status = 409
		case "session_not_found", "calendar_version_not_found":
			status = 404
		}
		fail(w, status, p.Code, p.Message, nil)
	case errors.As(err, &a):
		fail(w, a.Status, a.Code, a.Message, nil)
	case errors.As(err, &d):
		fail(w, d.Status, d.Code, d.Message, nil)
	default:
		fail(w, 500, "internal_error", "Internal server error", nil)
	}
}

type command struct {
	Head      int            `json:"expected_head"`
	Target    int            `json:"to_version"`
	Reason    *string        `json:"reason"`
	AnchorDay string         `json:"anchor_date"`
	Start     string         `json:"start_date"`
	Pattern   map[string]int `json:"pattern"`
	Edits     []struct {
		Op     string
		UID    *uuid.UUID      `json:"session_uid"`
		Fields json.RawMessage `json:"fields"`
	} `json:"edits"`
}

func (h Handler) serve(w http.ResponseWriter, r *http.Request, name string) {
	ctx := r.Context()
	now := time.Now().UTC()
	if h.Now != nil {
		now = h.Now()
	}
	var full json.RawMessage
	if name != "list" {
		raw, err := io.ReadAll(r.Body)
		if err != nil || len(raw) == 0 {
			fail(w, 422, "validation_error", "Invalid request fields", []field{{"body", "Field required"}})
			return
		}
		if !json.Valid(raw) {
			fail(w, 422, "validation_error", "Invalid request fields", []field{{"body.0", "JSON decode error"}})
			return
		}
		var issues []jsonmodel.Issue
		full, _, issues = models.Parse(name, "body", raw)
		if len(issues) > 0 {
			var fields []field
			for _, i := range issues {
				fields = append(fields, field{i.Path, i.Message})
			}
			fail(w, 422, "validation_error", "Invalid request fields", fields)
			return
		}
	}
	mode := pgx.ReadWrite
	if name == "list" {
		mode = pgx.ReadOnly
	}
	var data any
	var rev int32
	err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{AccessMode: mode, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		q := db.New(tx)
		var err error
		if name == "list" {
			items, e := anchors.List(ctx, tx)
			if e != nil {
				return e
			}
			data = map[string]any{"items": items}
			rev, err = q.DataRevision(ctx)
			return err
		}
		if err := q.LockGlobalWriter(ctx); err != nil {
			return err
		}
		zone, err := q.CalendarTimezone(ctx)
		if err != nil {
			return err
		}
		loc, err := time.LoadLocation(zone)
		if err != nil {
			return err
		}
		today, err := time.Parse(time.DateOnly, now.In(loc).Format(time.DateOnly))
		if err != nil {
			return err
		}
		scope := calendar.PlanScope{}
		if name == "AnchorInput" {
			var input anchors.Input
			if err := json.Unmarshal(full, &input); err != nil {
				return err
			}
			row, err := anchors.Create(ctx, tx, input, zone)
			if err != nil {
				return err
			}
			data, err = row.Data()
			if err != nil {
				return err
			}
			scope.Since = input.ValidFrom
			scope.Dates = []string{input.ValidFrom}
		} else {
			var c command
			if err := json.Unmarshal(full, &c); err != nil {
				return err
			}
			result, kind, e := apply(ctx, tx, name, c, today)
			if e != nil {
				return e
			}
			data = map[string]any{"kind": kind, "version": result.Version, "stale_proposals": result.Stale, "preserved_session_uids": result.Preserved}
			scope.Dates = result.Dates
			scope.PlanUIDs = result.PlanUIDs
		}
		rev, err = q.BumpDataRevision(ctx)
		if err != nil {
			return err
		}
		return calendar.RefreshPlans(ctx, tx, scope, now, h.Metrics)
	})
	if err != nil {
		domainError(w, err)
		return
	}
	status := 200
	if name != "list" && name != "AnchorInput" {
		status = 201
	}
	send(w, status, map[string]any{"schema_version": "v1", "mode": h.Mode, "data_revision": rev, "data": data})
}
func apply(ctx context.Context, tx pgx.Tx, name string, c command, today time.Time) (calendar.AppliedEdits, string, error) {
	day := today.Format(time.DateOnly)
	if name == "BootstrapInput" {
		if len(c.Pattern) != 2 || c.Pattern["quality"] != 1 || c.Pattern["long"] != 1 {
			return calendar.AppliedEdits{}, "", &calendar.Problem{Code: "invalid_bootstrap_pattern", Message: "Bootstrap pattern must have one quality and one long run"}
		}
		anchor, e := time.Parse(time.DateOnly, c.AnchorDay)
		if e != nil {
			return calendar.AppliedEdits{}, "", e
		}
		start, e := time.Parse(time.DateOnly, c.Start)
		if e != nil {
			return calendar.AppliedEdits{}, "", e
		}
		result, err := calendar.Bootstrap(ctx, tx, anchor, start, today)
		return result, "bootstrap", err
	}
	check, err := drafts.CalendarPrescription(ctx, tx, day, name == "EditsInput")
	if err != nil {
		return calendar.AppliedEdits{}, "", err
	}
	if name == "RollbackInput" {
		result, e := calendar.Rollback(ctx, tx, c.Head, c.Target, c.Reason, day, check)
		return result, "rollback", e
	}
	b := calendar.EditBatch{Head: c.Head, Kind: "manual_edit", Actor: "user", Reason: c.Reason, Today: day}
	for _, e := range c.Edits {
		b.Edits = append(b.Edits, calendar.PlanEdit{Op: e.Op, SessionUID: e.UID, Fields: e.Fields})
	}
	result, e := calendar.ApplyEdits(ctx, tx, b, check)
	return result, "manual_edit", e
}
