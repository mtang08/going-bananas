// Command going-bananas-coach serves the skill's local synthetic coaching protocol.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/mtang08/going-bananas/backend-go/internal/coachdashboard"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drafts"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/drilldowns"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/protocol"
	"github.com/mtang08/going-bananas/backend-go/internal/coaching/snapshots"
	"github.com/mtang08/going-bananas/backend-go/internal/db"
)

type object = map[string]any

type command struct {
	name, operation, asOf, file, reason string
	revision                            int
	id                                  *uuid.UUID
	query                               object
}

var queries = map[string][]string{"activity_execution": {"activity-id"}, "explain_metric": {"result-id"}, "calendar_diff": {"from", "to"}, "recovery_nights": {"start", "end"}, "long_run_history": {"start", "end"}}

type missingFlag string

func (f missingFlag) Error() string { return "--" + string(f) + " required" }

func parse(args []string) (command, error) {
	var c command
	invalid := errors.New("invalid coach command arguments")
	if len(args) == 0 {
		return c, invalid
	}
	c.name = args[0]
	args = args[1:]
	f := flag.NewFlagSet(c.name, flag.ContinueOnError)
	f.SetOutput(io.Discard)
	switch c.name {
	case "schema":
	case "snapshot":
		f.StringVar(&c.operation, "operation", "", "")
		f.StringVar(&c.asOf, "as-of", "", "")
	case "query":
		if len(args) == 0 || queries[args[0]] == nil {
			return c, invalid
		}
		c.query = object{"name": args[0]}
		args = args[1:]
		for _, k := range []string{"activity-id", "result-id", "from", "to", "start", "end"} {
			if k == "from" || k == "to" {
				f.Int(k, 0, "")
			} else {
				f.String(k, "", "")
			}
		}
	case "revise":
		if len(args) == 0 {
			return c, invalid
		}
		id, err := uuid.Parse(args[0])
		if err != nil {
			return c, invalid
		}
		c.id = &id
		args = args[1:]
		f.IntVar(&c.revision, "expected-revision", 0, "")
		f.StringVar(&c.reason, "reason", "", "")
		fallthrough
	case "submit":
		f.StringVar(&c.file, "file", "", "")
	default:
		return c, invalid
	}
	if err := f.Parse(args); err != nil || f.NArg() != 0 {
		return c, invalid
	}
	flags := map[string]string{}
	f.Visit(func(fl *flag.Flag) { flags[fl.Name] = fl.Value.String() })
	if c.query != nil {
		for _, k := range queries[c.query["name"].(string)] {
			if _, ok := flags[k]; !ok {
				return c, missingFlag(k)
			}
		}
		for k, v := range flags {
			key := strings.ReplaceAll(k, "-", "_")
			switch k {
			case "from", "to":
				key += "_version"
			case "start", "end":
				if _, err := time.Parse(time.DateOnly, v); err != nil {
					return c, invalid
				}
			default:
				if _, err := uuid.Parse(v); err != nil {
					return c, invalid
				}
			}
			c.query[key] = v
		}
	}
	if c.name == "snapshot" {
		if !snapshots.Supported(c.operation) {
			return c, invalid
		}
		if c.asOf != "" {
			if _, err := time.Parse(time.DateOnly, c.asOf); err != nil {
				return c, invalid
			}
		}
	}
	if c.name == "revise" {
		for _, k := range []string{"reason", "expected-revision"} {
			if _, ok := flags[k]; !ok {
				return c, invalid
			}
		}
	}
	if (c.name == "submit" || c.name == "revise") && c.file == "" {
		return c, invalid
	}
	return c, nil
}

func emit(w io.Writer, code int, v any) int {
	if json.NewEncoder(w).Encode(v) != nil {
		return 1
	}
	return code
}

func issue(code, msg string) []drafts.Issue { return []drafts.Issue{{Code: code, Message: msg}} }

func invalid(id *uuid.UUID, code string, issues []drafts.Issue) object {
	o := object{"proposal_id": id, "revision": nil, "status": "invalid", "errors": issues}
	if code != "" {
		o["error"] = code
	}
	return o
}

func (c command) run(ctx context.Context, out, stderr io.Writer) int {
	if c.name == "schema" {
		return emit(out, 0, protocol.Schema())
	}
	var raw json.RawMessage
	if c.file != "" {
		data, err := os.ReadFile(c.file)
		data = bytes.TrimSpace(data)
		if err != nil || len(data) == 0 || data[0] != '{' || !utf8.Valid(data) || !json.Valid(data) {
			return emit(out, 2, invalid(nil, "", issue("V1.schema", "File is not a JSON object")))
		}
		raw = data
		if c.id != nil && (c.revision < 1 || len([]rune(c.reason)) < 1 || len([]rune(c.reason)) > 500) {
			return emit(out, 2, invalid(c.id, "invalid_revision_request", issue("invalid_revision_request", "Invalid revision request")))
		}
	}
	mode := os.Getenv("APP_MODE")
	dsn := strings.Replace(os.Getenv("DATABASE_URL"), "postgresql+psycopg://", "postgresql://", 1)
	cfg, err := pgxpool.ParseConfig(dsn)
	if dsn == "" || err != nil || (mode != "test" && mode != "demo") || !strings.HasSuffix(cfg.ConnConfig.Database, "_"+mode) {
		return emit(stderr, 1, object{"error": "invalid_synthetic_database"})
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return emit(stderr, 1, object{"error": "unexpected_error"})
	}
	defer pool.Close()
	root := os.Getenv("GB_MODE_ROOT")
	if root == "" {
		root = os.Getenv("GB_REPO")
	}
	if root == "" {
		root = "."
	}
	kb := filepath.Join(root, "running_coach_kb")
	access := pgx.ReadWrite
	if c.query != nil {
		access = pgx.ReadOnly
	}
	now := time.Now().UTC()
	code := 0
	var result any
	err = pgx.BeginTxFunc(ctx, pool, pgx.TxOptions{AccessMode: access}, func(tx pgx.Tx) error {
		var err error
		switch c.name {
		case "snapshot":
			if c.asOf == "" {
				zone, err := db.New(tx).CalendarTimezone(ctx)
				if err != nil {
					return err
				}
				loc, err := time.LoadLocation(zone)
				if err != nil {
					return err
				}
				c.asOf = now.In(loc).Format(time.DateOnly)
			}
			result, err = snapshots.Build(ctx, tx, c.operation, c.asOf, now, kb)
		case "query":
			var data any
			data, err = drilldowns.CLIQuery(ctx, tx, c.query)
			result = object{"query": c.query["name"], "data": data}
		default:
			store := drafts.InTransaction(tx)
			validate := drafts.NewValidator(kb)
			var edit drafts.EditResult
			if c.id == nil {
				edit, err = store.Submit(ctx, raw, now, validate)
			} else {
				edit, err = store.Revise(ctx, *c.id, drafts.RevisionRequest{ExpectedRevision: c.revision, Reason: c.reason, Document: raw}, now, validate)
			}
			result = object{"proposal_id": edit.ID, "revision": edit.Revision, "status": edit.Status, "errors": edit.Issues}
			switch edit.Status {
			case "pending":
			case "stale":
				code = 3
			default:
				code = 2
			}
		}
		return err
	})
	if err != nil {
		return c.failure(err, root, out, stderr)
	}
	return emit(out, code, result)
}

func (c command) failure(err error, root string, out, stderr io.Writer) int {
	code := 2
	var d *drafts.Error
	var t *coachdashboard.ToolFailure
	var pg *pgconn.PgError
	switch {
	case errors.As(err, &pg) && (pg.Code == "42703" || pg.Code == "42P01"):
		o := object{"error": "database_schema_mismatch", "message": "The coach could not find a required database column or table. Check the migration version for this workspace before retrying."}
		if head, err := os.ReadFile(filepath.Join(root, "backend/app/migrations_head.py")); err == nil {
			for _, line := range strings.Split(string(head), "\n") {
				if val, ok := strings.CutPrefix(line, "EXPECTED_HEAD = "); ok {
					o["expected_migration"] = strings.Trim(val, "\"")
					break
				}
			}
		}
		return emit(stderr, 1, o)
	case errors.Is(err, snapshots.ErrKnowledgeUnavailable):
		return emit(stderr, 4, object{"error": "knowledge_unavailable"})
	case errors.As(err, &d):
		if d.Code == "knowledge_unavailable" {
			return emit(stderr, 4, object{"error": d.Code})
		}
		issues := issue(d.Code, d.Message)
		var cmd *drafts.CommandError
		if errors.As(err, &cmd) && len(cmd.Issues) > 0 {
			issues = cmd.Issues
		}
		code = 2
		if d.Code == "stale_evidence" {
			code = 3
		}
		return emit(out, code, invalid(c.id, d.Code, issues))
	case errors.As(err, &t):
		code = 2
		if strings.HasSuffix(t.Code, "_not_found") {
			code = 4
		}
		return emit(stderr, code, object{"error": t.Code})
	default:
		return emit(stderr, 1, object{"error": "unexpected_error"})
	}
}

func run(ctx context.Context, args []string, out, stderr io.Writer) int {
	c, err := parse(args)
	if err != nil {
		var m missingFlag
		if errors.As(err, &m) {
			return emit(stderr, 2, object{"error": "missing_argument", "message": m.Error()})
		}
		return emit(stderr, 2, object{"error": "invalid_arguments"})
	}
	return c.run(ctx, out, stderr)
}

func main() { os.Exit(run(context.Background(), os.Args[1:], os.Stdout, os.Stderr)) }
