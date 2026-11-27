package checkinhttp

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"regexp"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/checkins"
	"github.com/mtang08/going-bananas/backend-go/internal/exceptions"
	"github.com/mtang08/going-bananas/backend-go/internal/phonegateway"
)

func TestCheckinParityServer(t *testing.T) {
	if os.Getenv("CHECKIN_HTTP_FIXTURE") == "" {
		t.Skip("run scripts/test-db.py phone-checkins")
	}
	cfg, err := pgxpool.ParseConfig(os.Getenv("PROPOSAL_TEST_DATABASE_URL"))
	if err != nil || os.Getenv("APP_MODE") != "test" || cfg.ConnConfig.Database != "garmin_test" || (cfg.ConnConfig.Host != "127.0.0.1" && cfg.ConnConfig.Host != "localhost") || fmt.Sprint(cfg.ConnConfig.Port) != os.Getenv("TEST_DATABASE_PORT") || !regexp.MustCompile(`^-csearch_path=go_parity_[0-9a-f]{32} -cTimeZone=Asia/Kathmandu$`).MatchString(os.Getenv("PGOPTIONS")) {
		t.Fatal("expected disposable test schema")
	}
	pool, err := pgxpool.NewWithConfig(t.Context(), cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()
	var schema string
	if err := pool.QueryRow(t.Context(), "SELECT current_schema()").Scan(&schema); err != nil || !regexp.MustCompile(`^go_parity_[0-9a-f]{32}$`).MatchString(schema) {
		t.Fatal("invalid comparison schema")
	}
	s := checkins.Store{Pool: pool, Refresh: func(ctx context.Context, tx pgx.Tx, scopes []string) error {
		_, err := tx.Exec(ctx, "INSERT INTO fixture_hooks(kind,scopes) VALUES ('refresh',$1)", scopes)
		return err
	}, Detect: func(ctx context.Context, tx pgx.Tx, now time.Time) (checkins.Detection, error) {
		_, err := tx.Exec(ctx, "INSERT INTO fixture_hooks(kind) VALUES ('detect')")
		if err != nil {
			return nil, err
		}
		result, err := exceptions.Detect(ctx, tx, now)
		if err != nil {
			fmt.Fprintln(os.Stderr, "synthetic detector:", err)
		}
		return result, err
	}}
	if fixed := os.Getenv("CHECKIN_REFRESH_CLOCK"); fixed != "" {
		stamp, err := time.Parse(time.RFC3339, fixed)
		if err != nil {
			t.Fatal(err)
		}
		s = checkins.NewStore(pool, func() time.Time { return stamp }, nil)
	}
	api, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	gateway, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	mux := http.NewServeMux()
	Handler{Store: s, Mode: "test"}.Register(mux)
	server := &http.Server{Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	defer func() { _ = server.Close() }()
	go func() { _ = server.Serve(api) }()
	access := phonegateway.Access{Host: "synthetic.ts.net:8444", Login: "athlete@example.invalid", Mode: "test", APIPort: api.Addr().(*net.TCPAddr).Port}
	proxy := &http.Server{Handler: phonegateway.Gateway{Access: access, Assets: os.DirFS(os.Getenv("PHONE_FIXTURE_ASSETS"))}, ReadHeaderTimeout: 5 * time.Second}
	fmt.Printf("%d %d\n", access.APIPort, gateway.Addr().(*net.TCPAddr).Port)
	if err := proxy.Serve(gateway); err != nil && !errors.Is(err, http.ErrServerClosed) {
		t.Fatal(err)
	}
}
