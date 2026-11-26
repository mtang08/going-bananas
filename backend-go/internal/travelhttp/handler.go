// Package travelhttp serves Google Calendar and trip endpoints behind the
// application's local HTTP guards. Register the routes on the guarded mux.
package travelhttp

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/travel"
)

type Provider = travel.Provider

type Handler struct {
	Pool       *pgxpool.Pool
	Mode       string
	PrivateDir string
	Provider   Provider
	Now        func() time.Time
}

func (h Handler) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/google-calendar/status", h.status)
	mux.HandleFunc("POST /api/v1/google-calendar/sync", h.sync)
	mux.HandleFunc("GET /api/v1/google-calendar/events", h.events)
	mux.HandleFunc("PATCH /api/v1/google-calendar/events/{event_id}", h.patchEvent)
	mux.HandleFunc("GET /api/v1/trips", h.trips)
	mux.HandleFunc("POST /api/v1/trips", h.createTrip)
	mux.HandleFunc("PATCH /api/v1/trips/{trip_id}", h.patchTrip)
}

func (h Handler) now() time.Time {
	if h.Now != nil {
		return h.Now().UTC()
	}
	return time.Now().UTC()
}

func (h Handler) read(r *http.Request, query func(pgx.Tx) (any, error)) (any, int32, error) {
	ctx := r.Context()
	var data any
	var revision int32
	err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
		var err error
		data, err = query(tx)
		if err != nil {
			return err
		}
		return tx.QueryRow(ctx, "SELECT data_revision FROM app_state WHERE id=1").Scan(&revision)
	})
	return data, revision, err
}

func requestID(w http.ResponseWriter) string {
	if id := w.Header().Get("X-Request-ID"); id != "" {
		return id
	}
	var buf [8]byte
	_, _ = rand.Read(buf[:])
	id := hex.EncodeToString(buf[:])
	w.Header().Set("X-Request-ID", id)
	return id
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func (h Handler) respond(w http.ResponseWriter, _ *http.Request, status int, data any, revision int32) {
	requestID(w)
	writeJSON(w, status, struct {
		SchemaVersion string `json:"schema_version"`
		Mode          string `json:"mode"`
		DataRevision  int32  `json:"data_revision"`
		Data          any    `json:"data"`
	}{"v1", h.Mode, revision, data})
}

type Field struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}

type Problem struct {
	Status        int
	Code, Message string
	Fields        []Field
}

func (p *Problem) Error() string { return p.Code }

func writeError(w http.ResponseWriter, _ *http.Request, err error) {
	p := &Problem{Status: 500, Code: "internal_error", Message: "Internal server error"}
	var supplied *Problem
	if errors.As(err, &supplied) {
		p = supplied
	}
	fields := p.Fields
	if fields == nil {
		fields = []Field{}
	}
	writeJSON(w, p.Status, map[string]any{"error": map[string]any{
		"code": p.Code, "message": p.Message, "retryable": p.Status >= 500, "request_id": requestID(w), "fields": fields,
	}})
}
func fail(w http.ResponseWriter, r *http.Request, status int, code, message string) {
	writeError(w, r, &Problem{Status: status, Code: code, Message: message})
}
func invalid(w http.ResponseWriter, r *http.Request, fields []Field) {
	writeError(w, r, &Problem{Status: 422, Code: "validation_error", Message: "Invalid request fields", Fields: fields})
}
func internal(w http.ResponseWriter, r *http.Request) { writeError(w, r, nil) }

func (h Handler) sync(w http.ResponseWriter, r *http.Request) {
	if h.Mode != "real" {
		fail(w, r, 409, "real_mode_required", "Real mode required")
		return
	}
	result, err := travel.Sync(r.Context(), h.Pool, h.PrivateDir, h.Provider, h.now())
	if err != nil {
		var source *travel.ProviderError
		if errors.As(err, &source) {
			fail(w, r, source.Status(), source.Code, source.Message())
			return
		}
		internal(w, r)
		return
	}
	h.respond(w, r, 200, result, result.DataRevision)
}
