"""Private PostgreSQL/raw-data backups with validated new-target restores."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


class BackupError(RuntimeError):
    pass


def _pg_env(url: str) -> tuple[dict[str, str], str]:
    parsed = urlsplit(url.replace("postgresql+psycopg://", "postgresql://", 1))
    if parsed.scheme != "postgresql" or not parsed.path.strip("/"):
        raise BackupError("invalid_database_url")
    env = os.environ.copy()
    env.update(PGHOST=parsed.hostname or "localhost", PGPORT=str(parsed.port or 5432),
               PGDATABASE=unquote(parsed.path.lstrip("/")))
    if parsed.username:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    return env, env["PGDATABASE"]


def _run(argv: list[str], env: dict[str, str]) -> None:
    result = subprocess.run(argv, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False)
    if result.returncode:
        raise BackupError("postgres_tool_failed")


def _safe_files(private_dir: Path) -> list[Path]:
    files: list[Path] = []
    for root_name in ("raw", "profile", "config", "research-imports"):
        root = private_dir / root_name
        if not root.exists():
            continue
        if root.is_symlink():
            raise BackupError("private_symlink")
        candidates = root.rglob("*")
        for path in candidates:
            if path.is_symlink():
                raise BackupError("private_symlink")
            if not path.is_file():
                continue
            if "token" in path.name.lower() or "key" in path.name.lower() or path.name == ".env":
                continue
            files.append(path)
    return files


def create_backup(database_url: str, private_dir: Path, output: Path) -> dict:
    if output.exists():
        raise BackupError("backup_exists")
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    env, _ = _pg_env(database_url)
    fd, dump_name = tempfile.mkstemp(prefix="backup-", suffix=".pgdump", dir=output.parent)
    os.close(fd)
    dump = Path(dump_name)
    try:
        _run(["pg_dump", "--format=custom", "--file", str(dump)], env)
        files = [("database.pgdump", dump)] + [
            ("private/" + str(p.relative_to(private_dir)), p) for p in _safe_files(private_dir)
        ]
        manifest: dict[str, Any] = {"version": 1, "created_at": datetime.now(UTC).isoformat(),
                                    "contains_credentials": False, "files": {}}
        for name, path in files:
            manifest["files"][name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                       "bytes": path.stat().st_size}
        temp = output.with_suffix(output.suffix + ".tmp")
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                payload = json.dumps(manifest, sort_keys=True).encode()
                info = tarfile.TarInfo("manifest.json")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
                for name, path in files:
                    archive.add(path, arcname=name, recursive=False)
        temp.replace(output)
        return manifest
    finally:
        dump.unlink(missing_ok=True)


def validate_backup(archive_path: Path) -> tuple[dict, dict[str, bytes]]:
    if not archive_path.is_file():
        raise BackupError("backup_missing")
    contents: dict[str, bytes] = {}
    total = 0
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > 10001:
            raise BackupError("backup_too_many_entries")
        for member in members:
            name = member.name
            if (not member.isfile() or name.startswith("/") or ".." in Path(name).parts
                    or (name != "manifest.json" and name != "database.pgdump"
                        and not name.startswith("private/"))):
                raise BackupError("unsafe_backup_entry")
            if member.size > 5 * 1024**3:
                raise BackupError("backup_entry_too_large")
            total += member.size
            if total > 10 * 1024**3 or name in contents:
                raise BackupError("backup_size_or_duplicate")
            stream = archive.extractfile(member)
            if stream is None:
                raise BackupError("backup_read_failed")
            data = stream.read(member.size + 1)
            if len(data) != member.size:
                raise BackupError("backup_size_mismatch")
            contents[name] = data
    try:
        manifest = json.loads(contents.pop("manifest.json"))
        if manifest["version"] != 1 or manifest["contains_credentials"] is not False:
            raise BackupError("unsupported_backup_version")
        if set(manifest["files"]) != set(contents) or "database.pgdump" not in contents:
            raise BackupError("backup_manifest_mismatch")
        for name, data in contents.items():
            expected = manifest["files"][name]
            if expected["bytes"] != len(data) or expected["sha256"] != hashlib.sha256(data).hexdigest():
                raise BackupError("backup_checksum_mismatch")
    except (KeyError, TypeError, ValueError) as exc:
        raise BackupError("invalid_backup_manifest") from exc
    return manifest, contents


def restore_backup(archive_path: Path, target_url: str, target_private_dir: Path) -> dict:
    manifest, contents = validate_backup(archive_path)
    if target_private_dir.exists():
        raise BackupError("restore_private_target_exists")
    env, target_name = _pg_env(target_url)
    # createdb refuses an existing target, protecting a running database.
    create_env = env.copy()
    create_env["PGDATABASE"] = "postgres"
    _run(["createdb", target_name], create_env)
    target_private_dir.mkdir(mode=0o700, parents=True)
    target_private_dir.chmod(0o700)
    dump = target_private_dir / "restore.pgdump"
    try:
        dump.write_bytes(contents.pop("database.pgdump"))
        dump.chmod(0o600)
        _run(["pg_restore", "--no-owner", "--no-acl", "--exit-on-error",
              "--dbname", target_name, str(dump)], env)
        for name, data in contents.items():
            path = target_private_dir / name.removeprefix("private/")
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.parent.chmod(0o700)
            path.write_bytes(data)
            path.chmod(0o600)
        return manifest
    finally:
        dump.unlink(missing_ok=True)
