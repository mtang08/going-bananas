package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/exceptions"
	"github.com/mtang08/going-bananas/backend-go/internal/httpinput"
)

type ExceptionRoutes struct {
	Pool *pgxpool.Pool
	Mode string
	Now  func() time.Time
}

func (h ExceptionRoutes) Register(m *http.ServeMux) {
	m.HandleFunc("GET /api/v1/exceptions", h.listExceptions)
	m.HandleFunc("POST /api/v1/exceptions/{finding_id}/dismiss", h.editException)
	m.HandleFunc("POST /api/v1/exception-patches/{patch_id}/resolve", h.editException)
}

func invalidExceptions(w http.ResponseWriter, r *http.Request, fields []api.ValidationField) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusUnprocessableEntity)
	_ = json.NewEncoder(w).Encode(api.ErrorEnvelope{Error: api.ErrorDetail{Code: "validation_error", Message: "Invalid request fields", RequestId: requestID(r.Context()), Fields: fields}})
}

type exceptionCommand func(context.Context, pgx.Tx, time.Time) (map[string]any, error)

func (h ExceptionRoutes) run(w http.ResponseWriter, r *http.Request, command exceptionCommand) {
	ctx := r.Context()
	now := time.Now
	if h.Now != nil {
		now = h.Now
	}
	var data map[string]any
	var revision int32
	err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		var err error
		data, err = command(ctx, tx, now().UTC())
		if err != nil {
			return err
		}
		return tx.QueryRow(ctx, "SELECT data_revision FROM app_state WHERE id=1").Scan(&revision)
	})
	if err != nil {
		var action *exceptions.ActionError
		if errors.As(err, &action) {
			fail(w, r, action.Status, action.Code, action.Message)
		} else {
			internalError(w, r, err)
		}
		return
	}
	formatExceptionDates(data)
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]any{"schema_version": "v1", "mode": h.Mode, "data_revision": revision, "data": data})
}

func (h ExceptionRoutes) listExceptions(w http.ResponseWriter, r *http.Request) {
	include := "active"
	if values := r.URL.Query()["include"]; len(values) > 0 {
		include = values[len(values)-1]
	}
	if include != "active" && include != "recent" {
		invalidExceptions(w, r, []api.ValidationField{{Field: "query.include", Message: "Input should be 'active' or 'recent'"}})
		return
	}
	h.run(w, r, func(ctx context.Context, tx pgx.Tx, now time.Time) (map[string]any, error) {
		if _, err := exceptions.Detect(ctx, tx, now); err != nil {
			return nil, err
		}
		return exceptions.View(ctx, tx, now, include)
	})
}

func (h ExceptionRoutes) editException(w http.ResponseWriter, r *http.Request) {
	key := "finding_id"
	if r.PathValue("patch_id") != "" {
		key = "patch_id"
	}
	raw := r.PathValue(key)
	id, idErr := uuid.Parse(raw)
	values, order, fields := httpinput.Object(r.Body)
	if idErr != nil && (len(fields) == 0 || fields[0].Message != "JSON decode error") {
		fields = append([]api.ValidationField{{Field: "path." + key, Message: httpinput.UUIDMessage(raw)}}, fields...)
	}
	var version int
	var note *string
	var target string
	add := func(key, msg string) {
		fields = append(fields, api.ValidationField{Field: "body." + key, Message: msg})
	}
	if values != nil {
		if v, ok := values["expected_version"]; ok {
			var msg string
			version, msg = positiveInteger(v)
			if msg != "" {
				add("expected_version", msg)
			}
		} else {
			add("expected_version", "Field required")
		}
		delete(values, "expected_version")
		if key == "patch_id" {
			if v, ok := values["status"]; ok {
				target, _ = v.(string)
				if target != "resolved" && target != "escalated" {
					add("status", "Input should be 'resolved' or 'escalated'")
				}
			} else {
				add("status", "Field required")
			}
			delete(values, "status")
		}
		if v := values["note"]; v != nil {
			s, ok := v.(string)
			switch {
			case !ok:
				add("note", "Input should be a valid string")
			case utf8.RuneCountInString(s) > 500:
				add("note", "String should have at most 500 characters")
			default:
				note = &s
			}
		}
		delete(values, "note")
		for _, k := range order {
			if _, ok := values[k]; ok {
				add(k, "Extra inputs are not permitted")
			}
		}
	}
	if len(fields) > 0 {
		invalidExceptions(w, r, fields)
		return
	}
	h.run(w, r, func(ctx context.Context, tx pgx.Tx, now time.Time) (map[string]any, error) {
		if key == "patch_id" {
			return exceptions.Resolve(ctx, tx, id, version, target, note, now)
		}
		return exceptions.Dismiss(ctx, tx, id, version, note, now)
	})
}

// FastAPI renders UTC datetimes in response models with Z. Evidence timestamps
// inside JSONB are already strings and retain their producer's formatting.
func formatExceptionDates(data map[string]any) {
	for _, key := range []string{"evidence_at", "first_seen_at", "last_seen_at", "created_at", "resolved_at"} {
		if s, ok := data[key].(string); ok && strings.HasSuffix(s, "+00:00") {
			data[key] = strings.TrimSuffix(s, "+00:00") + "Z"
		}
	}
	for _, key := range []string{"findings", "patches"} {
		if rows, ok := data[key].([]map[string]any); ok {
			for _, row := range rows {
				formatExceptionDates(row)
			}
		}
	}
}
