package feedbackhttp

import (
	"bytes"
	"encoding/json"
	"github.com/jackc/pgx/v5/pgxpool"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
)

func TestPythonHTTP(t *testing.T) {
	cases := os.Getenv("FEEDBACK_HTTP_CASES")
	if cases == "" {
		t.Skip("run guarded prompt/RPE comparison")
	}
	cfg, err := pgxpool.ParseConfig(os.Getenv("PROPOSAL_TEST_DATABASE_URL"))
	if err != nil || cfg.ConnConfig.Database != "garmin_test" || os.Getenv("APP_MODE") != "test" || !strings.HasPrefix(os.Getenv("PGOPTIONS"), "-csearch_path=go_parity_") {
		t.Fatal("requires disposable test database")
	}
	cfg.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	pool, err := pgxpool.NewWithConfig(t.Context(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	now, _ := time.Parse(time.RFC3339Nano, "2026-11-22T12:00:00.123400Z")
	mux := http.NewServeMux()
	Handler{Pool: pool, Mode: "test", Now: func() time.Time { return now }}.Register(mux)
	b, err := os.ReadFile(cases)
	if err != nil {
		t.Fatal(err)
	}
	var casesData []struct {
		Path, Method, Body string
		Status             int
		Response           json.RawMessage
	}
	if err := json.Unmarshal(b, &casesData); err != nil {
		t.Fatal(err)
	}
	for _, c := range casesData {
		w := httptest.NewRecorder()
		w.Header().Set("X-Request-ID", "fixture")
		mux.ServeHTTP(w, httptest.NewRequest(c.Method, c.Path, strings.NewReader(c.Body)))
		var got map[string]any
		if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
			t.Fatal(err)
		}
		if p, ok := got["error"].(map[string]any); ok {
			delete(p, "request_id")
		}
		var expected map[string]any
		if err := json.Unmarshal(c.Response, &expected); err != nil {
			t.Fatal(err)
		}
		actual, _ := json.Marshal(got)
		want, _ := json.Marshal(expected)
		if w.Code != c.Status || !bytes.Equal(actual, want) {
			t.Fatalf("%s %s %s: got %d %s want %d %s", c.Method, c.Path, c.Body, w.Code, actual, c.Status, want)
		}
	}
}
