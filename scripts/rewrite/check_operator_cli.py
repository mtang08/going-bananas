"""Verify unified operator CLI behavior with isolated PostgreSQL databases."""

import json
import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
from check_gcal_replay import test_url
from check_import_export import fixture
from psycopg import sql
from test_proposal_slice import MODULE, ROOT


@contextmanager
def databases(test, root, binary):
    admin = test.set(drivername="postgresql")
    prefix = "operator_fixture_" + uuid4().hex
    names = {
        mode: prefix + "_" + mode
        for mode in ("demo", "real", "restore_first", "restore_last")
    }

    def dsn(mode):
        return admin.set(database=names[mode]).render_as_string(hide_password=False)

    with psycopg.connect(
        admin.render_as_string(hide_password=False), autocommit=True
    ) as conn:
        try:
            for mode in ("demo", "real"):
                conn.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(names[mode]))
                )
            env = {
                **os.environ,
                "DATABASE_URL": dsn("real"),
                "APP_MODE": "real",
                "PRIVATE_DIR": str(root / "real"),
            }
            subprocess.run([binary, "migrate"], cwd=ROOT, env=env, check=True)
            with psycopg.connect(dsn("demo")) as source:
                source.execute("CREATE TABLE operator_fixture (value text)")
                source.execute("INSERT INTO operator_fixture VALUES ('synthetic data')")
            yield names, dsn
        finally:
            for name in reversed(list(names.values())):
                conn.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name))
                )


def check(root, names, dsn, binary):
    def invoke(env, operation, *args):
        return subprocess.run(
            [binary, operation, *args],
            env=env,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )

    def expect(response, status, error=None):
        assert response.returncode == status, response
        if error is not None:
            assert json.loads(response.stderr) == {"error": error}
            assert not response.stdout
        return response

    src = root / "backup-root"
    (src / "raw").mkdir(parents=True)
    (src / "raw" / "sample.fit").write_bytes(b"synthetic file")
    backup_env = {**os.environ, "DATABASE_URL": dsn("demo"), "PRIVATE_DIR": str(src)}
    del backup_env["APP_MODE"]
    archive = root / "native.tar.gz"
    result = expect(invoke(backup_env, "backup", archive), 0)
    out = json.loads(result.stdout)
    assert out.keys() == {"created_at", "file_count"} and out["file_count"] == 2
    expect(invoke(backup_env, "backup", archive), 2, "backup_exists")
    mismatch = {**backup_env, "APP_MODE": "test"}
    expect(
        invoke(mismatch, "backup", root / "rejected.tar.gz"),
        2,
        "Database name must end with APP_MODE suffix",
    )
    assert not (root / "rejected.tar.gz").exists()

    restored = []
    for mode in ("restore_first", "restore_last"):
        folder = root / mode
        flags = [
            "--target-private-dir",
            str(folder),
            "--target-database-name",
            names[mode],
        ]
        args = (
            [archive, *flags]
            if mode == "restore_first"
            else [*flags[:2], f"{flags[2]}={flags[3]}", archive]
        )
        result = expect(invoke(backup_env, "restore", *args), 0)
        out = json.loads(result.stdout)
        assert out.keys() == {"restored_at", "file_count"} and out["file_count"] == 2
        restored.append(out)
        assert (folder / "raw" / "sample.fit").read_bytes() == b"synthetic file"
        with psycopg.connect(dsn(mode)) as db:
            assert db.execute("SELECT value FROM operator_fixture").fetchall() == [
                ("synthetic data",)
            ]
    assert restored[0] == restored[1]
    rejected = root / "restore-rejected"
    expect(
        invoke(
            backup_env,
            "restore",
            archive,
            "--target-database-name",
            names["demo"],
            "--target-private-dir",
            rejected,
        ),
        2,
        "restore_target_is_current_database",
    )
    assert not rejected.exists()

    export = root / "synthetic.zip"
    fixture(export)
    export_env = {
        **os.environ,
        "APP_MODE": "real",
        "DATABASE_URL": dsn("real"),
        "PRIVATE_DIR": str(root / "real"),
    }
    result = expect(invoke(export_env, "import-export", export), 0)
    assert json.loads(result.stdout) == json.loads(
        expect(invoke(export_env, "import-export", export), 0).stdout
    )
    wrong_mode = {**backup_env, "PRIVATE_DIR": str(root / "import-demo")}
    expect(
        invoke(export_env, "import-export", root / "missing.zip"),
        2,
        "invalid_export_archive",
    )
    expect(invoke(wrong_mode, "import-export", export), 2, "real_mode_required")
    invalid = expect(invoke(export_env, "import-export", export, "--unknown"), 2)
    assert not invalid.stdout and invalid.stderr.startswith("usage:")
    assert "unrecognized arguments: --unknown" in invalid.stderr
    with psycopg.connect(dsn("real")) as db:
        for table in ("activities", "import_batches", "raw_objects", "source_records"):
            assert db.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
            ).fetchone() == (0,)
    assert not (root / "real" / "raw").exists()


def main():
    test = test_url()
    with tempfile.TemporaryDirectory(dir=ROOT / "private") as directory:
        root = Path(directory)
        binary = root / "going-bananas"
        subprocess.run(
            ["go", "build", "-o", binary, "./cmd/going-bananas"], cwd=MODULE, check=True
        )
        with databases(test, root, binary) as (names, dsn):
            check(root, names, dsn, binary)
    print(
        "PASS operator CLI default mode, settings guards, backup/restore and Garmin export preview"
    )


if __name__ == "__main__":
    main()
