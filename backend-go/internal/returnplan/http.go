package returnplan

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Handler exposes GET /api/v1/running-interruption behind the core local HTTP guards.
type Handler struct {
	Pool *pgxpool.Pool
	Mode string
	Now  func() time.Time
}

func (h Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/api/v1/running-interruption" {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	id := uuid.NewString()
	w.Header().Set("X-Request-ID", id)
	fail := func(status int, code, msg string) {
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(object{"error": object{"code": code, "message": msg, "retryable": status >= 500, "request_id": id, "fields": []object{}}})
	}
	if r.Method != http.MethodGet {
		w.Header().Set("Allow", "GET")
		fail(http.StatusMethodNotAllowed, "method_not_allowed", "Request failed")
		return
	}
	now := time.Now()
	if h.Now != nil {
		now = h.Now()
	}
	var view object
	var revision int64
	ctx := r.Context()
	err := pgx.BeginTxFunc(ctx, h.Pool, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
		var asOf string
		err := tx.QueryRow(ctx, `SELECT (($1::timestamptz AT TIME ZONE coalesce((SELECT nullif(timezone,'') FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York'))::date)::text,
			coalesce((SELECT data_revision FROM app_state WHERE id=1),0)`, now).Scan(&asOf, &revision)
		if err != nil {
			return err
		}
		view, err = Read(ctx, tx, asOf)
		return err
	})
	if err != nil {
		fail(http.StatusInternalServerError, "internal_error", "Internal server error")
		return
	}
	_ = json.NewEncoder(w).Encode(object{"schema_version": "v1", "mode": h.Mode, "data_revision": revision, "data": view})
}
