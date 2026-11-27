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
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/api"
	"github.com/mtang08/going-bananas/backend-go/internal/backupcli"
	"github.com/mtang08/going-bananas/backend-go/internal/calendarcli"
	"github.com/mtang08/going-bananas/backend-go/internal/coachcli"
	"github.com/mtang08/going-bananas/backend-go/internal/exportcommand"
	"github.com/mtang08/going-bananas/backend-go/internal/fitcommand"
	"github.com/mtang08/going-bananas/backend-go/internal/health"
	"github.com/mtang08/going-bananas/backend-go/internal/metriccli"
	"github.com/mtang08/going-bananas/backend-go/internal/migratecli"
	"github.com/mtang08/going-bananas/backend-go/internal/strongcli"
	"github.com/mtang08/going-bananas/backend-go/internal/workercommand"
	"github.com/oapi-codegen/runtime"
)

func runtimeConfig(mode api.AppMode, dsn string) (*pgxpool.Config, error) {
	if mode == api.Real && os.Getenv("GOING_BANANAS_BACKEND") != "go" {
		return nil, errors.New("real mode requires the configured Go backend")
	}
	if mode != api.Test && mode != api.Demo && mode != api.Real {
		return nil, errors.New("APP_MODE must select test, demo or real")
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
		return nil, errors.New("database name must end in the selected mode suffix")
	}
	cfg.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	return cfg, nil
}

func serve(args []string) error {
	flags := flag.NewFlagSet("serve", flag.ContinueOnError)
	startup := flags.Bool("startup", false, "refresh athlete-local windows and prompts before serving")
	repo := flags.String("repo", os.Getenv("GB_MODE_ROOT"), "repository root containing running_coach_kb")
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
		return errors.New("unable to open database pool")
	}
	defer pool.Close()
	if err := pool.Ping(ctx); err != nil {
		return errors.New("unable to connect to database")
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
	root := *repo
	if root == "" {
		root, err = os.Getwd()
		if err != nil {
			return err
		}
		if filepath.Base(root) == "backend-go" {
			root = filepath.Dir(root)
		}
	}
	privateDir := os.Getenv("PRIVATE_DIR")
	dashboard, err := nativeDashboard(ctx, pool, mode, port, vitePort, root, privateDir)
	if err != nil {
		return fmt.Errorf("initialize coaching dashboard: %w", err)
	}
	if *startup {
		if _, err := health.Startup(ctx, pool, string(mode), privateDir, time.Now()); err != nil {
			log.Print("Startup metric refresh failed; metric pages compute on view until the next write.")
		}
	}
	dist := os.Getenv("FRONTEND_DIST")
	if dist == "" {
		dist = filepath.Join(root, "frontend", "dist")
	}
	h := applicationHandler(pool, mode, port, vitePort, root, privateDir, dist, dashboard)
	srv := &http.Server{Handler: h, ReadHeaderTimeout: 5 * time.Second}
	fmt.Println(l.Addr())
	shutdown, stop := signal.NotifyContext(ctx, os.Interrupt, syscall.SIGTERM)
	defer stop()
	done := make(chan error, 1)
	go func() { done <- srv.Serve(l) }()
	select {
	case err = <-done:
	case <-shutdown.Done():
		closing, cancel := context.WithTimeout(ctx, 10*time.Second)
		err = srv.Shutdown(closing)
		cancel()
	}
	drain, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	return errors.Join(err, dashboard.Shutdown(drain))
}

// Match the compact FastAPI JSON body for generated responses.
type compactJSON struct{ runtime.StdJSONCodec }

func main() {
	runtime.SetJSONCodec(compactJSON{})
	if len(os.Args) < 2 {
		log.Fatal("usage: going-bananas COMMAND [arguments]")
	}
	args := os.Args[1:]
	switch args[0] {
	case "serve":
		if err := serve(args[1:]); err != nil {
			log.Fatal(err)
		}
	case "worker", "sync":
		os.Exit(workercommand.Main(args))
	case "fit-backfill", "fit-reprocess":
		os.Exit(fitcommand.Main(args))
	case "calendar-connect", "calendar-probe":
		os.Exit(calendarcli.Main(args))
	case "backup", "restore":
		os.Exit(backupcli.Main(args))
	case "migrate":
		os.Exit(migratecli.Main(args[1:]))
	case "strong-import":
		os.Exit(strongcli.Main(args[1:]))
	case "import-export":
		os.Exit(exportcommand.Main(args[1:]))
	case "metrics-recompute", "metrics-assess-session", "metrics-refresh-today":
		os.Exit(metriccli.Main(args))
	case "coach":
		os.Exit(coachcli.Main(args[1:]))
	default:
		log.Fatal("unknown command")
	}
}
