package backup

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"
)

var dbName = regexp.MustCompile(`^[A-Za-z0-9_]{1,63}$`)

func connection(dsn string) (*url.URL, error) {
	u, err := url.Parse(strings.Replace(dsn, "postgresql+psycopg://", "postgresql://", 1))
	if err != nil || u.Scheme != "postgresql" || u.Hostname() == "" || strings.TrimPrefix(u.Path, "/") == "" {
		return nil, errors.New("invalid_database_url")
	}
	return u, nil
}

func pg(ctx context.Context, u *url.URL, program string, args ...string) error {
	cmd := exec.CommandContext(ctx, program, args...)
	port := u.Port()
	if port == "" {
		port = "5432"
	}
	cmd.Env = append(os.Environ(), "PGHOST="+u.Hostname(), "PGPORT="+port, "PGDATABASE="+strings.TrimPrefix(u.Path, "/"))
	if u.User != nil {
		cmd.Env = append(cmd.Env, "PGUSER="+u.User.Username())
		if pw, ok := u.User.Password(); ok {
			cmd.Env = append(cmd.Env, "PGPASSWORD="+pw)
		}
	}
	if err := cmd.Run(); err != nil {
		return errors.New("postgres_tool_failed")
	}
	return nil
}

func mustBeNew(p, code string) error {
	_, err := os.Lstat(p)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	return errors.New(code)
}

func Create(ctx context.Context, dsn, private, output string) (Manifest, error) {
	var m Manifest
	u, err := connection(dsn)
	if err != nil {
		return m, err
	}
	if private == "" || output == "" {
		return m, errors.New("missing_paths")
	}
	if err = mustBeNew(output, "backup_exists"); err != nil {
		return m, err
	}
	parent := filepath.Dir(output)
	if err = os.MkdirAll(parent, 0700); err != nil {
		return m, err
	}
	// Keep intermediate files outside the allowlisted data roots, even if output is inside private.
	stage, err := os.MkdirTemp("", "workspace-dump-")
	if err != nil {
		return m, err
	}
	defer func() { _ = os.RemoveAll(stage) }()
	dump := filepath.Join(stage, "database.pgdump")
	if err = pg(ctx, u, "pg_dump", "--format=custom", "--file", dump); err != nil {
		return m, err
	}
	// Spool outside private so traversal cannot include the archive being written.
	spool, err := os.CreateTemp(stage, "archive-")
	if err != nil {
		return m, err
	}
	defer func() { _ = spool.Close() }()
	m, err = writeArchive(spool, private, dump)
	if err != nil {
		return m, err
	}
	if _, err = spool.Seek(0, 0); err != nil {
		return m, err
	}
	tmp, err := os.CreateTemp(parent, ".backup-")
	if err != nil {
		return m, err
	}
	defer func() { _ = os.Remove(tmp.Name()) }()
	_, err = tmp.ReadFrom(spool)
	closeErr := tmp.Close()
	if err != nil {
		return m, err
	}
	if closeErr != nil {
		return m, closeErr
	}
	// Atomic publication; competing creates cannot replace an existing archive.
	return m, os.Link(tmp.Name(), output)
}

func Restore(ctx context.Context, dsn, archive, target, private string) (Manifest, error) {
	var m Manifest
	u, err := connection(dsn)
	if err != nil {
		return m, err
	}
	if !dbName.MatchString(target) {
		return m, errors.New("invalid_target_database_name")
	}
	if target == strings.TrimPrefix(u.Path, "/") {
		return m, errors.New("restore_target_is_current_database")
	}
	if private == "" {
		return m, errors.New("missing_paths")
	}
	if err = mustBeNew(private, "restore_private_target_exists"); err != nil {
		return m, err
	}
	parent := filepath.Dir(private)
	if err = os.MkdirAll(parent, 0700); err != nil {
		return m, err
	}
	stage, err := os.MkdirTemp(parent, ".workspace-restore-")
	if err != nil {
		return m, err
	}
	defer func() { _ = os.RemoveAll(stage) }()
	m, err = unpack(archive, stage)
	if err != nil {
		return m, err
	}
	// Reserve the target name before creating the database. Only delete an empty reservation.
	if err = os.Mkdir(private, 0700); err != nil {
		return m, err
	}
	installed := false
	defer func() {
		if !installed {
			_ = os.Remove(private)
		}
	}()
	u.Path = "/postgres"
	if err = pg(ctx, u, "createdb", "--", target); err != nil {
		return m, err
	}
	u.Path = "/" + target
	err = pg(ctx, u, "pg_restore", "--no-owner", "--no-acl", "--single-transaction", "--dbname", target, filepath.Join(stage, "database.pgdump"))
	if err == nil {
		tree := filepath.Join(stage, "private")
		if err = os.MkdirAll(tree, 0700); err == nil {
			// POSIX rename atomically replaces our reserved empty directory.
			err = syscall.Rename(tree, private)
		}
	}
	if err != nil {
		u.Path = "/postgres"
		cleanup, cancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
		defer cancel()
		if dropErr := pg(cleanup, u, "dropdb", "--", target); dropErr != nil {
			return m, fmt.Errorf("%w: restore_target_cleanup_failed", err)
		}
		return m, err
	}
	installed = true
	return m, nil
}
