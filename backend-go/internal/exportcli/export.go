// Package exportcli implements the import-export subcommand.
package exportcli

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/clisettings"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/replay"
)

const usage = "usage: going-bananas import-export [-h] [--apply] archive"

type options struct {
	archive string
	apply   bool
	help    bool
}

func parse(args []string) (options, error) {
	var opts options
	var extras []string
	hasArchive, flags := false, true
	for _, arg := range args {
		switch {
		case flags && arg == "--":
			flags = false
		case flags && (arg == "-h" || arg == "--h" || arg == "--he" || arg == "--hel" || arg == "--help"):
			opts.help = true
			return opts, nil
		case flags && (arg == "--a" || arg == "--ap" || arg == "--app" || arg == "--appl" || arg == "--apply"):
			opts.apply = true
		case flags && strings.HasPrefix(arg, "--apply="):
			return opts, fmt.Errorf("argument --apply: ignored explicit argument '%s'", strings.TrimPrefix(arg, "--apply="))
		case flags && strings.HasPrefix(arg, "-") && arg != "-":
			extras = append(extras, arg)
		case hasArchive:
			extras = append(extras, arg)
		default:
			hasArchive = true
			opts.archive = filepath.Clean(arg)
		}
	}
	if !hasArchive {
		return opts, errors.New("the following arguments are required: archive")
	}
	if len(extras) != 0 {
		return opts, fmt.Errorf("unrecognized arguments: %s", strings.Join(extras, " "))
	}
	return opts, nil
}

// Command runs the standalone or unified import-export command.
func Command(ctx context.Context, args []string, stdout, stderr io.Writer, refresh replay.Refresh) int {
	cfg, err := clisettings.Load()
	if err != nil {
		return report(stderr, err.Error())
	}
	opts, err := parse(args)
	if err != nil {
		_, _ = fmt.Fprintln(stderr, usage)
		_, _ = fmt.Fprintf(stderr, "going-bananas import-export: error: %s\n", err)
		return 2
	}
	if opts.help {
		_, _ = fmt.Fprintln(stdout, usage+"\n\npositional arguments:\n  archive\n\noptions:\n  -h, --help  show this help message and exit\n  --apply")
		return 0
	}
	if cfg.Mode != "real" {
		return report(stderr, "real_mode_required")
	}
	poolCfg, err := pgxpool.ParseConfig(cfg.DSN)
	if err != nil || !strings.HasSuffix(poolCfg.ConnConfig.Database, "_real") {
		return report(stderr, "invalid_real_database")
	}
	pool, err := pgxpool.NewWithConfig(ctx, poolCfg)
	if err != nil {
		return report(stderr, "cannot_open_database")
	}
	defer pool.Close()
	if err := execute(ctx, pool, cfg.PrivateDir, opts, stdout, refresh); err != nil {
		return report(stderr, errorCode(err))
	}
	return 0
}

func report(stderr io.Writer, code string) int {
	_ = json.NewEncoder(stderr).Encode(map[string]string{"error": code})
	return 2
}

func errorCode(err error) string {
	var pathErr *os.PathError
	if errors.As(err, &pathErr) {
		return "invalid_export_archive"
	}
	code := err.Error()
	switch code {
	case "archive_compression_ratio", "archive_copy_mismatch", "archive_crc_mismatch",
		"archive_member_size_mismatch", "archive_member_too_large", "archive_too_large",
		"archive_too_many_entries", "activity_member_count", "duplicate_activity_id",
		"empty_activity_export", "encrypted_archive_entry", "export_refresh_required",
		"invalid_activity_identity", "invalid_activity_json", "invalid_activity_record",
		"invalid_activity_schema", "invalid_activity_start", "invalid_activity_type",
		"invalid_export_archive", "invalid_recovery_array", "invalid_recovery_json",
		"mixed_activity_owner", "mixed_source_account", "unsafe_archive_entry", "unsafe_archive_path":
		return code
	}
	return "import_export_failed"
}

func Run(ctx context.Context, pool *pgxpool.Pool, privateDir, mode string, args []string, stdout io.Writer, refresh replay.Refresh) error {
	opts, err := parse(args)
	if err != nil {
		return err
	}
	if mode != "real" {
		return errors.New("real_mode_required")
	}
	return execute(ctx, pool, privateDir, opts, stdout, refresh)
}

func execute(ctx context.Context, pool *pgxpool.Pool, privateDir string, opts options, stdout io.Writer, refresh replay.Refresh) error {
	if opts.apply && refresh == nil {
		return errors.New("export_refresh_required")
	}
	result, err := replay.ImportExport(ctx, pool, privateDir, opts.archive, opts.apply, refresh)
	if err != nil {
		return err
	}
	return json.NewEncoder(stdout).Encode(result)
}
