// Package backupcli creates or restores a version-one private workspace archive.
package backupcli

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/mtang08/going-bananas/backend-go/internal/backup"
)

func run(ctx context.Context, args []string) error {
	var m backup.Manifest
	var err error
	var key string
	dsn := os.Getenv("DATABASE_URL")
	switch {
	case len(args) == 2 && args[0] == "backup":
		m, err = backup.Create(ctx, dsn, os.Getenv("PRIVATE_DIR"), args[1])
		key = "created_at"
	case len(args) == 6 && args[0] == "restore":
		opts := map[string]string{args[2]: args[3], args[4]: args[5]}
		m, err = backup.Restore(ctx, dsn, args[1], opts["--target-database-name"], opts["--target-private-dir"])
		key = "restored_at"
	default:
		return errors.New("expected backup OUTPUT or restore ARCHIVE --target-database-name NAME --target-private-dir DIR")
	}
	if err != nil {
		var pathErr *os.PathError
		if errors.As(err, &pathErr) {
			return errors.New("backup_filesystem_error")
		}
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{key: m.Created, "file_count": len(m.Files)})
}

func Main(args []string) int {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	if err := run(ctx, args); err != nil {
		msg, _ := json.Marshal(map[string]string{"error": err.Error()})
		fmt.Fprintln(os.Stderr, string(msg))
		return 2
	}
	return 0
}
