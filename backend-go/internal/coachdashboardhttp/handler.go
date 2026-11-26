// Package coachdashboardhttp adapts the dashboard conversation to the local HTTP API.
package coachdashboardhttp

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/coachdashboard"
)

const path = "/api/v1/coach/chat"

type Gateway interface {
	View(context.Context) (coachdashboard.View, error)
	Send(context.Context, coachdashboard.Guard, string, string, string) error
	New(context.Context, coachdashboard.Guard) error
	Cancel(context.Context, coachdashboard.Guard) error
}

var _ Gateway = (*coachdashboard.Gateway)(nil)

type Metadata struct {
	DataRevision     int64
	ProposalID       *string
	ProposalRevision *int
}

type MetadataReader interface {
	Read(context.Context, string) (Metadata, error)
}

type PostgresMetadata struct{ Pool *pgxpool.Pool }

func (m PostgresMetadata) Read(ctx context.Context, reviewProposal string) (Metadata, error) {
	var meta Metadata
	err := m.Pool.QueryRow(ctx, `SELECT COALESCE((SELECT data_revision FROM app_state WHERE id=1),0),
		p.id::text, p.revision FROM (VALUES(1)) AS anchor(n) LEFT JOIN LATERAL
		(SELECT id,revision FROM coach_proposals
		 WHERE status IN ('pending','stale','invalid') OR id=NULLIF($1,'')::uuid
		 ORDER BY (status IN ('pending','stale','invalid')) DESC, submitted_at DESC, id DESC LIMIT 1) p ON true`, reviewProposal).Scan(&meta.DataRevision, &meta.ProposalID, &meta.ProposalRevision)
	return meta, err
}

type handler struct {
	gateway              Gateway
	metadata             MetadataReader
	mode, port, vitePort string
}

func New(gateway Gateway, metadata MetadataReader, mode, port, vitePort string) http.Handler {
	return &handler{gateway, metadata, mode, port, vitePort}
}

type field struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}

func writeError(w http.ResponseWriter, id string, status int, code, message string, fields []field) {
	if fields == nil {
		fields = []field{}
	}
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]any{"code": code, "message": message, "retryable": status >= 500, "request_id": id, "fields": fields}})
}

func (h *handler) allowed(w http.ResponseWriter, r *http.Request, id string) bool {
	host := r.Host
	api := host == "127.0.0.1:"+h.port || host == "localhost:"+h.port
	vite := host == "127.0.0.1:"+h.vitePort || host == "localhost:"+h.vitePort
	localHost := api || vite || host == "127.0.0.1" || host == "localhost" || host == "testserver"
	if !localHost {
		writeError(w, id, 403, "invalid_host", "Local host required", nil)
		return false
	}
	peer, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		peer = r.RemoteAddr
	}
	localPeer := net.ParseIP(peer).IsLoopback() || h.mode == "test" && peer == "testclient"
	if !localPeer || r.Header.Get("Sec-Fetch-Site") == "cross-site" {
		writeError(w, id, 403, "local_coach_required", "Local coach request required", nil)
		return false
	}
	origin := r.Header.Get("Origin")
	fromVite := api && (origin == "http://127.0.0.1:"+h.vitePort || origin == "http://localhost:"+h.vitePort)
	if origin != "" && origin != "http://"+host && !fromVite {
		writeError(w, id, 403, "invalid_origin", "Local origin required", nil)
		return false
	}
	switch r.Method {
	case "POST", "PUT", "PATCH", "DELETE":
		if r.Header.Get("X-Local-Request") != "1" {
			writeError(w, id, 403, "csrf_header_required", "X-Local-Request: 1 required", nil)
			return false
		}
		if r.Method != "DELETE" && !strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
			writeError(w, id, 415, "json_required", "JSON body required", nil)
			return false
		}
	}
	return true
}

func (h *handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	var raw [8]byte
	rand.Read(raw[:])
	id := hex.EncodeToString(raw[:])
	w.Header().Set("Content-Type", "application/json")
	if !h.allowed(w, r, id) {
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Request-ID", id)
	var method string
	switch strings.TrimSuffix(r.URL.Path, "/") {
	case path:
		method = "GET"
	case path + "/messages", path + "/new", path + "/cancel":
		method = "POST"
	default:
		writeError(w, id, 404, "not_found", "API route not found", nil)
		return
	}
	if strings.HasSuffix(r.URL.Path, "/") {
		u := *r.URL
		u.Path = strings.TrimSuffix(u.Path, "/")
		http.Redirect(w, r, u.String(), http.StatusTemporaryRedirect)
		return
	}
	if r.Method != method {
		writeError(w, id, 405, "method_not_allowed", "Request failed", nil)
		return
	}
	ctx := r.Context()
	if method == "POST" {
		msg := r.URL.Path == path+"/messages"
		body, fields := parseInput(r.Body, msg)
		if len(fields) > 0 {
			writeError(w, id, 422, "validation_error", "Invalid request fields", fields)
			return
		}
		var err error
		switch r.URL.Path {
		case path + "/messages":
			err = h.gateway.Send(ctx, body.guard, body.clientID, body.text, body.intent)
		case path + "/new":
			err = h.gateway.New(ctx, body.guard)
		case path + "/cancel":
			err = h.gateway.Cancel(ctx, body.guard)
		}
		if err != nil {
			var problem *coachdashboard.Problem
			if errors.As(err, &problem) {
				writeError(w, id, 409, problem.Code, problem.Message, nil)
			} else {
				writeError(w, id, 500, "internal_error", "Internal server error", nil)
			}
			return
		}
	}
	review, err := h.gateway.View(ctx)
	if err != nil {
		writeError(w, id, 500, "internal_error", "Internal server error", nil)
		return
	}
	proposalID := ""
	if review.ProposalID != nil {
		proposalID = *review.ProposalID
	}
	meta, err := h.metadata.Read(ctx, proposalID)
	if err != nil {
		writeError(w, id, 500, "internal_error", "Internal server error", nil)
		return
	}
	if review.Messages == nil {
		review.Messages = []coachdashboard.Message{}
	}
	_ = json.NewEncoder(w).Encode(map[string]any{"schema_version": "v1", "mode": h.mode, "data_revision": meta.DataRevision,
		"data": map[string]any{"id": review.ID, "messages": review.Messages, "error": review.Error, "status": review.Status, "proposal_id": meta.ProposalID, "proposal_revision": meta.ProposalRevision}})
}
