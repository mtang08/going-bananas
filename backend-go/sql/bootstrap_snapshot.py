"""Generate native bootstrap rows and revision metadata from a freshly migrated disposable schema."""

import argparse
import ast
import json
import os
import re
import subprocess
from pathlib import Path

from snapshot import normalized

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1] / "backend"


def revision_ids():
    chain = {}
    for path in (BACKEND / "migrations/versions").glob("*.py"):
        values = {}
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in ("revision", "down_revision"):
                    values[name] = ast.literal_eval(node.value)
        if values:
            parent = values["down_revision"]
            if parent in chain:
                raise ValueError("expected a linear migration history")
            chain[parent] = values["revision"]
    ids = []
    head = None
    while head in chain:
        head = chain.pop(head)
        ids.append(head)
    if chain or not ids:
        raise ValueError("invalid migration history")
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    command = ["psql", "-XAt", "-v", "ON_ERROR_STOP=1", "-c"]
    if not os.environ.get("PGDATABASE", "").endswith("_test"):
        parser.error("requires an explicitly selected synthetic test database")
    schema = subprocess.check_output(
        [*command, "SELECT current_schema()"], text=True
    ).strip()
    if not re.fullmatch(r"go_parity_[0-9a-f]{32}", schema):
        parser.error("requires a fresh disposable Alembic parity schema")
    subprocess.run(["python3", HERE / "snapshot.py", "--check"], check=True)
    ids = revision_ids()
    stamp = subprocess.check_output(
        [*command, "SELECT version_num FROM alembic_version"], text=True
    ).strip()
    if stamp != ids[-1]:
        parser.error("fresh schema must be at repository migration head")
    dump = subprocess.check_output(
        [
            "pg_dump",
            "--data-only",
            "--column-inserts",
            "--no-owner",
            "--no-acl",
            "--schema",
            schema,
        ],
        text=True,
    )
    rows = [
        line
        for line in normalized(dump, schema).splitlines()
        if line.startswith(("INSERT INTO ", "SELECT pg_catalog.setval("))
    ]
    for path, data in [
        (HERE / "bootstrap.sql", "\n".join(rows) + "\n"),
        (HERE / "revisions.json", json.dumps(ids, indent=2) + "\n"),
    ]:
        if args.check:
            if path.read_text() != data:
                raise SystemExit(f"{path.name} differs from fresh Alembic migration")
        else:
            path.write_text(data)


if __name__ == "__main__":
    main()
