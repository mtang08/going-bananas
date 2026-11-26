package travelhttp

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/travel"
)

type fixtureCalendar struct{ dir string }

func (p fixtureCalendar) Connected() bool {
	_, err := os.Stat(filepath.Join(p.dir, "connected"))
	return err == nil
}

func (p fixtureCalendar) Fetch(_ context.Context, _ travel.Window) ([]json.RawMessage, error) {
	data, err := os.ReadFile(filepath.Join(p.dir, "delivery.json"))
	if err != nil {
		return nil, err
	}
	var delivery struct {
		Error string
		Pages []json.RawMessage
	}
	if err := json.Unmarshal(data, &delivery); err != nil {
		return nil, err
	}
	if delivery.Error != "" {
		return nil, &travel.ProviderError{Code: delivery.Error}
	}
	return delivery.Pages, nil
}

// TestParityServer is a loopback-only adapter for scripts/test-db.py travel-http.
func TestParityServer(t *testing.T) {
	mode := os.Getenv("TRAVEL_HTTP_FIXTURE_MODE")
	if mode == "" {
		t.Skip("run via the travel-http PostgreSQL comparison")
	}
	if (mode != "test" && mode != "real") || os.Getenv("APP_MODE") != "test" {
		t.Fatal("expected a synthetic test workspace")
	}
	config, err := pgxpool.ParseConfig(os.Getenv("PROPOSAL_TEST_DATABASE_URL"))
	if err != nil || config.ConnConfig.Database != "garmin_test" || config.ConnConfig.Host != "127.0.0.1" && config.ConnConfig.Host != "localhost" ||
		fmt.Sprint(config.ConnConfig.Port) != os.Getenv("TEST_DATABASE_PORT") ||
		!regexp.MustCompile(`^-csearch_path=go_parity_[0-9a-f]{32} -cTimeZone=Asia/Kathmandu -cdefault_transaction_read_only=on$`).MatchString(os.Getenv("PGOPTIONS")) {
		t.Fatal("expected a disposable local comparison schema")
	}
	pool, err := pgxpool.NewWithConfig(t.Context(), config)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var schema string
	if err := pool.QueryRow(t.Context(), "SELECT current_schema()").Scan(&schema); err != nil || !strings.HasPrefix(schema, "go_parity_") {
		t.Fatal("comparison schema is not active")
	}
	dir := os.Getenv("PRIVATE_DIR")
	h := Handler{Pool: pool, Mode: mode, PrivateDir: dir, Provider: fixtureCalendar{dir}, Now: func() time.Time {
		data, err := os.ReadFile(filepath.Join(dir, "now"))
		if err != nil {
			panic(err)
		}
		stamp, err := time.Parse(time.RFC3339, string(data))
		if err != nil {
			panic(err)
		}
		return stamp
	}}
	mux := http.NewServeMux()
	h.Register(mux)
	socket, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = socket.Close() }()
	fmt.Println(socket.Addr())
	server := &http.Server{Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	if err := server.Serve(socket); err != nil && err != http.ErrServerClosed {
		t.Fatal(err)
	}
}
