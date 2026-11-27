package workspacemigrate

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// Historical migrations and their data transforms remain in the original
// Alembic chain. The child owns both the lock and the SQL transaction so a
// parent interruption or a second startup cannot race the upgrade.
const upgrade = `
import sys
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from app.config import settings

schema, target, lock, parent_pid, token = sys.argv[1:]
engine = create_engine(settings.database_url)
with engine.begin() as conn:
    conn.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL READ COMMITTED, READ WRITE")
    # Both connection libraries may apply libpq environment/service settings
    # differently. Verify the live parent in this exact database before writes.
    same_database = conn.execute(text("""
        SELECT EXISTS(SELECT FROM pg_catalog.pg_stat_activity
        WHERE pid=:pid AND application_name=:token AND datname=current_database())
    """), {"pid": int(parent_pid), "token": token}).scalar_one()
    if not same_database:
        raise RuntimeError("historical connection target mismatch")
    conn.execute(text("SELECT pg_catalog.set_config('search_path',pg_catalog.quote_ident(:schema),true)"), {"schema": schema})
    if conn.exec_driver_sql("SELECT current_schema()").scalar_one() != schema:
        raise RuntimeError("workspace schema disappeared")
    conn.exec_driver_sql(lock)
    if conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == target:
        sys.exit(3)
    config = Config("alembic.ini")
    config.attributes["connection"] = conn
    command.upgrade(config,target)
    if conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() != target:
        raise RuntimeError("migration head mismatch")
`

func historical(ctx context.Context, parent *pgx.Conn, backend, dsn, schema, head string) (string, error) {
	dir, err := filepath.Abs(backend)
	if err != nil {
		return "", err
	}
	python := os.Getenv("PYTHON")
	token := "workspace-migrate-" + uuid.NewString()
	if _, err := parent.Exec(ctx, "SELECT pg_catalog.set_config('application_name',$1,false)", token); err != nil {
		return "", err
	}
	args := []string{"-c", upgrade, schema, head, lockSQL, strconv.FormatUint(uint64(parent.PgConn().PID()), 10), token}
	if python == "" {
		python = filepath.Join(dir, ".venv", "bin", "python")
		if _, err := os.Stat(python); errors.Is(err, os.ErrNotExist) {
			python = "uv"
			args = append([]string{"run", "--locked", "python"}, args...)
		}
	}
	cmd := exec.CommandContext(ctx, python, args...)
	cmd.Dir = dir
	cmd.Env = append(os.Environ(), "DATABASE_URL="+strings.Replace(dsn, "postgresql://", "postgresql+psycopg://", 1))
	// Old SQL exceptions can contain athlete rows or connection details.
	if err := cmd.Run(); err != nil {
		var code *exec.ExitError
		if errors.As(err, &code) && code.ExitCode() == 3 {
			return "current", nil
		}
		if ctx.Err() != nil {
			return "", ctx.Err()
		}
		return "", errors.New("historical_alembic_upgrade_failed")
	}
	return "historical", nil
}
