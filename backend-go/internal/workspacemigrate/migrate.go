// Package workspacemigrate provisions a new PostgreSQL workspace and upgrades
// historical Alembic workspaces without discarding existing data.
package workspacemigrate

import (
	"context"
	"errors"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"
	baseline "github.com/mtang08/going-bananas/backend-go/sql"
)

type Result struct {
	Action string `json:"action"`
	Head   string `json:"head"`
}

// The Python historical path takes this same transaction-scoped lock before running Alembic.
const lockSQL = "SELECT pg_catalog.pg_advisory_xact_lock(1948468209, pg_catalog.hashtext(current_schema()::text))"

func classify(ctx context.Context, tx pgx.Tx, schema string, revisions []string) (string, error) {
	var stamped bool
	err := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname=$1 AND c.relname='alembic_version' AND c.relkind='r')`, schema).Scan(&stamped)
	if err != nil {
		return "", err
	}
	if !stamped {
		var occupied bool
		err = tx.QueryRow(ctx, `SELECT EXISTS(SELECT FROM pg_catalog.pg_depend d JOIN pg_catalog.pg_namespace n ON d.refobjid=n.oid
 WHERE d.refclassid='pg_catalog.pg_namespace'::regclass AND n.nspname=$1)`, schema).Scan(&occupied)
		if err != nil {
			return "", err
		}
		if occupied {
			return "", errors.New("nonempty_unstamped_schema")
		}
		return "baseline", nil
	}
	var stamps []string
	if err := tx.QueryRow(ctx, "SELECT coalesce(array_agg(version_num::text),'{}') FROM "+pgx.Identifier{schema, "alembic_version"}.Sanitize()).Scan(&stamps); err != nil {
		return "", err
	}
	if len(stamps) != 1 || !slices.Contains(revisions, stamps[0]) {
		return "", errors.New("unknown_migration_revision")
	}
	if stamps[0] == revisions[len(revisions)-1] {
		return "current", nil
	}
	return "historical", nil
}

// Run inspects the selected schema behind the same lock as native and historical
// migrations. In check mode it reports the action without running it.
func Run(ctx context.Context, conn *pgx.Conn, backend, dsn string, check bool) (Result, error) {
	revisions := baseline.Revisions()
	result := Result{Head: revisions[len(revisions)-1]}
	var schema string
	opts := pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}
	if check {
		opts = pgx.TxOptions{AccessMode: pgx.ReadOnly, IsoLevel: pgx.RepeatableRead}
	}
	err := pgx.BeginTxFunc(ctx, conn, opts, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx, "SELECT coalesce(current_schema()::text,'')").Scan(&schema); err != nil {
			return err
		}
		if schema == "" || strings.HasPrefix(schema, "pg_") || schema == "information_schema" {
			return errors.New("invalid_workspace_schema")
		}
		if !check {
			if _, err := tx.Exec(ctx, lockSQL); err != nil {
				return err
			}
		}
		var err error
		result.Action, err = classify(ctx, tx, schema, revisions)
		if err != nil || check || result.Action != "baseline" {
			return err
		}
		if _, err := tx.Exec(ctx, "SELECT pg_catalog.set_config('search_path',pg_catalog.quote_ident($1),true)", schema); err != nil {
			return err
		}
		_, err = tx.Exec(ctx, baseline.SQL())
		return err
	})
	if err == nil && !check && result.Action == "historical" {
		result.Action, err = historical(ctx, conn, backend, dsn, schema, result.Head)
		if err == nil {
			// Confirm the receipt against the original connection as well.
			var stamped bool
			err = conn.QueryRow(ctx, "SELECT count(*)=1 AND coalesce(bool_and(version_num=$1),false) FROM "+pgx.Identifier{schema, "alembic_version"}.Sanitize(), result.Head).Scan(&stamped)
			if err == nil && !stamped {
				err = errors.New("historical_alembic_upgrade_failed")
			}
		}
	}
	return result, err
}
