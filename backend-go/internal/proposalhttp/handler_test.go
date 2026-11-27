package proposalhttp

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drafts"
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
		Path   string
		Status int
		Body   map[string]any
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
		if e, ok := got["error"].(map[string]any); ok {
			delete(e, "request_id")
		}
		if w.Code != c.Status {
			t.Fatalf("view %s: got status %d want %d", c.Path, w.Code, c.Status)
		}
		if !reflect.DeepEqual(c.Body, got) {
			if c.Status != http.StatusOK {
				t.Fatalf("view %s: got %v want %v", c.Path, got, c.Body)
			}
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

func TestReferenceCommands(t *testing.T) {
	path := os.Getenv("COACHING_HTTP_COMMANDS")
	if path == "" {
		t.Skip("synthetic HTTP workflow supplied by check_lifecycle.py")
	}
	pool, err := pgxpool.New(context.Background(), os.Getenv("COACHING_DECISION_TEST_URL"))
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var name, schema string
	if err := pool.QueryRow(context.Background(), "SELECT current_database(),current_schema()").Scan(&name, &schema); err != nil {
		t.Fatal(err)
	}
	if name != "garmin_test" || !regexp.MustCompile(`^go_drafts_[0-9a-f]{32}$`).MatchString(schema) {
		t.Fatal("requires isolated schema")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Method, Path string
		Body         json.RawMessage
		Status       int
		Expected     map[string]any
	}
	if err := json.Unmarshal(data, &cases); err != nil {
		t.Fatal(err)
	}
	h := Handler{Store: drafts.Store{Pool: pool}, KBRoot: "../../../running_coach_kb", Mode: "test"}
	mux := http.NewServeMux()
	h.Register(mux)
	id := ""
	for i, c := range cases {
		// The coach CLI creates the pending draft. The public API only revises
		// or reviews an existing draft.
		if c.Path == "" {
			res, err := h.Store.Submit(context.Background(), c.Body, time.Now().UTC(), drafts.NewValidator(h.KBRoot))
			if err != nil {
				t.Fatal(err)
			}
			id = res.ID.String()
			continue
		}
		w := httptest.NewRecorder()
		req := httptest.NewRequest(c.Method, prefix+strings.ReplaceAll(c.Path, "ID", id), strings.NewReader(string(c.Body)))
		mux.ServeHTTP(w, req)
		var got map[string]any
		if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
			t.Fatal(err)
		}
		if e, ok := got["error"].(map[string]any); ok {
			delete(e, "request_id")
		}
		if d, ok := got["data"].(map[string]any); ok {
			if v, ok := d["proposal_id"].(string); ok {
				if c.Path == "" {
					id = v
				} else if id != v {
					t.Fatalf("step %d proposal changed", i)
				}
				d["proposal_id"] = "ID"
			}
		}
		if w.Code != c.Status || !reflect.DeepEqual(c.Expected, got) {
			t.Fatalf("step %d %s %s: got %d %v want %d %v", i, c.Method, c.Path, w.Code, got, c.Status, c.Expected)
		}
	}
}

func TestRevisionNumber(t *testing.T) {
	for input, want := range map[string]int{
		"-2.000":                 -2,
		"  +01.00 ":              1,
		"1_0.0":                  10,
		"0":                      0,
		"2147483648":             2147483648,
		"9223372036854775807.0":  9223372036854775807,
		"-9223372036854775808.0": -9223372036854775808,
	} {
		got, message := revisionNumber(input)
		if message != "" || got != want {
			t.Errorf("%q: got %d, %q", input, got, message)
		}
	}
	for _, input := range []string{"1.1", "1e0", "1.", "--1", "1__2", "9223372036854775808", "-9223372036854775809"} {
		if _, message := revisionNumber(input); message == "" {
			t.Errorf("%q should fail validation", input)
		}
	}
}

func TestRevisionOutsideDatabaseRange(t *testing.T) {
	mux := http.NewServeMux()
	Handler{Mode: "test"}.Register(mux)
	for _, c := range []struct {
		revision string
		status   int
		code     string
	}{
		{"2147483648", http.StatusNotFound, "proposal_revision_not_found"},
		{"-2147483649", http.StatusNotFound, "proposal_revision_not_found"},
		{"9223372036854775807", http.StatusNotFound, "proposal_revision_not_found"},
		{"-9223372036854775808", http.StatusNotFound, "proposal_revision_not_found"},
		{"9223372036854775808", http.StatusUnprocessableEntity, "validation_error"},
		{"-9223372036854775809", http.StatusUnprocessableEntity, "validation_error"},
	} {
		t.Run(c.revision, func(t *testing.T) {
			w := httptest.NewRecorder()
			path := prefix + "/00000000-0000-0000-0000-000000000099/revisions/" + c.revision
			mux.ServeHTTP(w, httptest.NewRequest(http.MethodGet, path, nil))
			var body struct {
				Error struct{ Code string }
			}
			if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
				t.Fatal(err)
			}
			if w.Code != c.status || body.Error.Code != c.code {
				t.Fatalf("got %d %s want %d %s", w.Code, body.Error.Code, c.status, c.code)
			}
		})
	}
}
