package httpapi

import (
	"bytes"
	"encoding/json"
	"net/http/httptest"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestExceptionHTTPReference(t *testing.T) {
	path := os.Getenv("EXCEPTION_HTTP_REFERENCE")
	if path == "" {
		t.Skip("requires scripts/rewrite/check_exception_http.py")
	}
	ctx := t.Context()
	pool, err := pgxpool.New(ctx, os.Getenv("PROPOSAL_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var database, schema string
	if err := pool.QueryRow(ctx, "SELECT current_database(),current_schema()").Scan(&database, &schema); err != nil || database != "garmin_test" || !strings.HasPrefix(schema, "go_parity_") {
		t.Fatal("expected isolated exception schema")
	}
	now, err := time.Parse(time.RFC3339Nano, os.Getenv("EXCEPTION_HTTP_NOW"))
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Method, Path string
		Body         json.RawMessage
		Status       int
		Expected     map[string]any
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	if len(cases) == 0 {
		t.Fatal("no captured reference cases")
	}
	h := New(nil, nil, nil, "test", "8000", "5173", ExceptionRoutes{pool, "test", func() time.Time { return now }}.Register)
	for _, c := range cases {
		req := httptest.NewRequest(c.Method, c.Path, bytes.NewReader(c.Body))
		req.Host = "testserver"
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-Local-Request", "1")
		w := httptest.NewRecorder()
		h.ServeHTTP(w, req)
		var got map[string]any
		if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
			t.Fatal(err)
		}
		if e, ok := got["error"].(map[string]any); ok {
			delete(e, "request_id")
		}
		if w.Code != c.Status || !reflect.DeepEqual(got, c.Expected) {
			t.Fatalf("%s %s\ngot %d %v\nwant %d %v", c.Method, c.Path, w.Code, got, c.Status, c.Expected)
		}
	}
}
