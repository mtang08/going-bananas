// Command import-export previews a local Garmin account export and optionally imports it.
package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/mtang08/going-bananas/backend-go/internal/exportcli"
	"github.com/mtang08/going-bananas/backend-go/internal/garmincli"
	"github.com/mtang08/going-bananas/backend-go/internal/metrics/refresh"
)

func main() {
	os.Exit(run())
}

func run() int {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	return exportcli.Command(ctx, os.Args[1:], os.Stdout, os.Stderr, garmincli.SourceRefresh(time.Now, refresh.Runs))
}
