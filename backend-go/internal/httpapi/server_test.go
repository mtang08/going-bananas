package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/proposals"
)

type readFunc func(context.Context, string) (proposals.List, error)

func (f readFunc) List(ctx context.Context, status string) (proposals.List, error) {
	return f(ctx, status)
}

func TestProposalListHTTP(t *testing.T) {
	now := time.Date(2026, 2, 1, 15, 2, 0, 123400000, time.FixedZone("EST", -5*3600))
	store := readFunc(func(_ context.Context, status string) (proposals.List, error) {
		switch status {
		case "open":
			return proposals.List{DataRevision: 17, Items: []proposals.Item{{ID: uuid.MustParse("9248048b-7c1e-4948-b0a1-f0623c9d7e13"), Status: "pending", Operation: "rolling", Headline: "New plan", Revision: 2, SubmittedAt: now}}}, nil
		case "invalid":
			return proposals.List{}, errors.New("private database error")
		case "":
			return proposals.List{DataRevision: 17}, nil
		default:
			t.Errorf("unexpected filter %q", status)
			return proposals.List{}, nil
		}
	})
	ts := httptest.NewUnstartedServer(nil)
	defer ts.Close()
	addr := ts.Listener.Addr().String()
	_, port, _ := strings.Cut(addr, ":")
	ts.Config.Handler = New(store, nil, nil, api.Demo, port, "5173")
	ts.Start()
	ts.Client().CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	request := func(method, path, host, origin string) (int, http.Header, string) {
		t.Helper()
		req, err := http.NewRequest(method, ts.URL+path, nil)
		if err != nil {
			t.Fatal(err)
		}
		if host != "" {
			req.Host = host
		}
		req.Header.Set("Origin", origin)
		resp, err := ts.Client().Do(req)
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = resp.Body.Close() }()
		body, err := io.ReadAll(resp.Body)
		if err != nil {
			t.Fatal(err)
		}
		return resp.StatusCode, resp.Header, string(body)
	}
	path := "/api/v1/coach/proposals"
	for _, tc := range []struct {
		query    string
		status   int
		contains []string
	}{
		{"", 200, []string{`"items":[]`, `"mode":"demo"`, `"data_revision":17`}},
		{"?status=bogus&status=open", 200, []string{`"submitted_at":"2026-02-01T15:02:00.123400-05:00"`, `"decided_at":null`, `"discarded_at":null`, `"change_count":0`}},
		{"?status=open&status=bogus", 422, []string{`"field":"query.status"`, `"retryable":false`}},
		{"?status=", 422, []string{`"code":"validation_error"`}},
	} {
		t.Run(url.QueryEscape(tc.query), func(t *testing.T) {
			status, headers, body := request("GET", path+tc.query, "", "http://localhost:5173")
			id := headers.Get("X-Request-ID")
			if status != tc.status || headers.Get("Cache-Control") != "no-store" || !regexp.MustCompile("^[0-9a-f]{16}$").MatchString(id) {
				t.Fatalf("status %d, headers %v", status, headers)
			}
			if status == 422 && !strings.Contains(body, id) {
				t.Errorf("missing request ID: %s", body)
			}
			for _, s := range tc.contains {
				if !strings.Contains(body, s) {
					t.Errorf("response missing %q: %s", s, body)
				}
			}
		})
	}
	for _, tc := range []struct {
		method, path, host, origin, code string
		status                           int
	}{
		{"GET", path, "foreign.example", "", "invalid_host", 403},
		{"GET", path, "", "http://foreign.example", "invalid_origin", 403},
		{"POST", path, "", "", "csrf_header_required", 403},
		{"HEAD", path, "", "", "", 405},
		{"GET", path + "/?status=open", "", "", "not_found", 404},
		{"OPTIONS", path + "/", "", "", "method_not_allowed", 405},
		{"GET", "/api/v1/other", "", "", "not_found", 404},
		{"GET", path + "?status=invalid", "", "", "internal_error", 500},
	} {
		status, _, body := request(tc.method, tc.path, tc.host, tc.origin)
		if status != tc.status {
			t.Errorf("%s %s returned %d", tc.method, tc.path, status)
		}
		if tc.code == "" {
			continue
		}
		var v struct {
			Error struct {
				Code      string
				RequestID string `json:"request_id"`
				Retryable bool
				Fields    []api.ValidationField
			}
		}
		if err := json.Unmarshal([]byte(body), &v); err != nil {
			t.Fatal(err)
		}
		if v.Error.Code != tc.code || v.Error.RequestID == "" || v.Error.Fields == nil || v.Error.Retryable != (status == 500) || strings.Contains(body, "private database error") {
			t.Errorf("unexpected error for %s: %s", tc.path, body)
		}
	}
}
