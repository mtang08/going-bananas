package backup

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"os"
	"strings"

	"github.com/mtang08/going-bananas/backend-go/internal/clisettings"
)

// RunCommand processes a backup or restore CLI invocation.
func RunCommand(ctx context.Context, args []string, stdout, stderr io.Writer) int {
	if err := runCommand(ctx, args, stdout); err != nil {
		_ = json.NewEncoder(stderr).Encode(map[string]string{"error": err.Error()})
		return 2
	}
	return 0
}

func runCommand(ctx context.Context, args []string, stdout io.Writer) error {
	cfg, err := clisettings.Load()
	if err != nil {
		return err
	}
	var manifest Manifest
	var key string
	switch {
	case len(args) == 2 && args[0] == "backup":
		manifest, err = Create(ctx, cfg.DSN, cfg.PrivateDir, args[1])
		key = "created_at"
	case len(args) > 0 && args[0] == "restore":
		archive, target, private, ok := restoreArgs(args[1:])
		if !ok {
			return errUsage
		}
		manifest, err = Restore(ctx, cfg.DSN, archive, target, private)
		key = "restored_at"
	default:
		return errUsage
	}
	if err != nil {
		var pathErr *os.PathError
		if errors.As(err, &pathErr) {
			return errors.New("backup_filesystem_error")
		}
		return err
	}
	return json.NewEncoder(stdout).Encode(map[string]any{key: manifest.Created, "file_count": len(manifest.Files)})
}

var errUsage = errors.New("expected backup OUTPUT or restore ARCHIVE --target-database-name NAME --target-private-dir DIR")

func restoreArgs(args []string) (archive, target, private string, ok bool) {
	for len(args) > 0 {
		arg := args[0]
		args = args[1:]
		flag, value, hasValue := strings.Cut(arg, "=")
		var dest *string
		switch flag {
		case "--target-database-name":
			dest = &target
		case "--target-private-dir":
			dest = &private
		default:
			if archive != "" || strings.HasPrefix(arg, "--") {
				return "", "", "", false
			}
			archive = arg
			continue
		}
		if !hasValue {
			if len(args) == 0 || strings.HasPrefix(args[0], "--") {
				return "", "", "", false
			}
			value, args = args[0], args[1:]
		}
		*dest = value
	}
	return archive, target, private, archive != "" && target != "" && private != ""
}
