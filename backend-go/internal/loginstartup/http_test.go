package loginstartup

import (
	"context"
	"encoding/json"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"

	"github.com/mtang08/going-bananas/backend-go/internal/httpapi"
)

func TestPythonDashboardHTTP(t *testing.T) {
	var cases []struct {
		Method, Body, Guard, Peer string
		Headers                   map[string]string
		Status                    int
		Wire                      map[string]any
	}
	readReference(t, "http.json", &cases)
	for _, c := range cases {
		calls := 0
		h := Handler{Mode: "test", Run: func(ctx context.Context, want *bool) State {
			calls++
			if c.Guard == "unavailable" || c.Guard == "other_checkout" {
				return problem(c.Guard, "Fixture error")
			}
			on := want != nil && *want
			status := "disabled"
			if on {
				status = "enabled"
			}
			return State{Status: status, Enabled: &on}
		}}
		mux := httpapi.New(nil, nil, nil, "test", "8000", "5173", h.Register)
		r := httptest.NewRequest(c.Method, "http://localhost:8000"+Path, strings.NewReader(c.Body))
		r.RemoteAddr = c.Peer + ":12345"
		for k, v := range c.Headers {
			r.Header.Set(k, v)
		}
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, r)
		var got map[string]any
		if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
			t.Fatal(err)
		}
		if e, ok := got["error"].(map[string]any); ok {
			if e["request_id"] == "" {
				t.Fatal("missing request ID")
			}
			delete(e, "request_id")
		}
		if w.Code != c.Status || !reflect.DeepEqual(got, c.Wire) {
			t.Fatalf("%s %s %s: got %d %+v, want %d %+v", c.Method, c.Body, c.Guard, w.Code, got, c.Status, c.Wire)
		}
		if c.Status >= 400 && c.Status != 409 && c.Status != 503 && calls != 0 {
			t.Fatal("rejected request touched launcher")
		}
	}
}
