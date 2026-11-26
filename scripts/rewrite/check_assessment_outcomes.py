"""Regenerate planned/actual outcome fixtures from calls in the Python unit suite."""
import argparse
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
FIXTURE = ROOT / "backend-go/internal/metrics/assessment/testdata/outcomes.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    options = parser.parse_args()
    filename = ROOT / "backend/tests/unit/metrics/test_planned_actual.py"
    spec = importlib.util.spec_from_file_location("assessment_reference", filename)
    suite = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(suite)
    native = suite.planned_actual_outcome
    cases = []
    for name, test in vars(suite).items():
        if not name.startswith("test_"):
            continue
        def capture(*args, **kwargs):
            inputs = inspect.signature(native).bind(*args, **kwargs).arguments
            expected = native(*args, **kwargs)
            cases.append(json.dumps(dict(test=name, input=inputs, expected=expected), default=str, separators=(",", ":")))
            return expected
        with patch.object(suite, "planned_actual_outcome", capture):
            test()
    fixture = "[\n" + ",\n".join(cases) + "\n]\n"
    if options.update:
        FIXTURE.write_text(fixture)
    elif FIXTURE.read_text() != fixture:
        raise SystemExit("Python planned/actual reference changed")
    subprocess.run(["go", "test", "-count=1", "-run", "TestPythonOutcomes", "./internal/metrics/assessment"], cwd=ROOT / "backend-go", check=True)
    print(f"Matched {len(cases)} Python assessment outcomes")


if __name__ == "__main__":
    main()
