"""Replay ordered validation issues from the Python proposal suite through Go."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from reference_validation import rule_inputs

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    from app.services.proposals import validation

    cases = []
    reference = validation._rules

    def capture(doc, ctx, *, exception_checks=True):
        issues = reference(doc, ctx, exception_checks=exception_checks)
        if exception_checks:
            case = rule_inputs(doc, ctx)
            case.update(
                document=doc.model_dump(mode="json"),
                expected=[i.to_json() for i in issues],
                index={
                    key: {v: True for v in vals}
                    for key, vals in [
                        ("PolicyIDs", ctx.kb.policy_ids),
                        ("RecipeIDs", ctx.kb.recipe_ids),
                        ("EvidenceIDs", ctx.kb.evidence_ids),
                    ]
                },
            )
            try:
                cases.append(json.dumps(case, default=str, allow_nan=False))
            except ValueError:
                # The proposal canonicalizer rejects non-finite input before submission.
                pass
        return issues

    with patch.object(validation, "_rules", capture):
        result = pytest.main(["-q", str(ROOT / "backend/tests/unit/test_proposals.py")])
    if result or not cases:
        raise SystemExit(result or "empty corpus")
    with tempfile.TemporaryDirectory(dir=ROOT / "private") as scratch:
        path = Path(scratch) / "rules.json"
        path.write_text("[" + ",\n".join(cases) + "]")
        subprocess.run(
            [
                "go",
                "test",
                "-count=1",
                "-run",
                "^TestPythonRules$",
                "./internal/coaching/drafts",
            ],
            cwd=ROOT / "backend-go",
            env={**os.environ, "COACHING_RULES_REFERENCE": str(path)},
            check=True,
        )
    print(
        f"Matched ordered validation issues on {len(cases)} Python proposal rule calls."
    )


if __name__ == "__main__":
    main()
