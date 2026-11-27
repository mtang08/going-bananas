package completionhttp

import (
	"bytes"

	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

type fixture struct {
	Path, Body string
	Status     int
	Response   json.RawMessage
}

func TestCompletionHTTP(t *testing.T) {
	cases := os.Getenv("COMPLETION_HTTP_CASES")
	if cases == "" {
		t.Skip("run guarded FastAPI comparison")
	}
	cfg, err := pgxpool.ParseConfig(os.Getenv("PROPOSAL_TEST_DATABASE_URL"))
	if err != nil || cfg.ConnConfig.Database != "garmin_test" || os.Getenv("APP_MODE") != "test" || !strings.HasPrefix(os.Getenv("PGOPTIONS"), "-csearch_path=go_parity_") {
		t.Fatal("requires disposable test DB")
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
	request := func(path, body string) (int, map[string]any) {
		w := httptest.NewRecorder()
		w.Header().Set("X-Request-ID", "fixture")
		r := httptest.NewRequest(http.MethodPut, path, strings.NewReader(body))
		mux.ServeHTTP(w, r)
		var v map[string]any
		if err := json.Unmarshal(w.Body.Bytes(), &v); err != nil {
			t.Error(err)
		}
		if problem, ok := v["error"].(map[string]any); ok {
			delete(problem, "request_id")
		}
		return w.Code, v
	}
	if mode := os.Getenv("COMPLETION_HTTP_FAILURE"); mode != "" {
		path := "/api/v1/calendar/completions/00000000-0000-0000-0000-00000000000a"
		var rev int
		if err := pool.QueryRow(t.Context(), "SELECT data_revision FROM app_state WHERE id=1").Scan(&rev); err != nil {
			t.Fatal(err)
		}
		code, _ := request(path, `{"expected_version":1,"status":"completed_as_planned","reason_note":"failure probe"}`)
		if code != 500 {
			t.Fatalf("%s returned %d", mode, code)
		}
		var version, after int
		var note string
		if err := pool.QueryRow(t.Context(), "SELECT version,reason_note,(SELECT data_revision FROM app_state WHERE id=1) FROM session_completions WHERE session_uid='00000000-0000-0000-0000-00000000000a'").Scan(&version, &note, &after); err != nil {
			t.Fatal(err)
		}
		if mode == "metric-fail" && (version != 1 || after != rev) {
			t.Fatal("source write survived failed metric transaction")
		}
		if mode == "detect-fail" && (version != 2 || after != rev+1 || note != "failure probe") {
			t.Fatal("detector failure lost committed source write")
		}
		return
	}
	raw, err := os.ReadFile(cases)
	if err != nil {
		t.Fatal(err)
	}
	var corpus []fixture
	if err := json.Unmarshal(raw, &corpus); err != nil {
		t.Fatal(err)
	}
	for _, c := range corpus {
		status, v := request(c.Path, c.Body)
		if data, ok := v["data"].(map[string]any); ok {
			var stored string
			if err := pool.QueryRow(t.Context(), "SELECT id::text FROM session_completions WHERE session_uid=$1", data["session_uid"]).Scan(&stored); err != nil || data["id"] != stored {
				t.Fatal("completion ID differs", err)
			}
			data["id"] = "verified-database-id"
		}
		got, _ := json.Marshal(v)
		var want any
		if err := json.Unmarshal(c.Response, &want); err != nil {
			t.Fatal(err)
		}
		expected, _ := json.Marshal(want)
		if status != c.Status || !bytes.Equal(got, expected) {
			t.Fatalf("%s %s: got %d %s, want %d %s", c.Path, c.Body, status, got, c.Status, expected)
		}
	}
	// Two optimistic edits at the same version serialize under the application lock.
	path := "/api/v1/calendar/completions/00000000-0000-0000-0000-00000000000a"
	status := make(chan int, 2)
	for _, note := range []string{"one", "two"} {
		go func() { code, _ := request(path, `{"status":"skipped","reason_note":"`+note+`"}`); status <- code }()
	}
	codes := []int{<-status, <-status}
	slices.Sort(codes)
	if !slices.Equal(codes, []int{200, 409}) {
		t.Fatal(codes)
	}
}
