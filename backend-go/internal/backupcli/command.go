// Package backupcli creates or restores a version-one private workspace archive.
package backupcli

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/mtang08/going-bananas/backend-go/internal/backup"
)

func Main(args []string) int {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	return backup.RunCommand(ctx, args, os.Stdout, os.Stderr)
}
