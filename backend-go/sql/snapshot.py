"""Refresh or verify sqlc's schema using a migrated PostgreSQL 17 test database."""

import argparse
import os
import re
import subprocess
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


def normalized(dump: str, schema: str) -> str:
    lines = []
    for line in dump.splitlines():
        if line.startswith(("--", r"\restrict ", r"\unrestrict ")):
            continue
        if line == f"CREATE SCHEMA {schema};":
            continue
        lines.append(re.sub(rf"\b{re.escape(schema)}\.", "public.", line))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("PGDATABASE"):
        parser.error("set PGDATABASE explicitly to a migrated synthetic _test database")
    result = subprocess.check_output(
        ["psql", "-XAt", "-v", "ON_ERROR_STOP=1", "-c",
         "SELECT current_database(), current_schema(), current_setting('server_version_num')"],
        text=True,
    )
    name, schema, version = result.strip().split("|")
    if not name.endswith("_test") or not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
        parser.error("expected a synthetic _test database and a simple schema name")
    if int(version) // 10000 != 17:
        parser.error("snapshot requires PostgreSQL 17")
    dump = subprocess.check_output(
        ["pg_dump", "--schema-only", "--no-owner", "--no-acl", "--no-comments",
         "--no-tablespaces", "--schema", schema], text=True,
    )
    snapshot = normalized(dump, schema)
    if args.check:
        if SCHEMA.read_text() != snapshot:
            raise SystemExit("sql/schema.sql differs from the migrated database")
    else:
        SCHEMA.write_text(snapshot)


if __name__ == "__main__":
    main()
