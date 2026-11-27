package activityhttp

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/jackc/pgx/v5/pgxpool"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"regexp"
	"testing"
	"time"
)

func difference(a, b any, path string) string {
	if reflect.DeepEqual(a, b) {
		return ""
	}
	switch x := a.(type) {
	case map[string]any:
		y, ok := b.(map[string]any)
		if ok {
			for k, v := range x {
				if msg := difference(v, y[k], path+"."+k); msg != "" {
					return msg
				}
			}
			for k := range y {
				if _, ok := x[k]; !ok {
					return path + " missing " + k
				}
			}
		}
	case []any:
		y, ok := b.([]any)
		if ok && len(x) == len(y) {
			for i, v := range x {
				if msg := difference(v, y[i], fmt.Sprintf("%s[%d]", path, i)); msg != "" {
					return msg
				}
			}
		}
	}
	return fmt.Sprintf("%s: %v != %v", path, a, b)
}
func TestActivityReads(t *testing.T) {
	file := os.Getenv("ACTIVITY_READ_CASES")
	if file == "" {
		t.Skip("requires Python oracle")
	}
	raw, err := os.ReadFile(file)
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Path   string
		Status int
		Body   map[string]any
	}
	if err = json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	p, err := pgxpool.New(t.Context(), "")
	if err != nil {
		t.Fatal(err)
	}
	defer p.Close()
	var schema string
	cfg := p.Config().ConnConfig
	if cfg.Database != "garmin_test" || (cfg.Host != "127.0.0.1" && cfg.Host != "localhost") || p.QueryRow(t.Context(), "select current_schema()").Scan(&schema) != nil || !regexp.MustCompile("^go_parity_[0-9a-f]{32}$").MatchString(schema) {
		t.Fatal("expected disposable fixture")
	}
	mux := http.NewServeMux()
	Handler{Pool: p, Mode: "test", Now: func() time.Time { return time.Date(2026, 11, 26, 12, 0, 0, 0, time.UTC) }}.Register(mux)
	counts := func(ctx context.Context) (string, error) {
		var s string
		err := p.QueryRow(ctx, "SELECT json_build_array((SELECT count(*) FROM metric_results),(SELECT count(*) FROM metric_configs),(SELECT data_revision FROM app_state WHERE id=1))::text").Scan(&s)
		return s, err
	}
	before, err := counts(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range cases {
		t.Run(c.Path, func(t *testing.T) {
			req := httptest.NewRequest("GET", "/api/v1"+c.Path, nil)
			w := httptest.NewRecorder()
			mux.ServeHTTP(w, req)
			var got object
			if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
				t.Fatal(w.Code, w.Body.String())
			}
			if e, ok := got["error"].(map[string]any); ok {
				delete(e, "request_id")
			}
			if w.Code != c.Status {
				t.Fatalf("HTTP %d vs %d: %v", w.Code, c.Status, got)
			}
			if diff := difference(got, c.Body, "body"); diff != "" {
				t.Fatal(diff)
			}
		})
	}
	after, err := counts(t.Context())
	if err != nil || before != after {
		t.Fatal("GET mutated source or metric state", before, after, err)
	}
}
