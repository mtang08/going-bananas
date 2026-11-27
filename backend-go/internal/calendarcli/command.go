// Package calendarcli connects Google Calendar and probes its read-only event feed.
package calendarcli

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"runtime"
	"syscall"

	"github.com/mtang08/going-bananas/backend-go/internal/googlecalendar"
	"github.com/mtang08/going-bananas/backend-go/internal/travel"
)

func run(ctx context.Context, mode, dir string, args []string, out, diagnostic io.Writer) error {
	if mode != "real" {
		return errors.New("real_mode_required")
	}
	if len(args) == 0 {
		return errors.New("expected calendar-connect or calendar-probe")
	}
	c := googlecalendar.New(dir)
	flags := flag.NewFlagSet(args[0], flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	switch args[0] {
	case "calendar-connect":
		manual := flags.Bool("no-browser", false, "display the authorization URL")
		if flags.Parse(args[1:]) != nil || flags.NArg() != 0 {
			return errors.New("invalid_arguments")
		}
		err := c.Connect(ctx, func(link string) error {
			if *manual {
				_, err := fmt.Fprintln(diagnostic, "Open this authorization URL:", link)
				return err
			}
			tool := "xdg-open"
			if runtime.GOOS == "darwin" {
				tool = "open"
			}
			return exec.CommandContext(ctx, tool, link).Run()
		})
		if err != nil {
			return err
		}
		return json.NewEncoder(out).Encode(map[string]any{"connected": true, "scope": "calendar.readonly"})
	case "calendar-probe":
		days := flags.Int("days", 60, "days of primary calendar events to inspect")
		if flags.Parse(args[1:]) != nil || flags.NArg() != 0 {
			return errors.New("invalid_arguments")
		}
		lines, err := c.Probe(ctx, *days)
		if err != nil {
			return err
		}
		for _, line := range lines {
			if _, err := fmt.Fprintln(out, line); err != nil {
				return err
			}
		}
		return nil
	default:
		return errors.New("expected calendar-connect or calendar-probe")
	}
}
func Main(args []string) int {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	dir := os.Getenv("PRIVATE_DIR")
	if dir == "" {
		dir = "private"
	}
	err := run(ctx, os.Getenv("APP_MODE"), dir, args, os.Stdout, os.Stderr)
	if err != nil {
		code := err.Error()
		var perr *travel.ProviderError
		if errors.As(err, &perr) {
			code = perr.Code
		} else if errors.Is(err, ctx.Err()) {
			code = "cancelled"
		}
		_ = json.NewEncoder(os.Stderr).Encode(map[string]string{"error": code})
		return 2
	}
	return 0
}
