package httpapi

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"strings"

	"github.com/mtang08/going-bananas/backend-go/api"
)

type requestIDKey struct{}

func requestID(ctx context.Context) string { return ctx.Value(requestIDKey{}).(string) }

func fail(w http.ResponseWriter, r *http.Request, status int, code, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]any{
		"code":       code,
		"message":    message,
		"retryable":  status >= 500,
		"request_id": requestID(r.Context()),
		"fields":     []api.ValidationField{},
	}})
}

type localGuard struct {
	allowedHost map[string]bool
	apiHost     map[string]bool
	viteOrigin  map[string]bool
}

func newGuard(port, vitePort string) localGuard {
	g := localGuard{
		allowedHost: map[string]bool{"testserver": true},
		apiHost:     make(map[string]bool),
		viteOrigin:  make(map[string]bool),
	}
	for _, host := range []string{"localhost", "127.0.0.1"} {
		apiHost := host + ":" + port
		viteHost := host + ":" + vitePort
		g.allowedHost[host] = true
		g.allowedHost[apiHost] = true
		g.allowedHost[viteHost] = true
		g.apiHost[apiHost] = true
		g.viteOrigin["http://"+viteHost] = true
	}
	return g
}

func (g localGuard) allow(w http.ResponseWriter, r *http.Request) bool {
	if !g.allowedHost[r.Host] {
		fail(w, r, http.StatusForbidden, "invalid_host", "Local host required")
		return false
	}
	origin := r.Header.Get("Origin")
	fromVite := g.apiHost[r.Host] && g.viteOrigin[origin]
	if origin != "" && origin != "http://"+r.Host && !fromVite {
		fail(w, r, http.StatusForbidden, "invalid_origin", "Local origin required")
		return false
	}
	switch r.Method {
	case http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete:
		if r.Header.Get("X-Local-Request") != "1" {
			fail(w, r, http.StatusForbidden, "csrf_header_required", "X-Local-Request: 1 required")
			return false
		}
		if r.Method != http.MethodDelete && !strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
			fail(w, r, http.StatusUnsupportedMediaType, "json_required", "JSON body required")
			return false
		}
	}
	return true
}

func New(reader ProposalReader, mode api.AppMode, port, vitePort string) http.Handler {
	strict := api.NewStrictHandlerWithOptions(server{reader, mode}, nil, api.StrictHTTPServerOptions{
		ResponseErrorHandlerFunc: func(w http.ResponseWriter, r *http.Request, _ error) {
			// The reference middleware returns before adding success/validation headers on internal errors.
			w.Header().Del("Cache-Control")
			w.Header().Del("X-Request-ID")
			fail(w, r, http.StatusInternalServerError, "internal_error", "Internal server error")
		},
	})
	handler := api.Handler(strict)
	guard := newGuard(port, vitePort)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var id [8]byte
		_, _ = rand.Read(id[:])
		rid := hex.EncodeToString(id[:])
		r = r.WithContext(context.WithValue(r.Context(), requestIDKey{}, rid))
		if !guard.allow(w, r) {
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Request-ID", rid)
		const path = "/api/v1/coach/proposals"
		if r.Method != http.MethodGet && (r.URL.Path == path || r.URL.Path == path+"/") {
			fail(w, r, http.StatusMethodNotAllowed, "method_not_allowed", "Request failed")
			return
		}
		if r.URL.Path != path {
			fail(w, r, http.StatusNotFound, "not_found", "API route not found")
			return
		}
		// FastAPI binds the last occurrence of a scalar query parameter.
		query := r.URL.Query()
		if values := query["status"]; len(values) > 1 {
			query.Set("status", values[len(values)-1])
			urlCopy := *r.URL
			urlCopy.RawQuery = query.Encode()
			r.URL = &urlCopy
		}
		handler.ServeHTTP(w, r)
	})
}
