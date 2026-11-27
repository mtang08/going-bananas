// Package exportcli implements the import-export subcommand.
package exportcli

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/replay"
)

func Run(ctx context.Context, pool *pgxpool.Pool, privateDir, mode string, args []string, stdout io.Writer) error {
	if mode != "real" {
		return errors.New("real_mode_required")
	}
	archive := ""
	apply := false
	flags := true
	for _, arg := range args {
		switch {
		case flags && arg == "--":
			flags = false
		case flags && arg == "--apply":
			apply = true
		case flags && strings.HasPrefix(arg, "-"):
			return errors.New("usage: import-export ARCHIVE [--apply]")
		default:
			if archive != "" {
				return errors.New("usage: import-export ARCHIVE [--apply]")
			}
			archive = arg
		}
	}
	if archive == "" {
		return errors.New("usage: import-export ARCHIVE [--apply]")
	}
	result, err := replay.ImportExport(ctx, pool, privateDir, archive, apply)
	if err != nil {
		return err
	}
	return json.NewEncoder(stdout).Encode(result)
}
