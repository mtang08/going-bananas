package preflight

import (
	"context"
	"encoding/json"
	"flag"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// Main returns a redacted receipt and exits successfully only for a ready workspace.
func Main(args []string) int {
	flags := flag.NewFlagSet("workspace-preflight", flag.ContinueOnError)
	defaultRepo := os.Getenv("GB_REPO")
	if defaultRepo == "" {
		defaultRepo = "."
	}
	repo := flags.String("repo", defaultRepo, "repository root containing running_coach_kb")
	if err := flags.Parse(args); err != nil {
		return 2
	}
	r := Report{Checks: map[string]string{"workspace": "failed"}}
	mode, dir := os.Getenv("APP_MODE"), os.Getenv("PRIVATE_DIR")
	cfg, err := pgx.ParseConfig(strings.Replace(os.Getenv("DATABASE_URL"), "postgresql+psycopg://", "postgresql://", 1))
	if flags.NArg() == 0 && (mode == "real" || mode == "test" || mode == "demo") && dir != "" && os.Getenv("DATABASE_URL") != "" && err == nil && strings.HasSuffix(cfg.Database, "_"+mode) {
		cfg.RuntimeParams["default_transaction_read_only"] = "on"
		ctx := context.Background()
		conn, err := pgx.ConnectConfig(ctx, cfg)
		if err == nil {
			r, _ = Check(ctx, conn, dir, filepath.Join(*repo, "running_coach_kb"), time.Now().UTC())
			_ = conn.Close(ctx)
		}
	}
	_ = json.NewEncoder(os.Stdout).Encode(r)
	if !r.Ready {
		return 1
	}
	return 0
}
