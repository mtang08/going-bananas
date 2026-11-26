"""Replay actual successful interval scoring calls from the Python unit suite in Go."""

import dataclasses
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
import pytest
from app.metrics import intervals


def main():
    cases = []
    original = intervals.execution_outcome

    def capture(plan_steps, fit_steps, laps, stream, sport=None):
        result = original(plan_steps, fit_steps, laps, stream, sport)
        plans = [
            {
                "type": p.type,
                "duration_type": p.duration_type,
                "duration_value": p.duration_value,
                "expanded_step": p.step,
                "step_path": p.step_path,
                "repeat_index": p.repeat_index,
                "target": {
                    "modality": p.target_modality,
                    "low": p.target_low,
                    "high": p.target_high,
                },
            }
            for p in plan_steps
        ]
        fits = [
            {
                "Index": f.message_index,
                "Duration": f.duration_type,
                "Intensity": f.intensity,
                "Value": f.duration_value,
                "RepeatFrom": f.repeat_from,
                "RepeatCount": f.repeat_count,
            }
            for f in fit_steps
        ]
        inputs = [
            {
                k: (None if isinstance(v, float) and not math.isfinite(v) else v)
                for k, v in dataclasses.asdict(l).items()
            }
            for l in laps
        ]
        cases.append(
            {
                "steps": plans,
                "fit": fits,
                "laps": inputs,
                "stream": dataclasses.asdict(stream) if stream else None,
                "treadmill": sport == "treadmill_running",
                "expected": result,
            }
        )
        return result

    with patch.object(intervals, "execution_outcome", capture):
        code = pytest.main(
            ["-q", str(ROOT / "backend/tests/unit/metrics/test_intervals.py")]
        )
        if code:
            raise SystemExit(code)
    with tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp:
        fixture = Path(tmp) / "cases.json"
        fixture.write_text(json.dumps(cases, allow_nan=False))
        subprocess.run(
            ["go", "test", "-race", "-count=1", "./internal/metrics/intervals"],
            cwd=ROOT / "backend-go",
            env={**os.environ, "INTERVAL_SCORING": str(fixture)},
            check=True,
        )
    print(f"Compared {len(cases)} interval scoring calls")


if __name__ == "__main__":
    main()
