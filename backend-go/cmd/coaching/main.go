// Command coaching exercises the pending-draft lifecycle against a synthetic database.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drafts"
)

func run(ctx context.Context, args []string, w io.Writer) error {
	if len(args) == 0 {
		return errors.New("usage: coaching load|discard|submit|revise [-id UUID] [-revision N]")
	}
	flags := flag.NewFlagSet(args[0], flag.ContinueOnError)
	idArg := flags.String("id", "", "saved proposal ID")
	revision := flags.Int("revision", 0, "expected draft revision")
	root := flags.String("repo", ".", "repository root containing the verified knowledge package")
	nowArg := flags.String("now", "", "synthetic evaluation time, RFC3339")
	if err := flags.Parse(args[1:]); err != nil {
		return err
	}
	id, err := uuid.Parse(*idArg)
	if err != nil && args[0] != "submit" {
		return errors.New("valid proposal -id required")
	}
	mode := os.Getenv("APP_MODE")
	if mode != "test" && mode != "demo" {
		return errors.New("APP_MODE must be test or demo")
	}
	dsn := strings.Replace(os.Getenv("DATABASE_URL"), "postgresql+psycopg://", "postgresql://", 1)
	if dsn == "" {
		return errors.New("DATABASE_URL is required")
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil || !strings.HasSuffix(cfg.ConnConfig.Database, "_"+mode) {
		return errors.New("database must match the synthetic application mode")
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return errors.New("could not open synthetic database")
	}
	defer pool.Close()
	s := drafts.Store{Pool: pool}
	now := time.Now().UTC()
	if *nowArg != "" {
		now, err = time.Parse(time.RFC3339Nano, *nowArg)
		if err != nil {
			return errors.New("invalid evaluation timestamp")
		}
	}
	absolute, err := filepath.Abs(*root)
	if err != nil {
		return err
	}
	validate := drafts.NewValidator(filepath.Join(absolute, "running_coach_kb"))
	var result any
	switch args[0] {
	case "submit":
		var raw json.RawMessage
		if err := json.NewDecoder(os.Stdin).Decode(&raw); err != nil {
			return err
		}
		result, err = s.Submit(ctx, raw, now, validate)
	case "revise":
		var req drafts.RevisionRequest
		dec := json.NewDecoder(os.Stdin)
		dec.DisallowUnknownFields()
		if err := dec.Decode(&req); err != nil {
			return err
		}
		if req.ExpectedRevision < 1 || len([]rune(req.Reason)) > 500 {
			return errors.New("invalid revision request")
		}
		result, err = s.Revise(ctx, id, req, now, validate)
	case "load":
		result, err = s.Load(ctx, id)
	case "discard":
		if *revision < 1 {
			return errors.New("positive -revision required")
		}
		result, err = s.Discard(ctx, id, *revision, now)
	default:
		return errors.New("unknown coaching operation")
	}
	if err != nil {
		return err
	}
	return json.NewEncoder(w).Encode(result)
}

func main() {
	if err := run(context.Background(), os.Args[1:], os.Stdout); err != nil {
		var command *drafts.CommandError
		var decision *drafts.Error
		if errors.As(err, &command) {
			_ = json.NewEncoder(os.Stderr).Encode(command)
		} else if errors.As(err, &decision) {
			_ = json.NewEncoder(os.Stderr).Encode(decision)
		} else {
			fmt.Fprintln(os.Stderr, "Coaching command failed:", err)
		}
		os.Exit(1)
	}
}
