"""Normalize PostgreSQL schema output for synthetic comparisons."""

import re
import runpy
import subprocess


def normalize_array_casts(ddl):
    # A dump/restore can distribute an array cast over literal varchar elements.
    # Compare the same expression tree spelling; preserve each element and its order.
    def array_cast(match):
        values = match[1].split(", ")
        return "ARRAY[" + ", ".join(f"({v})::text" for v in values) + "]"

    return re.sub(
        r"\(ARRAY\[((?:'[A-Za-z_0-9]+'::character varying)(?:, '[A-Za-z_0-9]+'::character varying)*)\]\)::text\[\]",
        array_cast,
        ddl,
    )

def check_native_schema(module, schema, env):
    snapshot = runpy.run_path(str(module / "sql/snapshot.py"))
    ddl = subprocess.check_output(
        ["pg_dump", "--schema-only", "--no-owner", "--no-acl", "--no-comments",
         "--no-tablespaces", "--schema", schema], env=env, text=True,
    )
    actual = snapshot["normalized"](ddl, schema)
    expected = snapshot["SCHEMA"].read_text()
    if normalize_array_casts(actual) != normalize_array_casts(expected):
        raise AssertionError("sql/schema.sql differs from the native baseline")
