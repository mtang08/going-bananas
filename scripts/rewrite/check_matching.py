"""Compare every plan_matches call in the Python unit suite with Go's pure matcher.

From the repository root, run: uv run --project backend python scripts/rewrite/check_matching.py
"""

import json
import os
import subprocess
import tempfile
from datetime import date
from functools import wraps
from inspect import signature
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "backend-go"


def json_value(value):
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Unsupported reference value: {type(value).__name__}")


class MatchingCalls:
    def __init__(self):
        self.cases = []

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_call(self, item):
        reference = item.module.plan_matches
        parameters = signature(reference)
        call_number = 0

        @wraps(reference)
        def capture(*args, **kwargs):
            nonlocal call_number
            call_number += 1
            inputs = parameters.bind(*args, **kwargs).arguments
            result = reference(*args, **kwargs)
            # Serialize now: subsequent calls in a test may mutate the same inputs.
            self.cases.append(
                json.dumps(
                    {
                        "name": f"{item.name}/{call_number}",
                        "input": inputs,
                        "result": result,
                    },
                    default=json_value,
                )
            )
            return result

        with patch.object(item.module, "plan_matches", capture):
            return (yield)


def main():
    calls = MatchingCalls()
    tests = ROOT / "backend/tests/unit/test_matching.py"
    status = pytest.main(["-q", str(tests)], plugins=[calls])
    if status or not calls.cases:
        raise SystemExit(status or "No Python matching calls captured")
    scratch = ROOT / "private"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="matching-parity-", dir=scratch
    ) as directory:
        corpus = Path(directory) / "reference.json"
        corpus.write_text("[" + ",\n".join(calls.cases) + "]\n")
        subprocess.run(
            [
                "go",
                "test",
                "-count=1",
                "-run",
                "^TestPythonMatchingCorpus$",
                "./internal/matching",
            ],
            cwd=MODULE,
            env={**os.environ, "MATCHING_REFERENCE_JSON": str(corpus)},
            check=True,
        )
    print(
        f"Matched the complete outputs of {len(calls.cases)} Python plan_matches calls."
    )


if __name__ == "__main__":
    main()
