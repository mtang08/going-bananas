package googlecalendar

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/travel"
)

func TestConsentCallbackAndPKCE(t *testing.T) {
	for _, tc := range []struct{ name, scope, refresh, want string }{{"success", readScope, "fixture-refresh", ""}, {"scope", "other", "fixture-refresh", "gcal_scope_missing"}, {"refresh", readScope, "", "gcal_no_refresh_token"}} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			challenge := make(chan string, 1)
			srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				sum := sha256.Sum256([]byte(r.FormValue("code_verifier")))
				if base64.RawURLEncoding.EncodeToString(sum[:]) != <-challenge || r.FormValue("code") != "fixture-code" || r.FormValue("client_secret") != "fixture-secret" {
					t.Error("unexpected token exchange")
				}
				w.Header().Set("Content-Type", "application/json")
				_ = json.NewEncoder(w).Encode(map[string]any{"access_token": "fixture-access", "refresh_token": tc.refresh, "scope": tc.scope, "expires_in": 3600, "token_type": "Bearer"})
			}))
			defer srv.Close()
			app, _ := json.Marshal(map[string]any{"installed": desktopClient{"fixture-id", "fixture-secret", srv.URL + "/auth", srv.URL + "/token"}})
			if err := os.WriteFile(filepath.Join(dir, "google-calendar-client.json"), app, 0600); err != nil {
				t.Fatal(err)
			}
			c := NewWithConfig(Config{PrivateDir: dir, HTTPClient: srv.Client()})
			ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
			defer cancel()
			err := c.Connect(ctx, func(link string) error {
				parsed, err := url.Parse(link)
				if err != nil {
					return err
				}
				q := parsed.Query()
				challenge <- q.Get("code_challenge")
				redirect := q.Get("redirect_uri")
				if !strings.HasPrefix(redirect, "http://127.0.0.1:") || q.Get("code_challenge_method") != "S256" || q.Get("scope") != readScope || q.Get("prompt") != "consent" || q.Get("access_type") != "offline" || q.Get("state") == "" {
					t.Error("consent parameters")
				}
				for _, state := range []string{"wrong", q.Get("state")} {
					req, err := http.NewRequestWithContext(ctx, "GET", redirect+"?"+url.Values{"state": {state}, "code": {"fixture-code"}}.Encode(), nil)
					if err != nil {
						return err
					}
					resp, err := http.DefaultClient.Do(req)
					if err != nil {
						return err
					}
					_ = resp.Body.Close()
					if (resp.StatusCode == 200) != (state == q.Get("state")) {
						t.Error("unexpected callback status", resp.StatusCode)
					}
				}
				return nil
			})
			if tc.want != "" {
				if err == nil || err.Error() != tc.want || c.Connected() {
					t.Fatal("incorrect grant result", err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			info, err := os.Stat(filepath.Join(dir, tokenFile))
			if err != nil || info.Mode().Perm() != 0600 {
				t.Fatal("token permissions")
			}
			v, err := c.authorize(ctx)
			if err != nil || v.Token != "fixture-access" {
				t.Fatal("token cache incompatible", err)
			}
		})
	}
}
func TestProbePythonReport(t *testing.T) {
	b, err := os.ReadFile("../../../backend/tests/fixtures/gcal/basic_pages.json")
	if err != nil {
		t.Fatal(err)
	}
	var f struct {
		Calendars []map[string]any
		Pages     []json.RawMessage
	}
	if err = json.Unmarshal(b, &f); err != nil {
		t.Fatal(err)
	}
	gold, err := os.ReadFile("testdata/probe.txt")
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	cache, _ := json.Marshal(map[string]any{"token": "fixture", "client_id": "fixture", "client_secret": "fixture", "refresh_token": "fixture", "scopes": []string{readScope}, "expiry": "2031-01-01T00:00:00Z"})
	if err = os.WriteFile(filepath.Join(dir, tokenFile), cache, 0600); err != nil {
		t.Fatal(err)
	}
	index := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer fixture" {
			t.Error("missing authorization")
		}
		if r.URL.Path == "/list" {
			if r.URL.Query().Get("fields") != "items(summary,accessRole,primary)" {
				t.Error("calendar projection")
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"items": f.Calendars})
			return
		}
		if r.URL.Path != "/events" || index >= len(f.Pages) {
			t.Error("invalid event request")
			w.WriteHeader(400)
			return
		}
		_, _ = w.Write(f.Pages[index])
		index++
	}))
	defer srv.Close()
	c := NewWithConfig(Config{PrivateDir: dir, CalendarsURL: srv.URL + "/list", EventsURL: srv.URL + "/events", Now: func() time.Time { return time.Date(2026, 3, 1, 0, 0, 0, 0, time.UTC) }})
	got, err := c.Probe(t.Context(), 60)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(got, "\n")+"\n" != string(gold) {
		t.Fatalf("probe differs from Python\n%s", strings.Join(got, "\n"))
	}
	for _, days := range []int{0, 181} {
		if _, err = c.Probe(t.Context(), days); err == nil || err.Error() != "invalid_date_window" {
			t.Fatal(days, err)
		}
	}
}

func TestProbeSuppressesUnrecognizedMetadata(t *testing.T) {
	rows := []map[string]any{{"summary": "private@unlisted.invalid", "accessRole": "private role"}}
	raw := json.RawMessage(`{"items":[{"id":"secret-identity","summary":"Unlisted Person","location":"private@unlisted.invalid","eventType":"private-meeting","transparency":"private-status","start":{"dateTime":"2026-03-01T11:00:00Z","timeZone":"private/zone"},"end":{"dateTime":"2026-03-01T12:00:00Z","timeZone":"UTC"},"attendees":[{"self":true,"responseStatus":"private-rsvp"}]}]}`)
	lines, err := probeLines(rows, []json.RawMessage{raw})
	if err != nil {
		t.Fatal(err)
	}
	wanted := "calendar name=<email> access_role=- primary=false\nevent type=unknown kind=timed start_tz=- end_tz=UTC transparency=opaque response=- dur_h=1.0 title=\"<X>\" location=\"<X>\"\nsummary events=1 unknown=1 tz_differs=0 tz_missing=1"
	if strings.Join(lines, "\n") != wanted {
		t.Fatal("unexpected probe redaction", lines)
	}
}

func TestRevokedBearerRefreshesOnce(t *testing.T) {
	dir := t.TempDir()
	tokenFixture(t, dir, "2999-01-01T00:00:00Z")
	var grants, requests int
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/token" {
			grants++
			_, _ = w.Write([]byte(`{"access_token":"rotated","expires_in":3600}`))
			return
		}
		requests++
		if r.Header.Get("Authorization") != "Bearer rotated" {
			w.WriteHeader(401)
			return
		}
		_, _ = w.Write([]byte(`{"items":[]}`))
	}))
	defer srv.Close()
	c := NewWithConfig(Config{PrivateDir: dir, EventsURL: srv.URL, TokenURL: srv.URL + "/token"})
	pages, err := c.Fetch(t.Context(), travel.Window{})
	if err != nil || len(pages) != 1 || requests != 2 || grants != 1 {
		t.Fatal("reauthorization did not recover", err, requests, grants)
	}
}
