package proposalhttp

import (
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drafts"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"regexp"
	"strings"
	"testing"
)

func TestReferenceViews(t *testing.T) {
	path := os.Getenv("COACHING_HTTP_REFERENCE")
	if path == "" {
		t.Skip("check_lifecycle.py supplies Python HTTP responses")
	}
	pool, err := pgxpool.New(context.Background(), os.Getenv("COACHING_DECISION_TEST_URL"))
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var db, schema string
	if err := pool.QueryRow(context.Background(), "SELECT current_database(),current_schema()").Scan(&db, &schema); err != nil {
		t.Fatal(err)
	}
	if db != "garmin_test" || !regexp.MustCompile(`^go_drafts_[0-9a-f]{32}$`).MatchString(schema) {
		t.Fatal("requires isolated schema")
	}
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Path string
		Body map[string]any
	}
	if err := json.Unmarshal(b, &cases); err != nil {
		t.Fatal(err)
	}
	h := Handler{Store: drafts.Store{Pool: pool}, KBRoot: "../../../running_coach_kb", Mode: "test"}
	mux := http.NewServeMux()
	h.Register(mux)
	for _, c := range cases {
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, httptest.NewRequest("GET", c.Path, nil))
		var got map[string]any
		if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
			t.Fatal(err)
		}
		if w.Code != 200 {
			t.Fatalf("view %s error %d %v", c.Path, w.Code, got)
		}
		if !reflect.DeepEqual(c.Body, got) {
			a, _ := c.Body["data"].(map[string]any)
			b, _ := got["data"].(map[string]any)
			for k, v := range a {
				if !reflect.DeepEqual(v, b[k]) {
					t.Errorf("%s field %s: got %v want %v", c.Path, k, b[k], v)
				}
			}
			for k := range b {
				if _, ok := a[k]; !ok {
					t.Errorf("%s extra field %s", c.Path, k)
				}
			}
			t.FailNow()
		}
	}
	// A structural error must not open a transaction that edits the draft.
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, httptest.NewRequest("POST", prefix+"/00000000-0000-0000-0000-000000000099/revise", strings.NewReader(`{"expected_revision":0,"reason":"","document":[]}`)))
	if w.Code != 422 {
		t.Fatal(w.Code)
	}
}
