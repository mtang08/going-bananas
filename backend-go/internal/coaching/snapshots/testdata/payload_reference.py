"""Compare all projections exercised by the existing synthetic snapshot suite."""
import contextlib
import dataclasses
import sys
from pathlib import Path

import pytest

backend = Path(__file__).resolve().parents[5] / "backend"
sys.path.insert(0, str(backend))
from app.services.decision_inputs import canonical_json

cases = []


class Capture:
    def pytest_collection_modifyitems(self, items):
        module = items[0].module
        project = module.build_payload

        def capture(inputs, operation):
            result = project(inputs, operation)
            cases.append({"inputs": dataclasses.asdict(inputs), "operation": operation, "expected": result})
            return result

        module.build_payload = capture


with contextlib.redirect_stdout(sys.stderr):
    result = pytest.main(["-q", str(backend / "tests/unit/test_snapshot.py")], plugins=[Capture()])
if result:
    sys.exit(result)
print(canonical_json(cases))
