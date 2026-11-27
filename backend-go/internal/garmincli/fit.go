package garmincli

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"github.com/google/uuid"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin"
	"github.com/mtang08/going-bananas/backend-go/internal/garmin/replay"
	"io"
	"time"
)

// RunFITCommand handles live backfill and offline retained-file reprocessing.
// Tests supply an isolated download source. Reprocessing never opens a Garmin client.
func RunFITCommand(ctx context.Context, mode string, cfg Config, args []string, out io.Writer, src replay.FITSource) error {
	if len(args) == 0 || (args[0] != "fit-backfill" && args[0] != "fit-reprocess") {
		return errors.New("expected fit-backfill or fit-reprocess")
	}
	flags := flag.NewFlagSet(args[0], flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	date := flags.String("since", "", "first local date")
	var apply bool
	var activity string
	if args[0] == "fit-reprocess" {
		flags.BoolVar(&apply, "apply", false, "commit all changes")
		flags.StringVar(&activity, "activity-id", "", "select one activity")
	}
	if err := flags.Parse(args[1:]); err != nil {
		return err
	}
	if flags.NArg() != 0 || *date == "" {
		return errors.New("expected --since YYYY-MM-DD")
	}
	since, err := time.Parse(time.DateOnly, *date)
	if err != nil {
		return errors.New("invalid_date")
	}
	if cfg.Now == nil {
		cfg.Now = time.Now
	}
	if cfg.Refresh == nil {
		return errors.New("garmin_refresh_required")
	}
	var result any
	if args[0] == "fit-backfill" {
		if mode != "real" {
			return errors.New("real_mode_required")
		}
		if since.Format(time.DateOnly) > cfg.Now().In(time.Local).Format(time.DateOnly) {
			return errors.New("invalid_date_window")
		}
		if src == nil {
			src, err = garmin.Open(ctx, garminConfig(cfg.PrivateDir))
			if err != nil {
				return err
			}
		}
		result, err = replay.Backfill(ctx, cfg.Pool, cfg.PrivateDir, src, since, cfg.Now, cfg.Refresh)
	} else {
		var id *uuid.UUID
		if activity != "" {
			parsed, err := uuid.Parse(activity)
			if err != nil {
				return errors.New("invalid_activity_id")
			}
			id = &parsed
		}
		result, err = replay.ReprocessRange(ctx, cfg.Pool, cfg.PrivateDir, since, id, apply, cfg.Now().UTC(), cfg.Refresh)
	}
	if err != nil {
		return err
	}
	return json.NewEncoder(out).Encode(result)
}
