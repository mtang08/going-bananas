// Package exportcommand previews a local Garmin account export and optionally imports it.
package exportcommand

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

func Main(args []string) int {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	return exportcli.Command(ctx, args, os.Stdout, os.Stderr, garmincli.SourceRefresh(time.Now, refresh.Runs))
}
