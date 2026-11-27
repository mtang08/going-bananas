package health

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

func TestHeadTracksAlembic(t *testing.T) {
	reference, err := os.ReadFile("../../../backend/app/migrations_head.py")
	if err != nil || !strings.Contains(string(reference), "EXPECTED_HEAD = "+strconv.Quote(expectedHead)) {
		t.Fatal("update native readiness for the current migration head", err)
	}
}

func probe(t *testing.T, mux *http.ServeMux, path string, status, revision int, want string) {
	t.Helper()
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/health/"+path, nil))
	var response struct {
		Mode     string
		Revision int    `json:"data_revision"`
		Version  string `json:"schema_version"`
		Data     map[string]any
	}
	if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	if w.Code != status || response.Revision != revision || response.Version != "v1" || response.Mode != "test" || response.Data["status"] != want || len(response.Data) != 2 {
		t.Fatalf("%s %d %s", path, w.Code, w.Body.String())
	}
	if path == "live" && response.Data["dashboard_coach"] != true || path == "ready" && response.Data["database"] != (status == 200) {
		t.Fatalf("invalid flags %v", response.Data)
	}
}

func TestLivenessWithoutDatabase(t *testing.T) {
	mux := http.NewServeMux()
	Handler{Mode: "test"}.Register(mux)
	probe(t, mux, "live", 200, 0, "ok")
}

func TestStartupAndReadiness(t *testing.T) {
	oracle := os.Getenv("HEALTH_EXPECT_NEW")
	if oracle == "" {
		t.Skip("run health-startup database comparison")
	}
	if os.Getenv("APP_MODE") != "test" || !strings.HasPrefix(os.Getenv("PGOPTIONS"), "-csearch_path=go_parity_") {
		t.Fatal("requires a synthetic schema")
	}
	cfg, err := pgxpool.ParseConfig(os.Getenv("PROPOSAL_TEST_DATABASE_URL"))
	if err != nil || cfg.ConnConfig.Database != "garmin_test" {
		t.Fatal("requires isolated test database")
	}
	ctx := t.Context()
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	exec := func(sql string) {
		t.Helper()
		if _, err := pool.Exec(ctx, sql); err != nil {
			t.Fatal(err)
		}
	}
	mux := http.NewServeMux()
	Handler{Pool: pool, Mode: "test"}.Register(mux)
	exec("UPDATE app_state SET data_revision=17 WHERE id=1")
	probe(t, mux, "ready", 200, 17, "ok")
	now := time.Date(2026, 11, 23, 2, 0, 0, 0, time.UTC)
	exec("CREATE FUNCTION fail_startup() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test metric failure'; END $$; CREATE TRIGGER fail_startup BEFORE INSERT ON metric_results FOR EACH ROW EXECUTE FUNCTION fail_startup()")
	if _, err = Startup(ctx, pool, "test", "", now); err == nil {
		t.Fatal("expected injected failure")
	}
	var count int
	if err = pool.QueryRow(ctx, "SELECT count(*) FROM metric_results").Scan(&count); err != nil || count != 0 {
		t.Fatal(count, err)
	}
	exec("DROP TRIGGER fail_startup ON metric_results")
	cfg.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	reads, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer reads.Close()
	n, err := strconv.Atoi(oracle)
	if err != nil || n < 1 {
		t.Fatal(oracle)
	}
	for _, expected := range []int{n, 0} {
		result, err := Startup(ctx, reads, "test", "", now)
		if err != nil || result.AsOf != "2026-11-22" || result.NewResults != expected {
			t.Fatalf("%+v %v expected %d", result, err, expected)
		}
	}
	for _, sql := range []string{"INSERT INTO alembic_version VALUES('stale')", "DELETE FROM alembic_version WHERE version_num<>'stale'", "DELETE FROM alembic_version", "DROP TABLE alembic_version"} {
		exec(sql)
		probe(t, mux, "ready", 503, 0, "unavailable")
	}
	pool.Close()
	probe(t, mux, "ready", 503, 0, "unavailable")
	probe(t, mux, "live", 200, 0, "ok")
}
