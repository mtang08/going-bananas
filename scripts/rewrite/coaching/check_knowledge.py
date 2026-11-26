"""Verify the Go knowledge selection against every Python coaching operation."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    from app.services.knowledge import (
        SUPPORTED_OPERATIONS,
        load_route,
        verify_selection,
    )

    routes = [load_route(op).routes for op in sorted(SUPPORTED_OPERATIONS)]
    from app.services.knowledge import RECIPE_FILE, kb_index

    routes.extend(
        [[], [{"path": RECIPE_FILE, "record_ids": sorted(kb_index().recipe_ids)[:2]}]]
    )
    cases = []
    for route in routes:
        verified = verify_selection(tuple(route))
        cases.append(
            {
                "selection": route,
                "digest": verified["digest"],
                "records": verified["selected_records"],
                "policy_ids": sorted(verified["policy_ids"]),
                "recipe_ids": sorted(verified["recipe_ids"]),
                "evidence_ids": sorted(verified["evidence_ids"]),
            }
        )
    with tempfile.TemporaryDirectory(dir=ROOT / "private") as scratch:
        p = Path(scratch) / "cases.json"
        p.write_text(json.dumps(cases))
        subprocess.run(
            [
                "go",
                "test",
                "-count=1",
                "-run",
                "^TestKnowledgePython$",
                "./internal/coaching",
            ],
            cwd=ROOT / "backend-go",
            check=True,
            env={**os.environ, "COACHING_KB_REFERENCE": str(p)},
        )
    print(f"Verified {len(cases)} current Python knowledge selections.")


if __name__ == "__main__":
    main()
