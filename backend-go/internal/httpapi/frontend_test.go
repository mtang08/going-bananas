package httpapi

import (
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/mtang08/going-bananas/backend-go/api"
)

func TestFrontendOnLocalOrigin(t *testing.T) {
	root := t.TempDir()
	dist := filepath.Join(root, "dist")
	if err := os.MkdirAll(filepath.Join(dist, "phone"), 0700); err != nil {
		t.Fatal(err)
	}
	for p, data := range map[string]string{"private-test.txt": "outside", "dist/index.html": "app", "dist/phone/index.html": "phone", "dist/main.js": "asset"} {
		if err := os.WriteFile(filepath.Join(root, p), []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Symlink(filepath.Join(root, "private-test.txt"), filepath.Join(dist, "link.js")); err != nil {
		t.Fatal(err)
	}
	h := New(nil, nil, nil, api.Test, "8000", "5173", Frontend{Dist: dist}.Register)
	for _, c := range []struct {
		path     string
		status   int
		contains string
	}{
		{"/", 200, "app"}, {"/settings", 200, "app"}, {"/phone/", 200, "phone"}, {"/main.js", 200, "asset"},
		{"/missing.js", 404, "Not found"}, {"/link.js", 404, "Not found"}, {"/api/v1/missing", 404, "API route not found"},
	} {
		r := httptest.NewRequest("GET", c.path, nil)
		r.Host = "localhost:8000"
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != c.status || !strings.Contains(w.Body.String(), c.contains) || w.Header().Get("Cache-Control") != "no-store" {
			t.Error(c.path, w.Code, w.Body.String())
		}
	}
}
