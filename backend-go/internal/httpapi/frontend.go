package httpapi

import (
	"errors"
	"io/fs"
	"net/http"
	"os"
	"path"
	"strings"
)

// Frontend serves the Vite build and its client-side routes from the same
// loopback origin as the API. os.Root keeps asset reads inside the build.
type Frontend struct{ Dist string }

func (f Frontend) Register(mux *http.ServeMux) {
	mux.HandleFunc("GET /", f.serve)
}

func (f Frontend) serve(w http.ResponseWriter, r *http.Request) {
	root, err := os.OpenRoot(f.Dist)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			fail(w, r, 404, "frontend_not_built", "Frontend not built")
		} else {
			internalError(w, r, err)
		}
		return
	}
	defer func() { _ = root.Close() }()
	name := strings.TrimPrefix(r.URL.Path, "/")
	if name == "phone/" {
		name = "phone/index.html"
	}
	if name == "" {
		name = "index.html"
	}
	if fs.ValidPath(name) && serveFile(w, r, root, name) {
		return
	}
	if !strings.Contains(path.Base(name), ".") && serveFile(w, r, root, "index.html") {
		return
	}
	fail(w, r, 404, "not_found", "Not found")
}

func serveFile(w http.ResponseWriter, r *http.Request, root *os.Root, name string) bool {
	file, err := root.Open(name)
	if err != nil {
		return false
	}
	defer func() { _ = file.Close() }()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() {
		return false
	}
	http.ServeContent(w, r, name, info.ModTime(), file)
	return true
}
