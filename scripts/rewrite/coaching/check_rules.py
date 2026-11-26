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
                payload=doc.model_dump(mode="json", exclude_unset=True),
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

    subsets = []
    reference_subset = validation.validate_subset

    def capture_subset(
        doc, accepted_ids, accept_block_change, accepted_anchor_keys, ctx
    ):
        issues = reference_subset(
            doc, accepted_ids, accept_block_change, accepted_anchor_keys, ctx
        )
        case = rule_inputs(doc, ctx)
        case.update(
            document=doc.model_dump(mode="json"),
            payload=doc.model_dump(mode="json", exclude_unset=True),
            expected=[i.to_json() for i in issues],
            selection=dict(
                accept_change_ids=sorted(accepted_ids),
                accept_block_change=accept_block_change,
                accept_anchor_changes=sorted(accepted_anchor_keys),
            ),
            index=dict(
                PolicyIDs=dict.fromkeys(ctx.kb.policy_ids, True),
                RecipeIDs=dict.fromkeys(ctx.kb.recipe_ids, True),
                EvidenceIDs=dict.fromkeys(ctx.kb.evidence_ids, True),
            ),
        )
        try:
            subsets.append(json.dumps(case, default=str, allow_nan=False))
        except ValueError:
            pass  # The submission canonicalizer rejects nonfinite numbers.
        return issues

    with (
        patch.object(validation, "_rules", capture),
        patch.object(validation, "validate_subset", capture_subset),
    ):
        result = pytest.main(["-q", str(ROOT / "backend/tests/unit/test_proposals.py")])
    if result or not cases or not subsets:
        raise SystemExit(result or "empty corpus")
    with tempfile.TemporaryDirectory(dir=ROOT / "private") as scratch:
        path = Path(scratch) / "rules.json"
        path.write_text("[" + ",\n".join(cases + subsets) + "]")
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
        f"Matched ordered validation issues on {len(cases)} full proposals and {len(subsets)} partial selections."
    )


if __name__ == "__main__":
    main()
