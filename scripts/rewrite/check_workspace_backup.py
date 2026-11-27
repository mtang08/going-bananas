"""Exercise native backup archives and restoration against synthetic PostgreSQL."""

import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql
from test_proposal_slice import MODULE, ROOT


def main():
    url = os.environ["TEST_DATABASE_URL"].replace(
        "postgresql+psycopg://", "postgresql://"
    )
    host = urlsplit(url)
    if (
        os.getenv("APP_MODE") != "test"
        or host.hostname not in {"localhost", "127.0.0.1"}
        or host.path != "/garmin_test"
        or str(host.port) != os.getenv("TEST_DATABASE_PORT")
    ):
        raise ValueError("requires isolated test PostgreSQL")
    base = url.rsplit("/", 1)[0] + "/"
    source, target, alternate = [
        "backup_synthetic_" + uuid4().hex + "_test" for _ in range(3)
    ]
    with (
        tempfile.TemporaryDirectory(dir=ROOT / "private") as directory,
        psycopg.connect(url, autocommit=True) as control,
    ):
        root = Path(directory)
        private = root / "private"
        env = dict(
            os.environ,
            PRIVATE_DIR=str(private),
            DATABASE_URL=base + source,
            PGHOSTADDR="192.0.2.1",
        )
        binary = root / "workspace-backup"
        subprocess.run(
            ["go", "build", "-o", binary, "./cmd/workspace-backup"],
            cwd=MODULE,
            check=True,
        )
        for overrides, expected in (
            ({"APP_MODE": "wrong"}, "APP_MODE must be demo, real, or test"),
            ({"APP_MODE": ""}, "APP_MODE must be demo, real, or test"),
            (
                {"DATABASE_URL": "sqlite:///synthetic_test"},
                "Only PostgreSQL is supported",
            ),
            (
                {"DATABASE_URL": base + "synthetic_real"},
                "Database name must end with APP_MODE suffix",
            ),
            ({"DATABASE_URL": base}, "Database name must end with APP_MODE suffix"),
        ):
            invalid_env = {**env, **overrides}
            output = root / "invalid-settings.tar.gz"
            go = subprocess.run(
                [binary, "backup", output],
                env=invalid_env,
                capture_output=True,
                text=True,
                check=False,
            )
            assert go.returncode == 2 and json.loads(go.stderr) == {
                "error": expected
            }, go.stderr
            assert not output.exists()
        (private / "raw").mkdir(parents=True)
        (private / "raw/fixture.fit").write_bytes(b"synthetic fit bytes")
        (private / "raw/token.json").write_text("excluded fixture")
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(source)))
        try:
            with psycopg.connect(base + source) as db:
                db.execute("CREATE TABLE backup_fixture (value text)")
                db.execute("INSERT INTO backup_fixture VALUES ('synthetic row')")
            archive = private / "raw/backup.tar.gz"

            def go(*args, check=False):
                return subprocess.run(
                    [binary, *args], env=env, capture_output=True, check=check
                )

            info = json.loads(go("backup", archive, check=True).stdout)
            assert info["file_count"] == 2 and (archive.stat().st_mode & 0o777) == 0o600
            with tarfile.open(archive, "r:gz") as backup:
                manifest = json.load(backup.extractfile("manifest.json"))
                assert (
                    manifest["version"] == 1
                    and manifest["contains_credentials"] is False
                )
                assert set(manifest["files"]) == {
                    "database.pgdump",
                    "private/raw/fixture.fit",
                }
                assert set(backup.getnames()) == set(manifest["files"]) | {
                    "manifest.json"
                }
                for name, metadata in manifest["files"].items():
                    data = backup.extractfile(name).read()
                    assert metadata["bytes"] == len(data)
                    assert metadata["sha256"] == hashlib.sha256(data).hexdigest()
            assert go("backup", archive).returncode == 2

            def restore(name, folder):
                return go(
                    "restore",
                    archive,
                    "--target-database-name",
                    name,
                    "--target-private-dir",
                    folder,
                )

            restored = root / "restored"
            done = restore(target, restored)
            assert done.returncode == 0, done.stderr
            assert json.loads(done.stdout)["file_count"] == 2
            assert restore(source, root / "unused").returncode == 2
            assert (
                restore(target, root / "unused").returncode == 2
                and not (root / "unused").exists()
            )
            assert restore(alternate, restored).returncode == 2
            # A valid archive manifest with an invalid PostgreSQL dump must roll back both targets.
            invalid = root / "invalid.tar.gz"
            dump = b"synthetic invalid dump"
            manifest = json.dumps(
                {
                    "version": 1,
                    "contains_credentials": False,
                    "files": {
                        "database.pgdump": {
                            "sha256": hashlib.sha256(dump).hexdigest(),
                            "bytes": len(dump),
                        }
                    },
                }
            ).encode()
            with tarfile.open(invalid, "w:gz") as archive:
                for name, data in (
                    ("database.pgdump", dump),
                    ("manifest.json", manifest),
                ):
                    header = tarfile.TarInfo(name)
                    header.size = len(data)
                    archive.addfile(header, io.BytesIO(data))
            rejected = "backup_synthetic_" + uuid4().hex
            result = go(
                "restore",
                invalid,
                "--target-database-name",
                rejected,
                "--target-private-dir",
                root / "invalid",
            )
            assert result.returncode == 2 and not (root / "invalid").exists()
            assert not control.execute(
                "SELECT FROM pg_database WHERE datname=%s", (rejected,)
            ).fetchall()
            assert (restored / "raw/fixture.fit").read_bytes() == b"synthetic fit bytes"
            assert not (restored / "raw/token.json").exists()
            with psycopg.connect(base + target) as db:
                assert db.execute("SELECT value FROM backup_fixture").fetchall() == [
                    ("synthetic row",)
                ]
        finally:
            for name in (alternate, target, source):
                control.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name))
                )
    print(
        "PASS native backup manifest, credential exclusions, restore target guards and failed restore cleanup"
    )


if __name__ == "__main__":
    main()
