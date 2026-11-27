package garmincli

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"time"

	"github.com/google/uuid"
)

// Command runs Python-compatible sync or worker CLI arguments on the supplied worker.
// A sync which finishes with partial, failed, waiting or idle jobs exits with code 1.
func (w *Worker) Command(ctx context.Context, args []string, stdout io.Writer) (int, error) {
	if len(args) == 1 && args[0] == "worker" {
		err := w.Work(ctx)
		if err != nil && !errors.Is(err, context.Canceled) {
			return 1, err
		}
		return 0, nil
	}
	if len(args) == 0 || args[0] != "sync" {
		return 2, errors.New("expected sync or worker")
	}
	flags := flag.NewFlagSet("sync", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	var start, end *time.Time
	dateFlag := func(dst **time.Time) func(string) error {
		return func(s string) error {
			t, err := time.Parse(time.DateOnly, s)
			if err == nil {
				*dst = &t
			}
			return err
		}
	}
	flags.Func("start", "first calendar date", dateFlag(&start))
	flags.Func("end", "last calendar date", dateFlag(&end))
	if err := flags.Parse(args[1:]); err != nil {
		return 2, err
	}
	if flags.NArg() != 0 {
		return 2, errors.New("unexpected sync argument")
	}
	output := json.NewEncoder(stdout)
	statuses, err := w.Sync(ctx, start, end, func(ids []uuid.UUID) error {
		return output.Encode(map[string]any{"job_ids": ids})
	})
	if err != nil {
		return 1, err
	}
	exit := 0
	results := make([]*string, len(statuses))
	for i, status := range statuses {
		if status != "complete" {
			exit = 1
		}
		if status != "" {
			results[i] = &status
		}
	}
	if err := output.Encode(map[string]any{"results": results}); err != nil {
		return 1, err
	}
	return exit, nil
}
