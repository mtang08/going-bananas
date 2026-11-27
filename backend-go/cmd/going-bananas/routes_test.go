package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/mtang08/going-bananas/backend-go/api"
)

func TestApplicationRoutes(t *testing.T) {
	mux := http.NewServeMux()
	api.HandlerFromMux(nil, mux)
	for _, register := range applicationRoutes(nil, api.Test, t.TempDir(), t.TempDir(), t.TempDir(), http.NotFoundHandler()) {
		register(mux)
	}
	fragments, err := filepath.Glob("../../api/*.openapi.json")
	if err != nil {
		t.Fatal(err)
	}
	parameter := regexp.MustCompile(`\{[^}]+\}`)
	for _, file := range append(fragments, "../../api/openapi.json") {
		var spec struct {
			Paths map[string]map[string]json.RawMessage
		}
		data, err := os.ReadFile(file)
		if err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(data, &spec); err != nil {
			t.Fatal(err)
		}
		if len(spec.Paths) == 0 {
			t.Fatalf("no paths in %s", file)
		}
		for path, item := range spec.Paths {
			for key := range item {
				switch key {
				case "get", "put", "post", "delete", "options", "head", "patch", "trace":
					method := strings.ToUpper(key)
					url := parameter.ReplaceAllString(path, "00000000-0000-0000-0000-000000000001")
					_, pattern := mux.Handler(httptest.NewRequest(method, url, nil))
					if pattern == "" || pattern == "/" {
						t.Errorf("%s: missing %s %s", file, method, path)
					}
				}
			}
		}
	}
}
