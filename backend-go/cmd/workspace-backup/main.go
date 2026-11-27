// Command workspace-backup creates or restores a version-one private workspace archive.
package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/mtang08/going-bananas/backend-go/internal/backup"
)

func main() {
	os.Exit(run())
}

func run() int {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	return backup.RunCommand(ctx, os.Args[1:], os.Stdout, os.Stderr)
}
