"""Run the existing strong-import CLI through the native importer."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from app.config import Settings

_SAFE_ERRORS = {
    "csv_copy_mismatch",
    "csv_field_too_large",
    "csv_io_error",
    "csv_too_large",
    "empty_csv",
    "inconsistent_duration",
    "invalid_date",
    "invalid_duration",
    "invalid_number",
    "invalid_set_order",
    "invalid_utf8",
    "malformed_row",
    "missing_name",
    "mixed_source_account",
    "too_many_rows",
    "unsupported_columns",
}


def run_import(settings: Settings, path: Path, *, apply: bool) -> dict:
    backend = os.environ.get("GOING_BANANAS_BACKEND") or ("python" if settings.app_mode == "real" else "go")
    if backend == "python":
        from app.db import SessionLocal
        from app.services.strong_import import import_strong_csv

        with SessionLocal.begin() as session:
            return import_strong_csv(session, settings.private_dir, path, apply=apply)
    if backend != "go":
        raise ValueError("invalid_backend")
    command = ["go", "run", "./cmd/going-bananas", "strong-import"]
    if apply:
        command.append("-apply")
    command += ["--", str(path.resolve())]
    env = {
        **os.environ,
        "APP_MODE": settings.app_mode,
        "DATABASE_URL": settings.database_url,
        "PRIVATE_DIR": str(settings.private_dir),
    }
    try:
        process = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[2] / "backend-go",
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise ValueError("strong_import_unavailable") from exc
    if process.returncode:
        # Go emits one safe code for input and source conflicts. Other stderr
        # may include local paths or database details and stays private.
        code = next((s for s in process.stderr.splitlines() if s in _SAFE_ERRORS), None)
        raise ValueError(code or "strong_import_failed")
    return json.loads(process.stdout)["summary"]
