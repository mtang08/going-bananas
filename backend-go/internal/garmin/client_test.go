package garmin

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

type fixture struct {
	config    Config
	base      string
	exchanges atomic.Int32
}

func token(n int32) string {
	return "test." + base64.RawURLEncoding.EncodeToString([]byte(fmt.Sprintf(`{"exp":4102444800,"n":%d}`, n))) + ".fixture"
}

func setup(t *testing.T, reply http.HandlerFunc) *fixture {
	t.Helper()
	f := &fixture{config: Config{CacheFile: filepath.Join(t.TempDir(), "cache", "bearer.json")}}
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == tokenPath {
			if r.Method != "POST" || r.Header.Get("Accept") != "*/*" || r.Header.Get("Authorization") != "ApiKey synthetic" {
				t.Errorf("incorrect key exchange")
			}
			_, _ = fmt.Fprint(w, token(f.exchanges.Add(1)))
			return
		}
		if r.Method != "GET" || r.Header.Get("Authorization") != "Bearer "+token(f.exchanges.Load()) {
			t.Error("incorrect bearer request")
		}
		reply(w, r)
	}))
	f.base = s.URL
	t.Cleanup(s.Close)
	t.Setenv("GARMIN_PERSONAL_API_BASE_URL", s.URL+"/")
	t.Setenv("GARMIN_API_KEY", "synthetic")
	t.Setenv("GARMIN_PERSONAL_API_KEY", "ignored")
	return f
}

func (f *fixture) open(t *testing.T) *Client {
	t.Helper()
	c, err := Open(t.Context(), f.config)
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func TestSharedCache(t *testing.T) {
	f := setup(t, func(http.ResponseWriter, *http.Request) { t.Error("unexpected data request") })
	dir := filepath.Dir(f.config.CacheFile)
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	fingerprint := fmt.Sprintf("%x", sha256.Sum256([]byte(f.base+"\x00synthetic")))
	// Python SDK fields, including its floating-point Unix timestamp.
	pythonCache := fmt.Sprintf(`{"fingerprint":%q,"expires_at":4102444800.0,"access_token":"python-token"}`, fingerprint)
	if err := os.WriteFile(f.config.CacheFile, []byte(pythonCache), 0644); err != nil {
		t.Fatal(err)
	}
	if c := f.open(t); c.token != "python-token" || f.exchanges.Load() != 0 {
		t.Fatal("cache was not reused")
	}
	for path, mode := range map[string]os.FileMode{dir: 0700, f.config.CacheFile: 0600} {
		info, err := os.Stat(path)
		if err != nil || info.Mode().Perm() != mode {
			t.Errorf("wrong permissions on %s", path)
		}
	}
	for n, s := range []string{
		strings.Replace(pythonCache, "4102444800.0", strconv.FormatInt(time.Now().Unix()+3600, 10), 1),
		strings.Replace(pythonCache, fingerprint, "another-environment", 1),
		"garbled",
	} {
		if err := os.WriteFile(f.config.CacheFile, []byte(s), 0600); err != nil {
			t.Fatal(err)
		}
		f.open(t)
		if f.exchanges.Load() != int32(n+1) {
			t.Error("expected a fresh exchange")
		}
		b, err := os.ReadFile(f.config.CacheFile)
		if err != nil {
			t.Fatal(err)
		}
		var cache map[string]any
		if err := json.Unmarshal(b, &cache); err != nil {
			t.Fatal(err)
		}
		if cache["fingerprint"] != fingerprint || cache["access_token"] != token(int32(n+1)) || cache["expires_at"] != float64(4102444800) {
			t.Error("incompatible token cache")
		}
	}
}

func TestKeyFile(t *testing.T) {
	f := setup(t, func(http.ResponseWriter, *http.Request) {})
	t.Setenv("GARMIN_API_KEY", "")
	t.Setenv("GARMIN_PERSONAL_API_KEY", "")
	f.config.KeyFile = filepath.Join(t.TempDir(), "key")
	if _, err := Open(t.Context(), f.config); err == nil || err.Error() != "garmin_key_file_missing" {
		t.Fatalf("missing key: %v", err)
	}
	if err := os.WriteFile(f.config.KeyFile, []byte("synthetic\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(f.config.KeyFile, 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := Open(t.Context(), f.config); err == nil || err.Error() != "garmin_key_file_permissions" {
		t.Fatalf("permissions: %v", err)
	}
	if err := os.Chmod(f.config.KeyFile, 0600); err != nil {
		t.Fatal(err)
	}
	f.open(t)
}

func TestUnauthorizedAndThrottledDownload(t *testing.T) {
	var calls atomic.Int32
	binary := "PK\x03\x04\x00\xff"
	f := setup(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/download-service/files/activity/7" || !strings.Contains(r.Header.Get("Accept"), "application/zip") {
			t.Error("wrong download request")
		}
		switch calls.Add(1) {
		case 1, 3, 4:
			http.Error(w, "secret body", http.StatusUnauthorized)
		case 2:
			_, _ = fmt.Fprint(w, binary)
		case 5:
			w.Header().Set("Retry-After", "37")
			http.Error(w, "secret body", http.StatusTooManyRequests)
		default:
			t.Error("unexpected retry")
		}
	})
	c := f.open(t)
	if b, err := c.DownloadActivity(t.Context(), "7"); err != nil || string(b) != binary {
		t.Fatalf("binary mismatch: %v", err)
	}
	for _, want := range []int{401, 429} {
		_, err := c.DownloadActivity(t.Context(), "7")
		var remote *RemoteError
		if !errors.As(err, &remote) || remote.StatusCode != want || strings.Contains(err.Error(), "secret") {
			t.Fatalf("remote error: %v", err)
		}
		if want == 429 && remote.RetryAfter != "37" {
			t.Errorf("Retry-After %q", remote.RetryAfter)
		}
	}
	if calls.Load() != 5 || f.exchanges.Load() != 3 {
		t.Error("wrong total attempts")
	}
	if _, err := c.DownloadActivity(t.Context(), "../7"); err == nil {
		t.Error("invalid download ID accepted")
	}
}

func TestCancelledRequest(t *testing.T) {
	f := setup(t, func(http.ResponseWriter, *http.Request) {})
	c := f.open(t)
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	if _, err := c.ActivityDetail(ctx, "10"); !errors.Is(err, context.Canceled) {
		t.Fatalf("cancellation: %v", err)
	}
}

func TestSharedCacheDirectoryUnchanged(t *testing.T) {
	f := setup(t, func(http.ResponseWriter, *http.Request) {})
	parent := filepath.Dir(f.config.CacheFile)
	if err := os.Mkdir(parent, 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(parent, 0755); err != nil {
		t.Fatal(err)
	}
	if _, err := Open(t.Context(), f.config); err == nil || err.Error() != "garmin_cache_directory_permissions" {
		t.Fatalf("shared parent: %v", err)
	}
	info, err := os.Stat(parent)
	if err != nil || info.Mode().Perm() != 0755 || f.exchanges.Load() != 0 {
		t.Fatal("modified shared cache parent or exchanged token")
	}
}

func TestRedirectAuthorization(t *testing.T) {
	makeRequest := func(target string) *http.Request {
		req, err := http.NewRequest(http.MethodGet, target, nil)
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("Authorization", "Bearer synthetic")
		return req
	}
	original := makeRequest("https://api.example")
	if err := redirect(makeRequest("http://api.example"), []*http.Request{original}); err == nil {
		t.Fatal("allowed HTTPS downgrade")
	}
	first := makeRequest("https://cdn.api.example")
	if err := redirect(first, []*http.Request{original}); err != nil || first.Header.Get("Authorization") != "" {
		t.Fatal("cross-origin credentials")
	}
	second := makeRequest("https://cdn.api.example/another")
	if err := redirect(second, []*http.Request{original, first}); err != nil || second.Header.Get("Authorization") != "" {
		t.Fatal("restored credentials on second hop")
	}
}
