package coachdashboardhttp

import (
	"encoding/json"
	"net/http"

	"github.com/mtang08/going-bananas/backend-go/internal/coachdashboard"
)

func (h *handler) serveAuth(w http.ResponseWriter, r *http.Request, id string) {
	ctx := r.Context()
	var view coachdashboard.AuthView
	if r.Method == http.MethodGet {
		view = h.auth.Status(ctx)
	} else {
		body, fields := parseInput(r.Body, false)
		if body.guard.Set {
			fields = append(fields, field{"body.thread_id", "Extra inputs are not permitted"})
		}
		if len(fields) > 0 {
			writeError(w, id, 422, "validation_error", "Invalid request fields", fields)
			return
		}
		if r.URL.Path == path+"/auth/start" {
			view = h.auth.Start()
		} else {
			var err error
			view, err = h.auth.Cancel(ctx)
			if err != nil {
				writeError(w, id, 500, "internal_error", "Internal server error", nil)
				return
			}
		}
	}
	meta, err := h.metadata.Read(ctx, "")
	if err != nil {
		writeError(w, id, 500, "internal_error", "Internal server error", nil)
		return
	}
	_ = json.NewEncoder(w).Encode(map[string]any{"schema_version": "v1", "mode": h.mode, "data_revision": meta.DataRevision, "data": view})
}
