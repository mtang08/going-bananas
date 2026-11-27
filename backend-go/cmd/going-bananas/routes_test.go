package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"regexp"
	"testing"

	"github.com/mtang08/going-bananas/backend-go/api"
)

// Always assemble the full mux. Go detects overlapping wildcard registrations
// at startup. The PostgreSQL comparison runner also supplies FastAPI's live
// operation inventory to catch missing method/path registrations.
func TestApplicationRoutes(t *testing.T) {
	mux := http.NewServeMux()
	api.HandlerFromMux(nil, mux)
	for _, register := range applicationRoutes(nil, api.Test, t.TempDir(), t.TempDir(), t.TempDir(), http.NotFoundHandler()) {
		register(mux)
	}
	if file := os.Getenv("REFERENCE_HTTP_ROUTES"); file != "" {
		b, err := os.ReadFile(file)
		if err != nil {
			t.Fatal(err)
		}
		var routes [][2]string
		if err := json.Unmarshal(b, &routes); err != nil {
			t.Fatal(err)
		}
		if len(routes) == 0 {
			t.Fatal("empty Python route inventory")
		}
		parameter := regexp.MustCompile(`\{[^}]+\}`)
		for _, route := range routes {
			path := parameter.ReplaceAllString(route[1], "00000000-0000-0000-0000-000000000001")
			_, pattern := mux.Handler(httptest.NewRequest(route[0], path, nil))
			if pattern == "" || pattern == "/" {
				t.Errorf("missing %s %s", route[0], route[1])
			}
		}
		t.Logf("checked %d reference HTTP operations", len(routes))
	}
}
