package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/netip"
	"os"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/goals"
	"github.com/mtang08/going-bananas/backend-go/internal/httpapi"
	"github.com/mtang08/going-bananas/backend-go/internal/proposals"
	"github.com/oapi-codegen/runtime"
)

func runtimeConfig(mode api.AppMode, dsn string) (*pgxpool.Config, error) {
	if mode != api.Test && mode != api.Demo {
		return nil, errors.New("APP_MODE must select test or demo")
	}
	if dsn == "" {
		return nil, errors.New("DATABASE_URL is required")
	}
	dsn = strings.Replace(dsn, "postgresql+psycopg://", "postgresql://", 1)
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return nil, errors.New("invalid DATABASE_URL")
	}
	if !strings.HasSuffix(cfg.ConnConfig.Database, "_"+string(mode)) {
		return nil, errors.New("database name must end in the selected synthetic mode suffix")
	}
	cfg.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	return cfg, nil
}

func serve(args []string) error {
	flags := flag.NewFlagSet("serve", flag.ContinueOnError)
	address := flags.String("listen", "127.0.0.1:8011", "loopback IPv4 address and port")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return errors.New("unexpected serve arguments")
	}
	addr, err := netip.ParseAddrPort(*address)
	if err != nil || addr.Addr().String() != "127.0.0.1" {
		return errors.New("listen address must be 127.0.0.1 with a numeric port")
	}
	mode := api.AppMode(os.Getenv("APP_MODE"))
	cfg, err := runtimeConfig(mode, os.Getenv("DATABASE_URL"))
	if err != nil {
		return err
	}
	ctx := context.Background()
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return errors.New("unable to open synthetic database pool")
	}
	defer pool.Close()
	if err := pool.Ping(ctx); err != nil {
		return errors.New("unable to connect to synthetic database")
	}
	l, err := net.Listen("tcp4", addr.String())
	if err != nil {
		return err
	}
	defer func() { _ = l.Close() }()
	_, port, err := net.SplitHostPort(l.Addr().String())
	if err != nil {
		return err
	}
	vitePort := os.Getenv("VITE_PORT")
	if vitePort == "" {
		vitePort = "5173"
	}
	h := httpapi.New(proposals.New(pool), goals.New(pool), mode, port, vitePort)
	srv := &http.Server{Handler: h, ReadHeaderTimeout: 5 * time.Second}
	fmt.Println(l.Addr())
	return srv.Serve(l)
}

// Match the compact FastAPI JSON body for generated responses.
type compactJSON struct{ runtime.StdJSONCodec }

func main() {
	runtime.SetJSONCodec(compactJSON{})
	if len(os.Args) < 2 || os.Args[1] != "serve" {
		log.Fatal("usage: going-bananas serve [-listen 127.0.0.1:8011]")
	}
	if err := serve(os.Args[2:]); err != nil {
		log.Fatal(err)
	}
}
