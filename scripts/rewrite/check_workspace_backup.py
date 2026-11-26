"""Exercise the Python and Go backup commands in both directions on synthetic PostgreSQL."""
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql

from test_proposal_slice import BACKEND, MODULE

sys.path.insert(0, str(BACKEND))
from app.services.backup import create_backup, restore_backup, validate_backup


def main():
    url = os.environ["TEST_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    host = urlsplit(url)
    if (os.getenv("APP_MODE") != "test" or host.hostname not in {"localhost", "127.0.0.1"}
            or host.path != "/garmin_test" or str(host.port) != os.getenv("TEST_DATABASE_PORT")):
        raise ValueError("requires isolated test PostgreSQL")
    base = url.rsplit("/", 1)[0] + "/"
    source, to_go, to_py = ["backup_synthetic_" + uuid4().hex for _ in range(3)]
    with (tempfile.TemporaryDirectory() as directory, psycopg.connect(url, autocommit=True) as control):
        root = Path(directory)
        private = root / "private"
        env = dict(os.environ, PRIVATE_DIR=str(private), DATABASE_URL=base + source, PGHOSTADDR="192.0.2.1")
        binary = root / "workspace-backup"
        subprocess.run(["go", "build", "-o", binary, "./cmd/workspace-backup"], cwd=MODULE, check=True)
        (private / "raw").mkdir(parents=True)
        (private / "raw/fixture.fit").write_bytes(b"synthetic fit bytes")
        (private / "raw/token.json").write_text("excluded fixture")
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(source)))
        try:
            with psycopg.connect(base + source) as db:
                db.execute("CREATE TABLE backup_fixture (value text)")
                db.execute("INSERT INTO backup_fixture VALUES ('synthetic row')")
            py_archive, go_archive = root / "py.tar.gz", private / "raw/go.tar.gz"
            create_backup(base + source, private, py_archive)
            go = lambda *args, **kw: subprocess.run([binary, *args], env=env, capture_output=True, **kw)
            info = json.loads(go("backup", go_archive, check=True).stdout)
            assert info["file_count"] == 2 and (go_archive.stat().st_mode & 0o777) == 0o600
            assert set(validate_backup(go_archive)[1]) == {"database.pgdump", "private/raw/fixture.fit"}
            assert go("backup", go_archive).returncode == 2
            restore_backup(go_archive, base + to_py, root / "restored-python")
            def restore(target, folder):
                return go("restore", py_archive, "--target-database-name", target, "--target-private-dir", folder)
            done = restore(to_go, root / "restored-go")
            assert done.returncode == 0, done.stderr
            assert json.loads(done.stdout)["file_count"] == 2
            assert restore(source, root / "unused").returncode == 2
            assert restore(to_go, root / "unused").returncode == 2 and not (root / "unused").exists()
            assert restore(to_py, root / "restored-go").returncode == 2
            # A valid archive manifest with an invalid PostgreSQL dump must roll back both targets.
            invalid = root / "invalid.tar.gz"
            dump = b"synthetic invalid dump"
            manifest = json.dumps({"version": 1, "contains_credentials": False, "files": {
                "database.pgdump": {"sha256": hashlib.sha256(dump).hexdigest(), "bytes": len(dump)}}}).encode()
            with tarfile.open(invalid, "w:gz") as archive:
                for name, data in (("database.pgdump", dump), ("manifest.json", manifest)):
                    header = tarfile.TarInfo(name)
                    header.size = len(data)
                    archive.addfile(header, io.BytesIO(data))
            rejected = "backup_synthetic_" + uuid4().hex
            result = go("restore", invalid, "--target-database-name", rejected, "--target-private-dir", root / "invalid")
            assert result.returncode == 2 and not (root / "invalid").exists()
            assert not control.execute("SELECT FROM pg_database WHERE datname=%s", (rejected,)).fetchall()
            for target, folder in [(to_py, "restored-python"), (to_go, "restored-go")]:
                assert (root / folder / "raw/fixture.fit").read_bytes() == b"synthetic fit bytes"
                assert not (root / folder / "raw/token.json").exists()
                with psycopg.connect(base + target) as db:
                    assert db.execute("SELECT value FROM backup_fixture").fetchall() == [("synthetic row",)]
        finally:
            for name in (to_py, to_go, source):
                control.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
    print("Go and Python restored each other's synthetic database and private files; target guards passed.")


if __name__ == "__main__":
    main()
