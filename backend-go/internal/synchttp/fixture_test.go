package synchttp

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
	"iter"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"testing"
	"time"
)

type fixtureSource struct{ dir string }

func (s fixtureSource) Pages(_ context.Context, _, _ time.Time, _, _ int) iter.Seq2[garmin.Page, error] {
	return func(yield func(garmin.Page, error) bool) {
		b, err := os.ReadFile(filepath.Join(s.dir, "row.json"))
		var row garmin.Record
		if err == nil {
			dec := json.NewDecoder(bytes.NewReader(b))
			dec.UseNumber()
			err = dec.Decode(&row)
		}
		yield(garmin.Page{Records: []garmin.Record{row}}, err)
	}
}
func (s fixtureSource) DownloadActivity(context.Context, string) ([]byte, error) {
	if b, err := os.ReadFile(filepath.Join(s.dir, "download_status")); err == nil {
		code, err := strconv.Atoi(string(b))
		if err != nil {
			return nil, err
		}
		return nil, &garmin.RemoteError{StatusCode: code}
	}
	return os.ReadFile(filepath.Join(s.dir, "synthetic.zip"))
}
func TestHTTPFixture(t *testing.T) {
	if os.Getenv("SYNC_HTTP_FIXTURE") != "1" {
		t.Skip("requires migrated schemas")
	}
	c, err := pgxpool.ParseConfig(os.Getenv("PROPOSAL_TEST_DATABASE_URL"))
	if err != nil || c.ConnConfig.Database != "garmin_test" || (c.ConnConfig.Host != "localhost" && c.ConnConfig.Host != "127.0.0.1") || os.Getenv("APP_MODE") != "test" || fmt.Sprint(c.ConnConfig.Port) != os.Getenv("TEST_DATABASE_PORT") {
		t.Fatal("expected synthetic database")
	}
	c.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	pool, err := pgxpool.NewWithConfig(t.Context(), c)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var schema string
	if err := pool.QueryRow(t.Context(), "SELECT current_schema()").Scan(&schema); err != nil || !regexp.MustCompile("^go_parity_[0-9a-f]{32}$").MatchString(schema) {
		t.Fatal("expected disposable sync schema")
	}
	h := New(pool, os.Getenv("SYNC_ROUTE_MODE"), os.Getenv("PRIVATE_DIR"))
	h.Now = func() time.Time { return time.Date(2026, 11, 16, 9, 0, 0, 0, time.UTC) }
	h.OpenSource = func(context.Context) (Source, error) { return fixtureSource{h.PrivateDir}, nil }
	mux := http.NewServeMux()
	h.Register(mux)
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	fmt.Println(listener.Addr().(*net.TCPAddr).Port)
	server := http.Server{Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	if err := server.Serve(listener); err != nil {
		t.Fatal(err)
	}
}
