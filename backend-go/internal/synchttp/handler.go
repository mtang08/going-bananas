// Package synchttp serves the Garmin queue and treadmill review API.
package synchttp

import (
	"context"
	"encoding/json"
	"errors"
	"iter"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/replay"
	"github.com/mtang08/going-bananas/backend-go/internal/garmincli"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

type Source interface {
	Pages(context.Context, time.Time, time.Time, int, int) iter.Seq2[garmin.Page, error]
	DownloadActivity(context.Context, string) ([]byte, error)
}
type Handler struct {
	Pool             *pgxpool.Pool
	Mode, PrivateDir string
	Now              func() time.Time
	OpenSource       func(context.Context) (Source, error)
	Refresh          replay.Refresh
	mu               sync.Mutex
	previews         []preview
}

func New(pool *pgxpool.Pool, mode, privateDir string) *Handler {
	h := &Handler{Pool: pool, Mode: mode, PrivateDir: privateDir, Now: time.Now}
	h.Refresh = garmincli.SourceRefresh(func() time.Time { return h.Now() }, refresh.Runs)
	h.OpenSource = func(ctx context.Context) (Source, error) {
		key := os.Getenv("GARMIN_KEY_FILE")
		if key == "" {
			key = filepath.Join(privateDir, "garmin-key")
		}
		return garmin.Open(ctx, garmin.Config{KeyFile: key, CacheFile: filepath.Join(privateDir, "garmin-token.json")})
	}
	return h
}
func (h *Handler) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /api/v1/sync/status", h.status)
	mux.HandleFunc("GET /api/v1/sync/jobs/{job_id}", h.job)
	mux.HandleFunc("POST /api/v1/sync", h.enqueue)
	mux.HandleFunc("GET /api/v1/sync/treadmill-review/{remote_id}", h.review)
	mux.HandleFunc("POST /api/v1/sync/treadmill-review/{remote_id}", h.confirm)
}

type field struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}
type problem struct {
	status    int
	code, msg string
	fields    []field
}

func (p problem) Error() string { return p.code }
func issue(status int, code, msg string) problem {
	return problem{status: status, code: code, msg: msg}
}
func invalid(fields []field) error {
	return problem{422, "validation_error", "Invalid request fields", fields}
}

var realOnly = issue(409, "real_mode_required", "Real mode required")

func send(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(data)
}
func rid(w http.ResponseWriter) string {
	id := w.Header().Get("X-Request-ID")
	if id == "" {
		id = uuid.NewString()
		w.Header().Set("X-Request-ID", id)
	}
	return id
}
func failure(w http.ResponseWriter, err error) {
	p := issue(500, "internal_error", "Internal server error")
	var supplied problem
	if errors.As(err, &supplied) {
		p = supplied
	}
	if p.fields == nil {
		p.fields = []field{}
	}
	send(w, p.status, map[string]any{"error": map[string]any{"code": p.code, "message": p.msg, "fields": p.fields, "retryable": p.status >= 500, "request_id": rid(w)}})
}

type action func(context.Context, pgx.Tx) (any, error)

func (h *Handler) respond(w http.ResponseWriter, r *http.Request, status int, write bool, fn action) bool {
	var data any
	var rev int32
	opts := pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly}
	if write {
		opts = pgx.TxOptions{AccessMode: pgx.ReadWrite}
	}
	err := pgx.BeginTxFunc(r.Context(), h.Pool, opts, func(tx pgx.Tx) error {
		var err error
		data, err = fn(r.Context(), tx)
		if err == nil {
			rev, err = db.New(tx).DataRevision(r.Context())
		}
		return err
	})
	if err != nil {
		failure(w, err)
		return false
	}
	rid(w)
	send(w, status, map[string]any{"data": data, "data_revision": rev, "mode": h.Mode, "schema_version": "v1"})
	return true
}
