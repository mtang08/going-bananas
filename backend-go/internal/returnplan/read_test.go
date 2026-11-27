package returnplan

import (
	"context"
	_ "embed"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/testpg"
)

//go:embed testdata/seed.sql
var seed string

// The saved responses cover the same calendar across return windows and athlete restrictions.
func TestReturnPlanHTTPContract(t *testing.T) {
	cfg := testpg.DashboardConfig(t)
	ctx := t.Context()
	ref, err := os.ReadFile("testdata/expected.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Day      string
		Facts    json.RawMessage
		Expected object
	}
	if err = json.Unmarshal(ref, &cases); err != nil {
		t.Fatal(err)
	}
	cfg.MaxConns = 1
	cfg.AfterConnect = func(ctx context.Context, conn *pgx.Conn) error {
		if err := testpg.CheckDashboardSchema(ctx, conn); err != nil {
			return err
		}
		return pgx.BeginTxFunc(ctx, conn, pgx.TxOptions{AccessMode: pgx.ReadWrite}, func(tx pgx.Tx) error {
			_, err := tx.Exec(ctx, seed)
			return err
		})
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	for _, c := range cases {
		if _, err := pool.Exec(ctx, "UPDATE profile_versions SET facts=$1", c.Facts); err != nil {
			t.Fatal(err)
		}
		day, err := time.Parse(time.DateOnly, c.Day)
		if err != nil {
			t.Fatal(err)
		}
		// Before UTC dawn tomorrow it is still the requested date for this athlete.
		h := Handler{Pool: pool, Mode: "test", Now: func() time.Time { return day.Add(26 * time.Hour) }}
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/running-interruption", nil))
		var response struct {
			Data     object
			Mode     string
			Revision int `json:"data_revision"`
		}
		if err := json.Unmarshal(rec.Body.Bytes(), &response); err != nil {
			t.Fatal(err)
		}
		if rec.Code != 200 || response.Mode != "test" || response.Revision != 11 || !reflect.DeepEqual(response.Data, c.Expected) {
			t.Fatalf("day %s: status %d; got %v; want %v", c.Day, rec.Code, response, c.Expected)
		}
	}
}
