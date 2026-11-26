"""Capture the synthetic Python rule suite's inputs and full decisions for Go parity."""
import dataclasses
import gzip
import importlib.util
import itertools
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
TARGET = ROOT / "backend-go/internal/exceptions/testdata/rules.json.gz"


def encode(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, datetime):
        return obj.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, frozenset):
        return sorted(obj)
    raise TypeError(type(obj).__name__)


def main():
    spec = importlib.util.spec_from_file_location("synthetic_rules", BACKEND / "tests/unit/test_exception_rules.py")
    suite = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(suite)
    reference = suite.detect
    captured = {}
    ids = itertools.count(1)

    def record(inputs):
        result = reference(inputs)
        key = json.dumps(inputs, default=encode, sort_keys=True)
        captured.setdefault(key, {"name": name, "input": inputs, "expected": result})
        return result

    with patch.object(suite, "detect", record), patch.object(suite, "uuid4", lambda: UUID(int=next(ids))):
        for name, test in vars(suite).items():
            if name.startswith("test_"):
                test()
    codes = {c.rule_code for row in captured.values() for c in row["expected"]}
    assert codes == {code for code, _ in suite.TABLE}
    data = json.dumps(list(captured.values()), default=encode, sort_keys=True, separators=(",", ":")).encode()
    TARGET.write_bytes(gzip.compress(data, mtime=0))
    print(f"Captured {len(captured)} synthetic inputs and all {len(codes)} rule codes.")


if __name__ == "__main__":
    main()
