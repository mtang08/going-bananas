// Package planninghttp implements the local athlete's planning settings.
package planninghttp

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/jsonmodel"
	"github.com/mtang08/going-bananas/backend-go/internal/planning"
)

//go:embed model.json
var schema []byte
var models = jsonmodel.Load(schema, nil)

type Handler struct {
	Pool   *pgxpool.Pool
	KBRoot string
	Mode   string
	Now    func() time.Time
}
type result struct {
	data    any
	changed bool
}
type command struct {
	full, authored json.RawMessage
	id             *uuid.UUID
}
type operation func(context.Context, pgx.Tx, string, command) (result, error)
type route struct {
	pattern, model string
	status         int
	run            operation
}

func (h Handler) Register(m *http.ServeMux) {
	if h.Mode != "demo" && h.Mode != "test" {
		return
	}
	for _, r := range []route{
		{"GET /api/v1/blocks/active", "", 200, h.activeBlock}, {"GET /api/v1/blocks/benchmarks", "", 200, benchmarks}, {"GET /api/v1/blocks/{block_uid}/history", "", 200, blockHistory}, {"GET /api/v1/events/{event_id}/blocks", "", 200, eventBlocks}, {"PUT /api/v1/blocks/{block_uid}/benchmark-activity", "BenchmarkActivityInput", 200, setBenchmark},
		{"GET /api/v1/events", "", 200, listEvents}, {"POST /api/v1/events", "EventInput", 201, saveEvent}, {"PATCH /api/v1/events/{event_id}", "EventPatch", 200, saveEvent}, {"PUT /api/v1/events/order", "EventOrder", 200, orderEvents},
	} {
		m.HandleFunc(r.pattern, func(w http.ResponseWriter, req *http.Request) { h.serve(w, req, r) })
	}
}

type field struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}

func respond(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func problem(w http.ResponseWriter, status int, code, msg string, fields []field) {
	if fields == nil {
		fields = []field{}
	}
	respond(w, status, map[string]any{"error": map[string]any{"code": code, "message": msg, "fields": fields, "retryable": status >= 500, "request_id": w.Header().Get("X-Request-ID")}})
}
func parse(r *http.Request, model string) (command, []field) {
	c := command{}
	var issues []field
	keyName := "event_id"
	if r.PathValue("block_uid") != "" {
		keyName = "block_uid"
	}
	if key := r.PathValue(keyName); key != "" {
		id, err := uuid.Parse(key)
		if err != nil {
			issues = append(issues, field{"path." + keyName, "Input should be a valid UUID"})
		}
		c.id = &id
	}
	if model == "" {
		return c, issues
	}
	body, err := io.ReadAll(r.Body)
	if err != nil || len(body) == 0 {
		return c, append(issues, field{"body", "Field required"})
	}
	if !json.Valid(body) {
		return c, append(issues, field{"body.0", "JSON decode error"})
	}
	var problems []jsonmodel.Issue
	c.full, c.authored, problems = models.Parse(model, "body", body)
	for _, i := range problems {
		issues = append(issues, field{i.Path, i.Message})
	}
	if len(issues) == 0 && (model == "EventInput" || model == "EventPatch") {
		var obj map[string]any
		_ = json.Unmarshal(c.authored, &obj)
		if name, ok := obj["name"].(string); ok {
			name = strings.TrimSpace(name)
			if name == "" || utf8.RuneCountInString(name) > 100 {
				return c, []field{{"body.name", "Value error, Event name must be 1–100 characters"}}
			}
			obj["name"] = name
			c.authored, _ = json.Marshal(obj)
			_ = json.Unmarshal(c.full, &obj)
			obj["name"] = name
			c.full, _ = json.Marshal(obj)
		}
	}
	return c, issues
}
func (h Handler) serve(w http.ResponseWriter, r *http.Request, route route) {
	c, fields := parse(r, route.model)
	if len(fields) > 0 {
		problem(w, 422, "validation_error", "Invalid request fields", fields)
		return
	}
	ctx := r.Context()
	opts := pgx.TxOptions{AccessMode: pgx.ReadOnly, IsoLevel: pgx.RepeatableRead}
	write := r.Method != "GET"
	if write {
		opts = pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}
	}
	var out result
	var revision int32
	err := pgx.BeginTxFunc(ctx, h.Pool, opts, func(tx pgx.Tx) error {
		q := db.New(tx)
		if write {
			if err := q.LockGlobalWriter(ctx); err != nil {
				return err
			}
		}
		zone, err := q.CalendarTimezone(ctx)
		if err != nil {
			return err
		}
		loc, err := time.LoadLocation(zone)
		if err != nil {
			return err
		}
		now := time.Now()
		if h.Now != nil {
			now = h.Now()
		}
		out, err = route.run(ctx, tx, now.In(loc).Format(time.DateOnly), c)
		if err != nil {
			return err
		}
		if out.changed {
			revision, err = q.BumpDataRevision(ctx)
		} else {
			revision, err = q.DataRevision(ctx)
		}
		return err
	})
	if err != nil {
		var p *planning.Problem
		if errors.As(err, &p) {
			problem(w, p.Status, p.Code, p.Message, nil)
		} else {
			problem(w, 500, "internal_error", "Internal server error", nil)
		}
		return
	}
	respond(w, route.status, map[string]any{"schema_version": "v1", "mode": h.Mode, "data_revision": revision, "data": out.data})
}
func listEvents(ctx context.Context, tx pgx.Tx, today string, _ command) (result, error) {
	items, err := planning.Events(ctx, tx, today)
	return result{data: map[string]any{"items": items}}, err
}
func saveEvent(ctx context.Context, tx pgx.Tx, today string, c command) (result, error) {
	var input struct {
		Expected int `json:"expected_version"`
	}
	body := c.full
	if c.id != nil {
		body = c.authored
		if err := json.Unmarshal(body, &input); err != nil {
			return result{}, err
		}
	}
	row, err := planning.SaveEvent(ctx, tx, today, c.id, body, input.Expected)
	return result{row, true}, err
}
func orderEvents(ctx context.Context, tx pgx.Tx, today string, c command) (result, error) {
	var body struct {
		Items []planning.EventOrderItem `json:"items"`
	}
	if err := json.Unmarshal(c.full, &body); err != nil {
		return result{}, err
	}
	items, changed, err := planning.OrderEvents(ctx, tx, today, body.Items)
	return result{map[string]any{"items": items}, changed}, err
}

func (h Handler) activeBlock(ctx context.Context, tx pgx.Tx, today string, c command) (result, error) {
	d, e := planning.ActiveBlock(ctx, tx, today, h.KBRoot)
	return result{data: d}, e
}
func benchmarks(ctx context.Context, tx pgx.Tx, today string, c command) (result, error) {
	d, e := planning.BenchmarkHistory(ctx, tx)
	return result{data: map[string]any{"items": d}}, e
}
func blockHistory(ctx context.Context, tx pgx.Tx, today string, c command) (result, error) {
	d, e := planning.BlockHistory(ctx, tx, *c.id)
	return result{data: map[string]any{"items": d}}, e
}
func eventBlocks(ctx context.Context, tx pgx.Tx, today string, c command) (result, error) {
	d, e := planning.EventBlocks(ctx, tx, *c.id)
	return result{data: map[string]any{"items": d}}, e
}
func setBenchmark(ctx context.Context, tx pgx.Tx, today string, c command) (result, error) {
	var input struct {
		Activity *uuid.UUID `json:"activity_id"`
	}
	if err := json.Unmarshal(c.full, &input); err != nil {
		return result{}, err
	}
	d, e := planning.SetBenchmark(ctx, tx, *c.id, input.Activity, today)
	return result{d, true}, e
}
