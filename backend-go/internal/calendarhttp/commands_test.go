package calendarhttp

import (
	"context"
	"encoding/json"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/calendar"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"regexp"
	"strings"
	"testing"
	"time"
)

func TestReferenceCalendarCommands(t *testing.T) {
	path := os.Getenv("CALENDAR_COMMAND_CASES")
	if path == "" {
		t.Skip("check_calendar_commands.py supplies oracle")
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
	h := Handler{Pool: pool, Mode: "test", Now: func() time.Time { return now }, Metrics: func(context.Context, pgx.Tx, calendar.PlanScope, []uuid.UUID) error { return nil }}
	mux := http.NewServeMux()
	h.Register(mux)
	for i, c := range cases {
		body := string(c.Body)
		for n, label := range []string{"slot:0", "slot:1"} {
			if strings.Contains(body, label) {
				var uid string
				if err := pool.QueryRow(ctx, "SELECT session_uid::text FROM calendar_session_revisions WHERE calendar_version_number=1 ORDER BY local_date,slot OFFSET $1 LIMIT 1", n).Scan(&uid); err != nil {
					t.Fatal(err)
				}
				body = strings.ReplaceAll(body, label, uid)
			}
		}
		req := httptest.NewRequest(c.Method, "/api/v1"+c.Path, strings.NewReader(body))
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, req)
		var got map[string]any
		if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
			t.Fatal(err)
		}
		if o, ok := got["error"].(map[string]any); ok {
			delete(o, "request_id")
		}
		if o, ok := got["data"].(map[string]any); ok {
			if c.Path == "/anchors" {
				if rows, ok := o["items"].([]any); ok {
					for _, r := range rows {
						delete(r.(map[string]any), "id")
					}
				} else {
					delete(o, "id")
				}
			}
			if ids, ok := o["preserved_session_uids"].([]any); ok {
				for j := range ids {
					ids[j] = "protected"
				}
			}
		}
		err := pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{AccessMode: pgx.ReadOnly}, func(tx pgx.Tx) error {
			var head int
			if err := tx.QueryRow(ctx, "SELECT calendar_head_version FROM app_state").Scan(&head); err != nil {
				return err
			}
			undo, err := calendar.PreviewUndo(ctx, tx, head, "2026-11-16")
			if err != nil {
				return err
			}
			var actual map[string]any
			if undo != nil {
				actual = map[string]any{"target_version": float64(undo.TargetVersion), "eligible": undo.Eligible, "protected_session_uids": []any{}}
				for range undo.ProtectedSessionUIDs {
					actual["protected_session_uids"] = append(actual["protected_session_uids"].([]any), "protected")
				}
			}
			if !reflect.DeepEqual(actual, c.Undo) {
				t.Fatalf("case %d undo got %v want %v", i, actual, c.Undo)
			}
			return nil
		})
		if err != nil {
			t.Fatal(err)
		}
		if w.Code != c.Status || !reflect.DeepEqual(got, c.Expected) {
			t.Fatalf("case %d %s got %d %v want %d %v", i, c.Path, w.Code, got, c.Status, c.Expected)
		}
	}
}
