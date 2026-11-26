// Package phonegateway serves the phone shell and forwards its single observation route to the local API.
package phonegateway

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"mime"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"
)

type Access struct {
	Host, Login, Mode string
	APIPort           int
	ListenPort        int
}

func Discover(status []byte, demo bool) (Access, error) {
	var s struct {
		BackendState string
		Self         struct {
			DNSName string
			UserID  json.Number
		}
		User map[string]struct{ LoginName string }
	}
	if err := json.Unmarshal(status, &s); err != nil || s.BackendState != "Running" {
		return Access{}, errors.New("connect the Mac to Tailscale first")
	}
	host := strings.ToLower(strings.TrimRight(s.Self.DNSName, "."))
	login := s.User[string(s.Self.UserID)].LoginName
	if !strings.HasSuffix(host, ".ts.net") || login == "" {
		return Access{}, errors.New("a tailnet DNS name and owner login are required")
	}
	if demo {
		return Access{host + ":8444", login, "demo", 18000, 8766}, nil
	}
	return Access{host + ":8443", login, "real", 8000, 8765}, nil
}

var types = map[string]string{"index.html": "text/html; charset=utf-8", "phone.css": "text/css", "phone.js": "application/javascript", "sw.js": "application/javascript", "manifest.webmanifest": "application/manifest+json", "icon-192.png": "image/png", "icon-512.png": "image/png"}
var observation = regexp.MustCompile(`^/api/v1/phone/checkins/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

type Gateway struct {
	Access Access
	Assets fs.FS
}

// Never follow redirects or proxy settings when forwarding a phone write.
var localClient = &http.Client{Transport: &http.Transport{}, Timeout: 15 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}

func only(r *http.Request, name, want string) bool {
	v := r.Header.Values(name)
	return len(v) == 1 && v[0] == want
}

func (g Gateway) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	reply := func(status int, media string, body []byte) {
		w.Header().Set("Content-Type", media)
		w.Header().Set("Content-Length", strconv.Itoa(len(body)))
		w.Header().Set("Cache-Control", "no-store")
		if r.Method == "GET" || r.Method == "HEAD" {
			w.Header().Set("Cache-Control", "no-cache")
		}
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.WriteHeader(status)
		if r.Method != "HEAD" {
			_, _ = w.Write(body)
		}
	}
	plain := func(code int, msg string) { reply(code, "text/plain; charset=utf-8", []byte(msg)) }
	if r.Host != g.Access.Host {
		plain(403, "Phone hostname required.")
		return
	}
	if !only(r, "Tailscale-User-Login", g.Access.Login) {
		plain(403, "Connect with the owner's Tailscale account.")
		return
	}
	path := r.URL.EscapedPath()
	switch r.Method {
	case "HEAD", "GET":
		if path == "/" || path == "/phone" {
			w.Header().Set("Location", "/phone/")
			w.Header().Set("Cache-Control", "no-store")
			w.Header().Set("Content-Length", "0")
			w.WriteHeader(302)
			return
		}
		name, ok := strings.CutPrefix(path, "/phone/")
		if name == "" {
			name = "index.html"
		}
		media := types[name]
		if !ok || media == "" {
			plain(404, "Page not found. Open /phone/ for your morning check-in.")
			return
		}
		data, err := fs.ReadFile(g.Assets, name)
		if err != nil {
			plain(404, "")
			return
		}
		reply(200, media, data)
	case "PUT":
		if !observation.MatchString(r.RequestURI) {
			plain(404, "")
			return
		}
		if !only(r, "Origin", "https://"+g.Access.Host) || !only(r, "X-Local-Request", "1") {
			plain(403, "Same-origin phone request required.")
			return
		}
		media, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
		if err != nil || media != "application/json" {
			plain(415, "")
			return
		}
		if len(r.TransferEncoding) != 0 || r.ContentLength < 0 || r.Header.Get("Content-Length") == "" || len(r.Header.Get("Content-Length")) > 5 {
			plain(400, "")
			return
		}
		if r.ContentLength > 4096 {
			plain(413, "")
			return
		}
		data, err := io.ReadAll(io.LimitReader(r.Body, 4097))
		if err != nil || int64(len(data)) != r.ContentLength {
			plain(400, "")
			return
		}
		status, content, media, err := g.forward(r.Context(), path, data)
		if err != nil {
			plain(503, "The Mac API is unavailable.")
			return
		}
		reply(status, media, content)
	default:
		plain(501, "Unsupported method")
	}
}

func (g Gateway) forward(ctx context.Context, path string, data []byte) (int, []byte, string, error) {
	base := fmt.Sprintf("http://127.0.0.1:%d", g.Access.APIPort)
	req, err := http.NewRequestWithContext(ctx, "PUT", base+path, bytes.NewReader(data))
	if err != nil {
		return 0, nil, "", err
	}
	req.Header.Set("Origin", base)
	req.Header.Set("X-Local-Request", "1")
	req.Header.Set("X-Phone-Mode", g.Access.Mode)
	req.Header.Set("Content-Type", "application/json")
	resp, err := localClient.Do(req)
	if err != nil {
		return 0, nil, "", err
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(resp.Body)
	media := resp.Header.Get("Content-Type")
	if media == "" {
		media = "application/json"
	}
	return resp.StatusCode, body, media, err
}
