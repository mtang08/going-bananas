package loginstartup

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"strconv"
	"strings"
)

const Path = "/api/v1/settings/login-startup"

type Handler struct {
	Mode string
	Run  func(context.Context, *bool) State
}
type field struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}

func (h Handler) Register(mux *http.ServeMux) { mux.HandleFunc(Path, h.serve) }
func (h Handler) serve(w http.ResponseWriter, r *http.Request) {
	id := w.Header().Get("X-Request-ID")
	if id == "" {
		var b [8]byte
		_, _ = rand.Read(b[:])
		id = hex.EncodeToString(b[:])
		w.Header().Set("X-Request-ID", id)
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	fail := func(status int, code, message string, fields []field) {
		if fields == nil {
			fields = []field{}
		}
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]any{"code": code, "message": message, "retryable": status >= 500, "request_id": id, "fields": fields}})
	}
	peer, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		peer = r.RemoteAddr
	}
	localPeer := net.ParseIP(peer).IsLoopback() || (h.Mode == "test" && peer == "testclient")
	if !localPeer || r.Header.Get("Sec-Fetch-Site") == "cross-site" {
		fail(403, "local_login_startup_required", "Local app request required", nil)
		return
	}
	var want *bool
	switch r.Method {
	case http.MethodGet:
	case http.MethodPut:
		if r.Header.Get("X-Local-Request") != "1" {
			fail(403, "csrf_header_required", "X-Local-Request: 1 required", nil)
			return
		}
		if !strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
			fail(415, "json_required", "JSON body required", nil)
			return
		}
		var fields []field
		want, fields = parseInput(r.Body)
		if len(fields) > 0 {
			fail(422, "validation_error", "Invalid request fields", fields)
			return
		}
	default:
		fail(405, "method_not_allowed", "Request failed", nil)
		return
	}
	s := h.Run(r.Context(), want)
	if want != nil && (s.Enabled == nil || *s.Enabled != *want) {
		status := 409
		if s.Status == "unavailable" {
			status = 503
		}
		msg := "macOS did not confirm the login startup setting. Try again."
		if s.Message != nil && *s.Message != "" {
			msg = *s.Message
		}
		fail(status, "login_startup_"+s.Status, msg, nil)
		return
	}
	_ = json.NewEncoder(w).Encode(map[string]any{"schema_version": "v1", "data_revision": 0, "mode": h.Mode, "data": s})
}

func parseInput(r io.Reader) (*bool, []field) {
	data, err := io.ReadAll(r)
	if err != nil {
		return nil, []field{{"body", "Could not read request body"}}
	}
	if len(data) == 0 {
		return nil, []field{{"body", "Field required"}}
	}
	var raw json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		offset := 0
		var syntax *json.SyntaxError
		if errors.As(err, &syntax) {
			offset = int(syntax.Offset) - 1
			if syntax.Error() == "unexpected end of JSON input" {
				offset = len(data)
			}
		}
		return nil, []field{{"body." + strconv.Itoa(offset), "JSON decode error"}}
	}
	if raw[0] != '{' {
		return nil, []field{{"body", "Input should be a valid dictionary or object to extract fields from"}}
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	_, _ = d.Token()
	var enabled json.RawMessage
	extras := []field{}
	seen := map[string]bool{}
	for d.More() {
		token, _ := d.Token()
		key := token.(string)
		var value json.RawMessage
		_ = d.Decode(&value)
		if key == "enabled" {
			enabled = value
		} else if !seen[key] {
			extras = append(extras, field{"body." + key, "Extra inputs are not permitted"})
			seen[key] = true
		}
	}
	switch string(enabled) {
	case "true", "false":
		b := string(enabled) == "true"
		return &b, extras
	case "":
		return nil, append([]field{{"body.enabled", "Field required"}}, extras...)
	default:
		return nil, append([]field{{"body.enabled", "Input should be a valid boolean"}}, extras...)
	}
}
