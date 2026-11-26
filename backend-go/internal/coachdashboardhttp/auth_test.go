package coachdashboardhttp

import (
	"context"
	"io"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/mtang08/going-bananas/backend-go/internal/coachdashboard"
)

func TestAuthHTTPUsesLocalGuardsAndEmptyInput(t *testing.T) {
	calls := 0
	auth := coachdashboard.NewAuth(func(context.Context) (io.ReadWriteCloser, error) {
		calls++
		return nil, &coachdashboard.Problem{Code: "not_installed", Message: "Synthetic missing CLI"}
	})
	h := NewWithAuth(&stubGateway{}, stubMetadata{}, auth, "test", "8000", "5173")
	for _, tc := range []struct {
		suffix, body string
		remote       bool
		status       int
	}{{"/auth/start", "{}", true, 403}, {"/auth/start", `{"thread_id":null}`, false, 422}, {"/auth/cancel", "{}", false, 200}} {
		r := request("POST", tc.suffix, tc.body)
		if tc.remote {
			r.RemoteAddr = "192.0.2.1:1234"
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != tc.status || calls != 0 {
			t.Fatal(w.Code, w.Body, calls)
		}
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, request("GET", "/auth", ""))
	if w.Code != 200 || !strings.Contains(w.Body.String(), "not_installed") || calls != 1 {
		t.Fatal(w.Code, w.Body, calls)
	}
}
