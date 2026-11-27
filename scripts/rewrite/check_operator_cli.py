"""Verify operator CLI behavior against Python with isolated PostgreSQL databases."""

import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
from check_gcal_replay import test_url
from check_import_export import fixture
from psycopg import sql
from test_proposal_slice import BACKEND, MODULE, ROOT


@contextmanager
def databases(test, root):
    admin = test.set(drivername="postgresql")
    prefix = "operator_parity_" + uuid4().hex
    names = {mode: prefix + "_" + mode for mode in ("demo", "real", "restore_first", "restore_last")}

    def dsn(mode):
        return admin.set(database=names[mode]).render_as_string(hide_password=False)

    with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as conn:
        try:
            for mode in ("demo", "real"):
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(names[mode])))
            env = {**os.environ, "DATABASE_URL": dsn("real"), "APP_MODE": "real", "PRIVATE_DIR": str(root / "real")}
            subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True)
            with psycopg.connect(dsn("demo")) as source:
                source.execute("CREATE TABLE operator_fixture (value text)")
                source.execute("INSERT INTO operator_fixture VALUES ('synthetic data')")
            yield names, dsn
        finally:
            for name in reversed(list(names.values())):
                conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


def check(root, names, dsn):
    commands = {"python": [sys.executable, "-m", "app.cli"]}
    unified_module = os.environ.get("GO_OPERATOR_MODULE")
    if unified_module:
        binary = root / "going-bananas"
        subprocess.run(["go", "build", "-o", binary, "./cmd/going-bananas"], cwd=unified_module, check=True)
        commands["backup"] = commands["export"] = [str(binary)]
    else:
        for kind, package in (("backup", "workspace-backup"), ("export", "import-export")):
            binary = root / package
            subprocess.run(["go", "build", "-o", binary, "./cmd/" + package], cwd=MODULE, check=True)
            commands[kind] = [str(binary)]

    problems = []

    def invoke(runtime, env, operation, *args):
        kind = "export" if operation == "import-export" else "backup"
        command = commands["python" if runtime == "Python" else kind]
        if runtime == "Python" or unified_module or kind == "backup":
            command = [*command, operation]
        return subprocess.run([*command, *args], env=env, cwd=BACKEND, capture_output=True, text=True, timeout=45)

    def expect(runtime, label, response, status, error=None):
        if response.returncode != status:
            problems.append(f"{runtime} {label}: status {response.returncode}, expected {status}")
        if error is not None:
            try:
                match = json.loads(response.stderr) == {"error": error}
            except json.JSONDecodeError:
                match = False
            if not match or response.stdout:
                problems.append(f"{runtime} {label}: expected JSON error {error} on stderr and empty stdout")

    src = root / "backup-root"
    (src / "raw").mkdir(parents=True)
    (src / "raw" / "sample.fit").write_bytes(b"synthetic file")
    backup_env = {**os.environ, "DATABASE_URL": dsn("demo"), "PRIVATE_DIR": str(src)}
    del backup_env["APP_MODE"]
    archive = root / "python.tar.gz"
    runs = [(runtime, archive if runtime == "Python" else root / "go.tar.gz") for runtime in ("Python", "Go")]
    for runtime, path in runs:
        result = invoke(runtime, backup_env, "backup", path)
        expect(runtime, "backup with APP_MODE unset", result, 0)
        if result.returncode == 0:
            out = json.loads(result.stdout)
            assert out.keys() == {"created_at", "file_count"} and out["file_count"] == 2
            expect(runtime, "existing backup path", invoke(runtime, backup_env, "backup", path), 2, "backup_exists")
        mismatch = {**backup_env, "APP_MODE": "test"}
        invalid = invoke(runtime, mismatch, "backup", root / "rejected.tar.gz")
        if runtime == "Python":
            assert invalid.returncode == 1 and invalid.stderr.endswith(
                "ValueError: Database name must end with APP_MODE suffix\n"
            )
        else:
            expect(runtime, "database suffix mismatch", invalid, 2, "Database name must end with APP_MODE suffix")
        assert not (root / "rejected.tar.gz").exists()

    if archive.exists():
        restored = []
        for mode, runtime in (("restore_first", "Python"), ("restore_last", "Go")):
            folder = root / mode
            params = ["--target-private-dir", str(folder), "--target-database-name", names[mode]]
            args = [archive, *params] if runtime == "Python" else [*params[:2], f"{params[2]}={params[3]}", archive]
            result = invoke(runtime, backup_env, "restore", *args)
            expect(runtime, "restore with reversed flag order", result, 0)
            if result.returncode == 0:
                out = json.loads(result.stdout)
                assert out.keys() == {"restored_at", "file_count"} and out["file_count"] == 2
                restored.append(out)
                assert (folder / "raw" / "sample.fit").read_bytes() == b"synthetic file"
                with psycopg.connect(dsn(mode)) as db:
                    assert db.execute("SELECT value FROM operator_fixture").fetchall() == [("synthetic data",)]
        if len(restored) == 2:
            assert restored[0] == restored[1]
        for runtime in ("Python", "Go"):
            rejected = root / "restore-rejected"
            args = [archive, "--target-database-name", names["demo"], "--target-private-dir", rejected]
            expect(
                runtime,
                "restore current database",
                invoke(runtime, backup_env, "restore", *args),
                2,
                "restore_target_is_current_database",
            )
            assert not rejected.exists()

    export = root / "synthetic.zip"
    fixture(export)
    export_env = {**os.environ, "APP_MODE": "real", "DATABASE_URL": dsn("real"), "PRIVATE_DIR": str(root / "real")}
    results = []
    for runtime in ("Python", "Go"):
        result = invoke(runtime, export_env, "import-export", export)
        expect(runtime, "import-export preview", result, 0)
        if result.returncode == 0:
            results.append(json.loads(result.stdout))
        wrong_mode = {**backup_env, "PRIVATE_DIR": str(root / "import-demo")}
        cases = (
            ("invalid archive", export_env, [root / "missing.zip"], "invalid_export_archive"),
            ("default demo mode", wrong_mode, [export], "real_mode_required"),
            ("invalid argv", export_env, [export, "--unknown"], None),
        )
        for label, env, args, error in cases:
            result = invoke(runtime, env, "import-export", *args)
            expect(runtime, label, result, 2, error)
            if error is None and (
                not result.stderr.startswith("usage:")
                or "unrecognized arguments: --unknown" not in result.stderr
                or result.stdout
            ):
                problems.append(f"{runtime} invalid argv: expected a usage diagnostic only on stderr")
    if len(results) == 2 and results[0] != results[1]:
        problems.append("import-export preview JSON differs")
    with psycopg.connect(dsn("real")) as db:
        for table in ("activities", "import_batches", "raw_objects", "source_records"):
            assert db.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))).fetchone() == (0,)
    assert not (root / "real" / "raw").exists()
    if problems:
        raise AssertionError("\n".join(problems))


def main():
    test = test_url()
    with (
        tempfile.TemporaryDirectory(dir=ROOT / "private") as directory,
        databases(test, Path(directory)) as (names, dsn),
    ):
        check(Path(directory), names, dsn)
    print("PASS operator CLI default mode, settings guards, backup/restore and Garmin export preview")


if __name__ == "__main__":
    main()
