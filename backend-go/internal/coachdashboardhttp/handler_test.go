package coachdashboardhttp

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"

	"github.com/mtang08/going-bananas/backend-go/internal/coachdashboard"
)

type stubGateway struct {
	review  coachdashboard.View
	command string
	input   input
	err     error
}

func (s *stubGateway) View(context.Context) (coachdashboard.View, error) { return s.review, nil }
func (s *stubGateway) Send(_ context.Context, g coachdashboard.Guard, id, text, intent string) error {
	s.command = "send"
	s.input = input{g, id, text, intent}
	return s.err
}
func (s *stubGateway) Cancel(_ context.Context, g coachdashboard.Guard) error {
	s.command = "cancel"
	s.input.guard = g
	return s.err
}
func (s *stubGateway) New(_ context.Context, g coachdashboard.Guard) error {
	s.command = "new"
	s.input.guard = g
	return s.err
}

type stubMetadata struct{}

func (stubMetadata) Read(_ context.Context, _ string) (Metadata, error) {
	return Metadata{DataRevision: 5}, nil
}

func request(method, suffix, body string) *http.Request {
	r := httptest.NewRequest(method, "http://localhost:8000"+path+suffix, strings.NewReader(body))
	r.RemoteAddr = "127.0.0.1:22310"
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("X-Local-Request", "1")
	r.Header.Set("Origin", "http://localhost:5173")
	return r
}

func TestDashboardViewFields(t *testing.T) {
	g := &stubGateway{review: coachdashboard.View{Status: "idle"}}
	h := New(g, stubMetadata{}, "test", "8000", "5173")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, request("GET", "", ""))
	if w.Code != 200 || w.Header().Get("Cache-Control") != "no-store" || len(w.Header().Get("X-Request-ID")) != 16 {
		t.Fatalf("response %d, %s", w.Code, w.Body)
	}
	var got any
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"schema_version": "v1", "mode": "test", "data_revision": float64(5), "data": map[string]any{"id": nil, "status": "idle", "messages": []any{}, "error": nil, "proposal_id": nil, "proposal_revision": nil}}
	if !reflect.DeepEqual(want, got) || g.command != "" {
		t.Fatalf("unexpected view %#v", got)
	}
}

func TestDashboardCommands(t *testing.T) {
	g := &stubGateway{}
	h := New(g, stubMetadata{}, "test", "8000", "5173")
	const id = "52c57d4b-6a4c-4210-9b9f-04fced237a31"
	for _, tc := range []struct {
		suffix, body, command string
		want                  input
	}{
		{"/messages", `{"thread_id":null,"client_message_id":"52C57D4B-6A4C-4210-9B9F-04FCED237A31","text":"  easy?  ","intent":"today_run"}`, "send", input{coachdashboard.Guard{Set: true}, id, "easy?", "today_run"}},
		{"/cancel", `{"thread_id":"` + id + `"}`, "cancel", input{guard: coachdashboard.Guard{Set: true, ID: id}}},
		{"/new", `{}`, "new", input{}},
	} {
		g.input = input{}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, request("POST", tc.suffix, tc.body))
		if w.Code != 200 || g.command != tc.command || g.input != tc.want {
			t.Fatalf("%s: %d %+v", tc.suffix, w.Code, g.input)
		}
	}
	g.err = &coachdashboard.Problem{Code: "chat_review_changed", Message: "Refresh the review."}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, request("POST", "/new", "{}"))
	if w.Code != 409 || !strings.Contains(w.Body.String(), "chat_review_changed") {
		t.Fatal(w.Code, w.Body)
	}
}

func TestDashboardAccess(t *testing.T) {
	for _, tc := range []struct {
		change func(r *http.Request)
		status int
		code   string
	}{
		{func(r *http.Request) { r.Host = "public.test" }, 403, "invalid_host"},
		{func(r *http.Request) { r.RemoteAddr = "192.0.2.4:1234"; r.Header.Set("X-Forwarded-For", "127.0.0.1") }, 403, "local_coach_required"},
		{func(r *http.Request) { r.Header.Set("Sec-Fetch-Site", "cross-site") }, 403, "local_coach_required"},
		{func(r *http.Request) { r.Header.Set("Origin", "https://example.test") }, 403, "invalid_origin"},
		{func(r *http.Request) { r.Header.Del("X-Local-Request") }, 403, "csrf_header_required"},
		{func(r *http.Request) { r.Header.Del("Content-Type") }, 415, "json_required"},
	} {
		g := &stubGateway{}
		req := request("POST", "/new", "{}")
		tc.change(req)
		w := httptest.NewRecorder()
		New(g, stubMetadata{}, "test", "8000", "5173").ServeHTTP(w, req)
		if w.Code != tc.status || !strings.Contains(w.Body.String(), tc.code) || g.command != "" {
			t.Fatal(w.Code, w.Body)
		}
	}
}

func TestDashboardRejectsInvalidInputs(t *testing.T) {
	for _, tc := range []struct{ suffix, body, field string }{
		{"/new", `{"allow_activation":true}`, "body.allow_activation"},
		{"/new", `[]`, "body"},
		{"/new", `null`, "body"},
		{"/messages", `{"text":" ","intent":"save"}`, "body.text"},
		{"/messages", `{"text":"test","client_message_id":"invalid"}`, "body.client_message_id"},
		{"/messages", `{"thread_id":5}`, "body.thread_id"},
		{"/cancel", `{} {}`, "body."},
	} {
		w := httptest.NewRecorder()
		g := &stubGateway{}
		New(g, stubMetadata{}, "test", "8000", "5173").ServeHTTP(w, request("POST", tc.suffix, tc.body))
		if w.Code != 422 || !strings.Contains(w.Body.String(), tc.field) || g.command != "" {
			t.Fatalf("%s: %d %s", tc.suffix, w.Code, w.Body)
		}
	}
}
