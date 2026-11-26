"""Replay proposal schema inputs from the Python tests against the Go parser."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    from app.services.proposals import schema, validation

    parse = schema.parse_document
    cases = []

    def capture(raw):
        doc, issues = parse(raw)
        try:
            wire = json.loads(json.dumps(raw, default=str, allow_nan=False))
        except ValueError:
            return doc, issues
        normalized, expected = parse(wire)
        cases.append(
            dict(
                input=wire,
                document=normalized.model_dump(mode="json") if normalized else None,
                payload=normalized.model_dump(mode="json", exclude_unset=True)
                if normalized
                else None,
                issues=[i.to_json() for i in expected],
            )
        )
        return doc, issues

    with (
        patch.object(validation, "parse_document", capture),
        patch.object(schema, "parse_document", capture),
    ):
        result = pytest.main(["-q", str(ROOT / "backend/tests/unit/test_proposals.py")])
    if result or not cases:
        raise SystemExit(result or "empty schema corpus")
    with tempfile.TemporaryDirectory(dir=ROOT / "private") as scratch:
        path = Path(scratch) / "schema.json"
        path.write_text(json.dumps(cases))
        subprocess.run(
            [
                "go",
                "test",
                "-count=1",
                "-run",
                "^TestPythonSchema$",
                "./internal/coaching/drafts",
            ],
            cwd=ROOT / "backend-go",
            env={**os.environ, "COACHING_SCHEMA_REFERENCE": str(path)},
            check=True,
        )
    print(
        f"Matched {len(cases)} authored documents, expanded defaults and schema issue lists."
    )


if __name__ == "__main__":
    main()
