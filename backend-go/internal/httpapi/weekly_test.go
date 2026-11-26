package httpapi

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/api"
)

func TestWeeklyHTTPValidationAndGuards(t *testing.T) {
	h := NewWeekly(nil, api.AppMode("test"), "8000", "5173")
	for _, tc := range []struct {
		path, method, host, origin string
		code                       int
		problem                    string
	}{
		{WeeklyProjectionPath, "POST", "localhost:8000", "", 405, "method_not_allowed"},
		{WeeklyDigestPath, "DELETE", "localhost:8000", "", 405, "method_not_allowed"},
		{WeeklyProjectionPath, "GET", "outside.invalid", "", 403, "invalid_host"},
		{WeeklyDigestPath, "GET", "localhost:8000", "http://outside.invalid", 403, "invalid_origin"},
		{WeeklyDigestPath + "?week_start=not-a-date", "GET", "localhost", "", 422, "validation_error"},
		{WeeklyDigestPath + "?week_start=2030-01-07&week_start=2030-01-08", "GET", "localhost", "", 422, "invalid_week_start"},
		{WeeklyDigestPath + "/", "GET", "localhost", "", 307, ""},
		{WeeklyDigestPath + "-extra", "GET", "localhost", "", 404, "not_found"},
	} {
		r := httptest.NewRequest(tc.method, tc.path, nil)
		r.Host = tc.host
		r.Header.Set("Origin", tc.origin)
		r.Header.Set("X-Local-Request", "1")
		r.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != tc.code {
			t.Fatalf("%s %s: got %d", tc.method, tc.path, w.Code)
		}
		if tc.problem == "" {
			continue
		}
		var e api.ErrorEnvelope
		if err := json.Unmarshal(w.Body.Bytes(), &e); err != nil {
			t.Fatal(err)
		}
		if e.Error.Code != tc.problem || e.Error.RequestId == "" {
			t.Fatal(e)
		}
		if tc.problem == "validation_error" && (len(e.Error.Fields) != 1 || e.Error.Fields[0].Field != "query.week_start") {
			t.Fatal(e)
		}
	}
}

func TestWeeklyHTTPPostgres(t *testing.T) {
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires disposable PostgreSQL runner")
	}
	pool, err := pgxpool.New(t.Context(), dsn)
	if err != nil {
		t.Fatal("connect to synthetic server")
	}
	defer pool.Close()
	now := time.Date(2050, 1, 23, 17, 0, 0, 0, time.UTC)
	h := &weeklyHandler{pool, api.AppMode("test"), newGuard("8000", "5173"), func() time.Time { return now }}
	revision := func() int {
		t.Helper()
		var v int
		if err := pool.QueryRow(t.Context(), "SELECT COALESCE((SELECT data_revision FROM app_state WHERE id=1),0)").Scan(&v); err != nil {
			t.Fatal(err)
		}
		return v
	}
	before := revision()
	for _, tc := range []struct{ path, start string }{
		{WeeklyProjectionPath + "?week_start=nonsense", "2050-01-17"},
		{WeeklyDigestPath, "2050-01-17"},
		{WeeklyDigestPath + "?week_start=bad&week_start=2050-01-10", "2050-01-10"},
	} {
		req := httptest.NewRequest("GET", tc.path, nil)
		req.Host = "localhost:8000"
		req.Header.Set("Origin", "http://localhost:5173")
		w := httptest.NewRecorder()
		h.ServeHTTP(w, req)
		if w.Code != 200 {
			t.Fatalf("%s: HTTP %d %s", tc.path, w.Code, w.Body)
		}
		var response struct {
			Data         map[string]any
			DataRevision int `json:"data_revision"`
			Mode         string
			Schema       string `json:"schema_version"`
		}
		if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil {
			t.Fatal(err)
		}
		if w.Header().Get("Cache-Control") != "no-store" || response.DataRevision != before || response.Mode != "test" || response.Schema != "v1" || response.Data["week_start"] != tc.start {
			t.Fatal(response)
		}
	}
	if before != revision() {
		t.Fatal("GET changed data revision")
	}
}
