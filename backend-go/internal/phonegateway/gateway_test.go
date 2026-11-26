package phonegateway

import (
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strconv"
	"strings"
	"testing"
	"testing/fstest"
)

func TestDiscoverAndForward(t *testing.T) {
	status := []byte(`{"BackendState":"Running","Self":{"DNSName":"Synthetic.TS.NET.","UserID":42},"User":{"42":{"LoginName":"fixture"}}}`)
	access, err := Discover(status, true)
	if err != nil || access.Host != "synthetic.ts.net:8444" || access.Login != "fixture" || access.APIPort != 18000 || access.ListenPort != 8766 {
		t.Fatalf("demo access: %+v %v", access, err)
	}
	live, err := Discover(status, false)
	if err != nil || live.Host != "synthetic.ts.net:8443" || live.APIPort != 8000 || live.Mode != "real" || live.ListenPort != 8765 {
		t.Fatal(live, err)
	}
	if _, err := Discover([]byte(`{"BackendState":"Stopped"}`), false); err == nil {
		t.Fatal("accepted inactive Tailscale")
	}
	seen := make(chan http.Header, 1)
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen <- r.Header.Clone()
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte("{}"))
	}))
	defer up.Close()
	u, _ := url.Parse(up.URL)
	access.APIPort, _ = strconv.Atoi(u.Port())
	g := Gateway{access, fstest.MapFS{"index.html": {Data: []byte("phone"), Mode: os.FileMode(0444)}}}
	const path = "/api/v1/phone/checkins/12345678-1234-1234-1234-123456789abc"
	r := httptest.NewRequest("PUT", path, strings.NewReader("{}"))
	r.Host = access.Host
	r.Header.Set("Content-Length", "2")
	r.Header.Set("Tailscale-User-Login", "fixture")
	r.Header.Set("Origin", "https://"+access.Host)
	r.Header.Set("X-Local-Request", "1")
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("X-Phone-Mode", "real")
	r.Header.Set("Authorization", "Bearer fake")
	r.Header.Set("Cookie", "fake=1")
	r.Header.Set("X-Forwarded-For", "192.0.2.1")
	w := httptest.NewRecorder()
	g.ServeHTTP(w, r)
	if w.Code != 200 {
		t.Fatal(w.Code)
	}
	headers := <-seen
	for _, key := range []string{"Authorization", "Cookie", "Tailscale-User-Login", "X-Forwarded-For"} {
		if headers.Get(key) != "" {
			t.Fatal("forwarded " + key)
		}
	}
	if headers.Get("X-Phone-Mode") != "demo" || headers.Get("Origin") != up.URL {
		t.Fatal(headers)
	}
	r.Header.Add("Tailscale-User-Login", "fixture")
	w = httptest.NewRecorder()
	g.ServeHTTP(w, r)
	if w.Code != 403 {
		t.Fatal(w.Code)
	}
}
