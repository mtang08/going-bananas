// Package strongcli previews a local Strong CSV. Pass -apply to import it.
package strongcli

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/strong"
)

func options(args []string) (path string, apply bool, err error) {
	// The established CLI accepts FILE --apply as well as --apply FILE.
	if len(args) == 2 && !strings.HasPrefix(args[0], "-") && (args[1] == "--apply" || args[1] == "-apply") {
		args = []string{args[1], args[0]}
	}
	flags := flag.NewFlagSet("strong-import", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	flags.BoolVar(&apply, "apply", false, "apply imported workouts to the selected workspace")
	if err := flags.Parse(args); err != nil || flags.NArg() != 1 {
		return "", false, errors.New("usage: strong-import [--apply] FILE.csv")
	}
	return flags.Arg(0), apply, nil
}
func run(args []string) error {
	path, apply, err := options(args)
	if err != nil {
		return err
	}
	mode, root := os.Getenv("APP_MODE"), os.Getenv("PRIVATE_DIR")
	if (mode != "demo" && mode != "test" && mode != "real") || root == "" {
		return errors.New("select an explicit real, test or demo workspace with PRIVATE_DIR")
	}
	dsn := strings.Replace(os.Getenv("DATABASE_URL"), "postgresql+psycopg://", "postgresql://", 1)
	if dsn == "" {
		return errors.New("DATABASE_URL is required")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil || !strings.HasSuffix(cfg.ConnConfig.Database, "_"+mode) {
		return errors.New("database name must match APP_MODE")
	}
	ctx := context.Background()
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return errors.New("cannot open selected database")
	}
	defer pool.Close()
	result, err := strong.Import(ctx, pool, root, path, apply)
	if err != nil {
		var safe strong.Error
		if errors.As(err, &safe) {
			return safe
		}
		return errors.New("strong_import_failed")
	}
	return json.NewEncoder(os.Stdout).Encode(result)
}
func Main(args []string) int {
	if err := run(args); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}
