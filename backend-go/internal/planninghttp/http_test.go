package planninghttp

import (
	"context"
	"encoding/json"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"

	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"regexp"
	"strings"
	"testing"
	"time"
)

func TestReferencePlanningCommands(t *testing.T) {
	path := os.Getenv("PLANNING_COMMAND_CASES")
	if path == "" {
		t.Skip("check_planning_commands.py supplies oracle")
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, os.Getenv("PROPOSAL_TEST_DATABASE_URL"))
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var name, schema string
	if err := pool.QueryRow(ctx, "SELECT current_database(),current_schema()").Scan(&name, &schema); err != nil {
		t.Fatal(err)
	}
	if name != "garmin_test" || !regexp.MustCompile(`^go_parity_[0-9a-f]{32}$`).MatchString(schema) {
		t.Fatal("requires isolated synthetic schema")
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
		Undo         map[string]any
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 11, 16, 15, 0, 0, 0, time.UTC)
	h := Handler{Metrics: refresh.PlanMetrics(now, refresh.Runs), Pool: pool, Mode: "test", Now: func() time.Time { return now }}
	mux := http.NewServeMux()
	h.Register(mux)
	ids := map[string]string{}
	for i, c := range cases {
		body := string(c.Body)
		path := c.Path
		for ref, native := range ids {
			body = strings.ReplaceAll(body, ref, native)
			path = strings.ReplaceAll(path, ref, native)
		}
		req := httptest.NewRequest(c.Method, "/api/v1"+path, strings.NewReader(body))
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, req)
		var got map[string]any
		if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
			t.Fatal(err)
		}
		if o, ok := got["error"].(map[string]any); ok {
			delete(o, "request_id")
		}
		if w.Code == 201 && path == "/events" {
			ref := c.Expected["data"].(map[string]any)["id"].(string)
			ids[ref] = got["data"].(map[string]any)["id"].(string)
		}
		if c.Path == "/strength-routine" && w.Code == 200 {
			wantRows := c.Expected["data"].(map[string]any)["slots"].([]any)
			rows := got["data"].(map[string]any)["slots"].([]any)
			if len(wantRows) == len(rows) {
				for j, row := range rows {
					ref, ok := wantRows[j].(map[string]any)["id"].(string)
					if ok {
						ids[ref] = row.(map[string]any)["id"].(string)
					}
				}
			}
		}
		expected, _ := json.Marshal(c.Expected)
		text := string(expected)
		for ref, native := range ids {
			text = strings.ReplaceAll(text, ref, native)
		}
		var want map[string]any
		_ = json.Unmarshal([]byte(text), &want)
		if w.Code != c.Status || !reflect.DeepEqual(got, want) {
			t.Fatalf("case %d %s got %d %v want %d %v", i, path, w.Code, got, c.Status, want)
		}
	}
}
