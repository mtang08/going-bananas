package proposalhttp

import (
	"context"
	"embed"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drafts"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/snapshots"
)

// The JSON captures complete responses from the retired Python routes at
// e5e565d. views.sql is the exact seed used in UTC and America/New_York.
// commands.json records the synthetic lifecycle on a fresh calendar at head 0;
// the snapshot ID and athlete day are filled in by the native test.
//
//go:embed testdata/*
var responseFixtures embed.FS

func proposalPool(t *testing.T, zone, seed string) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("DASHBOARD_TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("requires the isolated PostgreSQL dashboard runner")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil || cfg.ConnConfig.Database != "garmin_test" ||
		(cfg.ConnConfig.Host != "127.0.0.1" && cfg.ConnConfig.Host != "localhost") ||
		!regexp.MustCompile(`^go_parity_[a-f0-9]{32}$`).MatchString(cfg.ConnConfig.RuntimeParams["search_path"]) {
		t.Fatal("requires the isolated PostgreSQL dashboard fixture")
	}
	schema := cfg.ConnConfig.RuntimeParams["search_path"]
	cfg.ConnConfig.RuntimeParams["TimeZone"] = zone
	cfg.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	cfg.MaxConns = 1
	cfg.AfterConnect = func(ctx context.Context, conn *pgx.Conn) error {
		var current string
		if err := conn.QueryRow(ctx, "SELECT current_schema()").Scan(&current); err != nil || current != schema {
			return errors.New("proposal test requires migrated fixture schema")
		}
		return pgx.BeginTxFunc(ctx, conn, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
			// These private views shadow the migrated schema only for this connection.
			// The fixture may write through the pool without affecting later packages.
			if _, err := tx.Exec(ctx, `
CREATE TEMP TABLE app_state AS SELECT * FROM app_state;
CREATE TEMP TABLE coach_snapshots (LIKE coach_snapshots INCLUDING ALL);
CREATE TEMP TABLE coach_proposals (LIKE coach_proposals INCLUDING ALL);
CREATE TEMP TABLE coach_proposal_revisions (LIKE coach_proposal_revisions INCLUDING ALL);
CREATE TEMP TABLE coach_proposal_changes (LIKE coach_proposal_changes INCLUDING ALL);
CREATE TEMP TABLE coach_decision_keys (LIKE coach_decision_keys INCLUDING ALL);
`); err != nil {
				return err
			}
			if seed == "" {
				return nil
			}
			_, err := tx.Exec(ctx, seed)
			return err
		})
	}
	pool, err := pgxpool.NewWithConfig(t.Context(), cfg)
	if err != nil {
		t.Fatal("open proposal fixture pool")
	}
	t.Cleanup(pool.Close)
	return pool
}

func TestProposalViewContract(t *testing.T) {
	seed, err := responseFixtures.ReadFile("testdata/views.sql")
	if err != nil {
		t.Fatal(err)
	}
	for _, zone := range []struct{ name, fixture string }{
		{"America/New_York", "views_new_york.json"},
		{"UTC", "views_utc.json"},
	} {
		t.Run(zone.name, func(t *testing.T) {
			pool := proposalPool(t, zone.name, string(seed))
			raw, err := responseFixtures.ReadFile("testdata/" + zone.fixture)
			if err != nil {
				t.Fatal(err)
			}
			var cases []struct {
				Path   string
				Status int
				Body   map[string]any
			}
			if err := json.Unmarshal(raw, &cases); err != nil {
				t.Fatal(err)
			}
			mux := http.NewServeMux()
			Handler{Store: drafts.Store{Pool: pool}, KBRoot: "../../../running_coach_kb", Mode: "test"}.Register(mux)
			for _, c := range cases {
				t.Run(strings.TrimPrefix(c.Path, prefix), func(t *testing.T) {
					checkProposalResponse(t, mux, http.MethodGet, c.Path, "", c.Status, c.Body, "")
				})
			}
		})
	}
}

func checkProposalResponse(t *testing.T, mux *http.ServeMux, method, path, body string, status int, expected map[string]any, proposalID string) {
	t.Helper()
	w := httptest.NewRecorder()
	w.Header().Set("X-Request-ID", "synthetic-request")
	mux.ServeHTTP(w, httptest.NewRequest(method, path, strings.NewReader(body)))
	var got map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if problem, ok := got["error"].(map[string]any); ok {
		if problem["request_id"] != "synthetic-request" {
			t.Errorf("error request_id = %v", problem["request_id"])
		}
		delete(problem, "request_id")
	}
	if proposalID != "" {
		if data, ok := got["data"].(map[string]any); ok && data["proposal_id"] == proposalID {
			data["proposal_id"] = "ID"
		}
	}
	if w.Code != status || !reflect.DeepEqual(expected, got) {
		t.Errorf("%s %s: got %d %s, want %d %v", method, path, w.Code, w.Body.Bytes(), status, expected)
	}
}

func TestProposalCommandContract(t *testing.T) {
	now := time.Date(2026, 11, 16, 15, 0, 0, 0, time.UTC)
	const kbRoot = "../../../running_coach_kb"
	ctx := t.Context()
	pool := proposalPool(t, "UTC", "UPDATE app_state SET data_revision=0,calendar_head_version=0 WHERE id=1")
	var packet map[string]any
	err := pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
		var err error
		packet, err = snapshots.BuildWithPreparation(ctx, tx, "proceed_or_modify_today", now.Format(time.DateOnly), now, kbRoot,
			func(context.Context, pgx.Tx, string, string, time.Time) error { return nil })
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	snapshot, ok := packet["snapshot_id"].(string)
	if !ok || snapshot == "" {
		t.Fatal("missing native snapshot ID")
	}
	raw, err := responseFixtures.ReadFile("testdata/commands.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Method, Path string
		Body         json.RawMessage
		Status       int
		Expected     map[string]any
	}
	wire := strings.NewReplacer("@SNAPSHOT@", snapshot, "@DAY@", now.Format(time.DateOnly)).Replace(string(raw))
	if err := json.Unmarshal([]byte(wire), &cases); err != nil {
		t.Fatal(err)
	}
	store := drafts.Store{Pool: pool}
	mux := http.NewServeMux()
	Handler{Store: store, KBRoot: kbRoot, Mode: "test", Now: func() time.Time { return now }}.Register(mux)
	validator := drafts.NewValidator(kbRoot)
	id := ""
	for i, c := range cases {
		if c.Path == "" {
			// Only the coaching CLI publishes a new pending draft.
			res, err := store.Submit(ctx, c.Body, now, validator)
			if err != nil || res.Status != "pending" || res.Revision != 1 || len(res.Issues) != 0 {
				t.Fatalf("step %d publish: %+v, %v", i, res, err)
			}
			if i == 1 && res.ID.String() != id {
				t.Fatalf("step %d repeated publish changed proposal %s to %s", i, id, res.ID)
			}
			if i > 1 && res.ID.String() == id {
				t.Fatalf("step %d new publication reused decided proposal %s", i, id)
			}
			id = res.ID.String()
			if i == 0 {
				var authored map[string]any
				if err := json.Unmarshal(c.Body, &authored); err != nil {
					t.Fatal(err)
				}
				checkProposalResponse(t, mux, http.MethodGet, prefix+"/"+id+"/document", "", http.StatusOK, map[string]any{
					"schema_version": "v1", "mode": "test", "data_revision": float64(0),
					"data": map[string]any{"proposal_id": "ID", "revision": float64(1), "status": "pending", "is_current": true, "document": authored},
				}, id)
			}
			continue
		}
		t.Run(c.Method+" "+c.Path, func(t *testing.T) {
			checkProposalResponse(t, mux, c.Method, prefix+strings.ReplaceAll(c.Path, "ID", id), string(c.Body), c.Status, c.Expected, id)
		})
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
