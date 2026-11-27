package loginstartup

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
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

// Exercise the HTTP response with a real-mode fixture and no installed agent.
// Both the home and launchctl are isolated from the host session.
func TestRealPreferenceOff(t *testing.T) {
	a := agent{root: t.TempDir(), home: t.TempDir(), domain: "gui/4321"}
	mkdir(t, filepath.Join(a.root, "frontend/dist"))
	writeFile(t, filepath.Join(a.root, "frontend/dist/index.html"), nil)
	writeFile(t, filepath.Join(a.root, ".env"), nil)
	var calls []string
	a.command = func(_ context.Context, action, target string) (string, bool, error) {
		calls = append(calls, action)
		switch action {
		case "print-disabled":
			if target == a.domain {
				return "", true, nil
			}
		case "print":
			if target == a.domain+"/"+label {
				return "", false, nil
			}
		}
		t.Fatalf("unexpected desktop command %s %s", action, target)
		return "", false, nil
	}
	h := Handler{Mode: "real", Run: a.run}
	mux := http.NewServeMux()
	h.Register(mux)
	r := httptest.NewRequest(http.MethodGet, Path, nil)
	r.RemoteAddr = "127.0.0.1:48123"
	response := httptest.NewRecorder()
	mux.ServeHTTP(response, r)
	var result struct {
		Mode string
		Data State
	}
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if response.Code != 200 || result.Mode != "real" || result.Data.Status != "disabled" || result.Data.Enabled == nil || *result.Data.Enabled || !reflect.DeepEqual(calls, []string{"print-disabled", "print"}) {
		t.Fatalf("response %d %+v, calls %v", response.Code, result, calls)
	}
	if _, err := os.Stat(filepath.Dir(a.path())); !os.IsNotExist(err) {
		t.Fatalf("preference read created launch directory: %v", err)
	}
}
