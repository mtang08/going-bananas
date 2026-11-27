package googlecalendar

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/travel"
)

func tokenFixture(t *testing.T, dir string, expiry string) []byte {
	t.Helper()
	raw, err := json.Marshal(map[string]any{"client_id": "fake-id", "client_secret": "fake-secret", "refresh_token": "old-refresh", "token": "old-token", "scopes": []string{readScope}, "expiry": expiry, "token_uri": "https://invalid.example/ignored"})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, tokenFile), raw, 0600); err != nil {
		t.Fatal(err)
	}
	return raw
}

func TestRefreshAndPage(t *testing.T) {
	dir := t.TempDir()
	tokenFixture(t, dir, "2000-01-01T00:00:00Z")
	now := time.Date(2026, 11, 2, 0, 0, 0, 0, time.UTC)
	posts, gets := 0, 0
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/token":
			posts++
			if r.Method != "POST" || r.FormValue("scope") != readScope || r.FormValue("refresh_token") != "old-refresh" || r.FormValue("client_secret") != "fake-secret" {
				t.Error("unexpected token request")
			}
			_, _ = w.Write([]byte(`{"access_token":"new-token","refresh_token":"new-refresh","expires_in":"3600"}`))
		case "/events":
			gets++
			q := r.URL.Query()
			if r.Header.Get("Authorization") != "Bearer new-token" || q.Get("fields") != fetchFields || q.Get("timeMin") != "2026-10-02T00:00:00-04:00" || q.Get("timeMax") != "2027-05-01T00:00:00-04:00" || q.Get("showDeleted") != "false" || q.Get("maxResults") != "2500" || q.Get("singleEvents") != "true" || q.Get("orderBy") != "startTime" {
				t.Error("unexpected event request")
			}
			if q.Get("pageToken") == "" {
				_, _ = w.Write([]byte(`{"items":[{"id":"a","status":"cancelled"}],"nextPageToken":"p2"}`))
			} else if q.Get("pageToken") == "p2" {
				_, _ = w.Write([]byte(`{}`))
			} else {
				t.Error("unexpected cursor")
			}
		default:
			t.Error("unexpected request")
		}
	}))
	defer s.Close()
	loc, err := time.LoadLocation("America/New_York")
	if err != nil {
		t.Fatal(err)
	}
	ctx := t.Context()
	c := NewWithConfig(Config{PrivateDir: dir, EventsURL: s.URL + "/events", TokenURL: s.URL + "/token", Now: func() time.Time { return now }})
	for i := 0; i < 2; i++ {
		pages, err := c.Fetch(ctx, travel.SyncWindow(now, loc))
		if err != nil || len(pages) != 2 {
			t.Fatalf("pages=%d err=%v", len(pages), err)
		}
		var p eventPage
		if err := json.Unmarshal(pages[1], &p); err != nil || p.RequestToken != "p2" || p.Items == nil {
			t.Fatal("missing page receipt")
		}
	}
	if posts != 1 || gets != 4 {
		t.Fatalf("refresh/events calls %d/%d", posts, gets)
	}
	b, err := os.ReadFile(filepath.Join(dir, tokenFile))
	if err != nil {
		t.Fatal(err)
	}
	var v credentials
	if json.Unmarshal(b, &v) != nil || v.RefreshToken != "new-refresh" || v.Token != "new-token" {
		t.Fatal("rotated tokens not saved")
	}
	for path, want := range map[string]os.FileMode{dir: 0700, filepath.Join(dir, tokenFile): 0600} {
		st, err := os.Stat(path)
		if err != nil || st.Mode().Perm() != want {
			t.Fatalf("mode differs: %v", err)
		}
	}
}

func TestAuthorizationErrors(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, tokenFile)
	c := NewWithConfig(Config{PrivateDir: dir, TokenURL: "http://127.0.0.1:1", EventsURL: "http://127.0.0.1:1"})
	if c.Connected() {
		t.Fatal("unexpected connection")
	}
	check := func(code string) {
		t.Helper()
		_, err := c.Fetch(t.Context(), travel.Window{})
		var pe *travel.ProviderError
		if !errors.As(err, &pe) || pe.Code != code || err.Error() != code {
			t.Fatalf("got %v want %s", err, code)
		}
	}
	check("gcal_not_connected")
	before := tokenFixture(t, dir, "2000-01-01T00:00:00Z")
	if !c.Connected() {
		t.Fatal("missing connection")
	}
	if err := os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
	check("gcal_credential_permissions")
	if err := os.Chmod(path, 0600); err != nil {
		t.Fatal(err)
	}
	check("gcal_remote_error")
	after, err := os.ReadFile(path)
	if err != nil || string(after) != string(before) {
		t.Fatal("refresh failure changed saved credentials")
	}
	for raw, code := range map[string]string{"{": "gcal_reauth_required", `{"refresh_token":"x","client_id":"i","client_secret":"s","scopes":"other"}`: "gcal_scope_missing"} {
		if err := os.WriteFile(path, []byte(raw), 0600); err != nil {
			t.Fatal(err)
		}
		check(code)
	}
}

func TestPageAndTransportFailures(t *testing.T) {
	for _, tc := range []struct {
		name       string
		status     int
		body, code string
	}{
		{"unauthorized", 401, "secret", "gcal_reauth_required"},
		{"quota", 403, `{"error":{"errors":[{"reason":"rateLimitExceeded"}]}}`, "gcal_rate_limited"},
		{"forbidden", 403, "secret", "gcal_remote_error"}, {"rate", 429, "secret", "gcal_rate_limited"},
		{"unavailable", 503, "secret", "gcal_remote_error"},
		{"list", 200, `[]`, "gcal_invalid_response"}, {"badItems", 200, `{"items":null}`, "gcal_invalid_response"},
		{"badItem", 200, `{"items":[null]}`, "gcal_invalid_response"}, {"badCursor", 200, `{"nextPageToken":[]}`, "gcal_invalid_response"},
		{"loop", 200, `{"nextPageToken":"repeat"}`, "gcal_invalid_response"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			tokenFixture(t, dir, "2999-01-01T00:00:00Z")
			s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path == "/token" {
					_, _ = w.Write([]byte(`{"access_token":"other","expires_in":3600}`))
					return
				}
				w.Header().Set("Retry-After", "7")
				w.WriteHeader(tc.status)
				_, _ = w.Write([]byte(tc.body))
			}))
			defer s.Close()
			c := NewWithConfig(Config{PrivateDir: dir, EventsURL: s.URL, TokenURL: s.URL + "/token"})
			pages, err := c.Fetch(t.Context(), travel.Window{})
			if pages != nil || err == nil || err.Error() != tc.code {
				t.Fatalf("got %v", err)
			}
			var re *RemoteError
			if tc.status != 200 && (!errors.As(err, &re) || re.StatusCode != tc.status || re.RetryAfter != "7") {
				t.Fatal("missing safe HTTP diagnostics")
			}
		})
	}
}

func TestRefreshDeniedScopePreservesCache(t *testing.T) {
	dir := t.TempDir()
	before := tokenFixture(t, dir, "2000-01-01T00:00:00Z")
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"access_token":"private","scope":"openid"}`))
	}))
	defer s.Close()
	c := NewWithConfig(Config{PrivateDir: dir, TokenURL: s.URL})
	if _, err := c.Fetch(context.Background(), travel.Window{}); err == nil || err.Error() != "gcal_scope_missing" {
		t.Fatalf("got %v", err)
	}
	got, err := os.ReadFile(filepath.Join(dir, tokenFile))
	if err != nil || string(got) != string(before) {
		t.Fatal("unsuccessful refresh changed cache")
	}
}

func TestFetchStopsAtTwentyPages(t *testing.T) {
	dir := t.TempDir()
	tokenFixture(t, dir, "2999-01-01T00:00:00Z")
	n := 0
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n++
		if n > 20 {
			t.Error("requested too many pages")
		}
		_ = json.NewEncoder(w).Encode(map[string]string{"nextPageToken": r.URL.Query().Get("pageToken") + "x"})
	}))
	defer s.Close()
	c := NewWithConfig(Config{PrivateDir: dir, EventsURL: s.URL})
	pages, err := c.Fetch(t.Context(), travel.Window{})
	if pages != nil || err == nil || err.Error() != "gcal_invalid_response" || n != 20 {
		t.Fatalf("pages: %d; error: %v", n, err)
	}
}

func TestTransientRefreshRetry(t *testing.T) {
	dir := t.TempDir()
	tokenFixture(t, dir, "2000-01-01T00:00:00Z")
	attempts := 0
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/token" {
			attempts++
			if attempts == 1 {
				w.WriteHeader(http.StatusServiceUnavailable)
				return
			}
			_, _ = w.Write([]byte(`{"access_token":"fake","expires_in":3600}`))
			return
		}
		_, _ = w.Write([]byte(`{"items":[]}`))
	}))
	defer s.Close()
	c := NewWithConfig(Config{PrivateDir: dir, EventsURL: s.URL + "/events", TokenURL: s.URL + "/token"})
	pages, err := c.Fetch(t.Context(), travel.Window{})
	if err != nil || len(pages) != 1 || attempts != 2 {
		t.Fatalf("attempts %d: %v", attempts, err)
	}
}
