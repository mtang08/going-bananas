"""Language-independent fixtures for identities persisted before the Go rewrite."""

import json
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

import pytest

from app.metrics import contract
from app.services import decision_inputs


@pytest.mark.parametrize(
    "name,canonical,digest",
    [
        ("coaching", decision_inputs.canonical_json, decision_inputs.digest),
        ("metrics", contract.canonical_json, contract.sha256_json),
    ],
)
def test_persisted_hash_bytes(name, canonical, digest):
    fixture = json.loads((Path(__file__).parents[1] / "fixtures" / "canonical-hashes.json").read_text())
    value = fixture["input"]
    value["instants"] = [datetime.fromisoformat(instant) for instant in value["instants"]]
    value["day"] = date.fromisoformat(value["day"])
    value["id"] = UUID(value["id"])
    assert canonical(value) == fixture["expected"][name]["canonical_json"]
    assert digest(value) == fixture["expected"][name]["sha256"]
