"""Bridge the established local CLI and skill to the synthetic Go draft writer."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def run_draft(command: str, payload: dict[str, Any], proposal_id: str | None) -> tuple[dict, int]:
    root = Path(__file__).resolve().parents[2]
    arguments = ["go", "run", "./cmd/coaching", command, "-repo", str(root)]
    if proposal_id:
        arguments += ["-id", proposal_id]
    try:
        process = subprocess.run(
            arguments,
            cwd=root / "backend-go",
            input=json.dumps(payload, ensure_ascii=False, allow_nan=False),
            text=True,
            capture_output=True,
            timeout=150,
            check=False,
        )
    except ValueError:
        return {
            "proposal_id": proposal_id,
            "revision": None,
            "status": "invalid",
            "errors": [{"code": "V1.schema", "path": "", "message": "File is not a JSON object"}],
        }, 2
    if process.returncode == 0:
        receipt = json.loads(process.stdout)
        return {
            "proposal_id": receipt["proposal_id"],
            "revision": receipt["revision"],
            "status": receipt["status"],
            "errors": receipt["issues"],
        }, {"pending": 0, "stale": 3}.get(receipt["status"], 2)
    # go run appends its own exit-status line after the binary's JSON error.
    for line in process.stderr.splitlines():
        if not line.startswith("{"):
            continue
        failure = json.loads(line)
        detail = failure.get("error", failure)
        code = detail["code"]
        if code == "knowledge_unavailable":
            return {"error": code}, 4
        issues = failure.get("issues") or [{"code": code, "path": "", "message": detail["message"]}]
        return {
            "proposal_id": proposal_id,
            "revision": None,
            "status": "invalid",
            "error": code,
            "errors": issues,
        }, 3 if code == "stale_evidence" else 2
    raise RuntimeError("Native coaching command did not return a receipt")
