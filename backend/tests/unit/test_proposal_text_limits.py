import pytest
from pydantic import ValidationError

from app.services.proposals.schema import (
    BlockVersionFields,
    Effort,
    Indicator,
    NextCheck,
    ProposalDoc,
    Rule,
    SessionBrief,
    SessionFields,
    Target,
    Why,
    parse_document,
)

SNAP = "00000000-0000-0000-0000-000000000200"
BRIEF = {"effort": {"rpe_low": 6, "rpe_high": 7, "feel": "controlled"}, "why": "Holding the dose"}


def doc(**overrides) -> dict:
    base = {
        "schema_version": "coach_proposal.v2",
        "operation": "review_rolling_plan",
        "snapshot_id": SNAP,
        "base_calendar_version": 1,
        "base_block_version_id": None,
        "headline": "Keep the week",
        "why": [{"kind": "observation", "text": "Runs went to plan"}],
        "next_check": {"on": "2026-11-23", "check": "Easy run feel"},
        "confidence": {"decision": "high", "evidence": "moderate", "data": "moderate"},
        "changes": [],
        "evidence_ids": [],
        "policy_ids": [],
        "recipe_ids": [],
        "skill_version": "running-coach.v1",
    }
    return {**base, **overrides}


def paths(raw: dict) -> list[str]:
    return [issue.path for issue in parse_document(raw)[1]]


def test_minimal_v2_document_parses():
    assert parse_document(doc())[1] == []


@pytest.mark.parametrize(("field", "limit"), [("headline", 100), ("coach_note", 400)])
def test_doc_text_limits(field, limit):
    assert paths(doc(**{field: "x" * limit})) == []
    assert paths(doc(**{field: "x" * (limit + 1)})) == [field]


def test_doc_list_limits():
    why = {"kind": "observation", "text": "Runs went to plan"}
    assert paths(doc(why=[])) == ["why"]
    assert paths(doc(why=[why] * 6)) == ["why"]
    assert paths(doc(uncertainty=["Unknown"] * 3)) == ["uncertainty"]
    assert paths(doc(change_triggers=[{"when": "Hard", "then": "Slow"}] * 4)) == ["change_triggers"]


def test_typed_text_limits():
    Why(kind="research", text="w" * 160)
    Rule(when="w" * 90, then="t" * 90)
    with pytest.raises(ValidationError):
        Why(kind="research", text="w" * 161)
    with pytest.raises(ValidationError):
        Rule(when="w" * 91, then="t")
    with pytest.raises(ValidationError):
        NextCheck(on="2026-11-23", check="c" * 121)
    with pytest.raises(ValidationError):
        Indicator(source="key_sessions", label="l" * 61, progress_when="p")
    with pytest.raises(ValidationError):
        Target(modality="effort", effort_cue="e" * 61)


def test_effort_order_and_bounds():
    with pytest.raises(ValidationError, match="rpe_low must not exceed rpe_high"):
        Effort(rpe_low=7, rpe_high=6, feel="x")
    with pytest.raises(ValidationError):
        Effort(rpe_low=1, rpe_high=11, feel="x")


@pytest.mark.parametrize(
    "overrides",
    [
        {"why": "y" * 121},
        {"focus": ["cue"] * 3},
        {"adjust_if": [{"when": "Hard", "then": "Slow"}] * 3},
    ],
)
def test_brief_limits(overrides):
    with pytest.raises(ValidationError):
        SessionBrief.model_validate({**BRIEF, **overrides})


def test_session_intent_cap_and_notes_rejected():
    SessionFields(intent="i" * 60)
    with pytest.raises(ValidationError):
        SessionFields(intent="i" * 61)
    with pytest.raises(ValidationError):
        SessionFields.model_validate({"notes": "x"})


def test_block_limits():
    fields = {
        "status": "active",
        "objective": "o" * 80,
        "why": [{"kind": "inference", "text": "Ready"}],
        "maintained_qualities": [],
        "non_goals": [],
        "eligible_recipe_ids": [],
        "progression_dimension": "none",
        "constraints": [],
        "start_date": "2026-11-16",
        "review_date": "2026-12-13",
        "indicators": [],
        "early_review_triggers": [],
        "objective_status": "unresolved",
    }
    BlockVersionFields.model_validate(fields)
    indicator = {"source": "key_sessions", "label": "Tempo control", "progress_when": "RPE stays under 7"}
    for overrides in ({"objective": "o" * 81}, {"why": []}, {"indicators": [indicator] * 5}):
        with pytest.raises(ValidationError):
            BlockVersionFields.model_validate({**fields, **overrides})


def test_reason_cap():
    change = {"change_id": "c1", "op": "delete", "session_uid": SNAP, "reason": "r" * 121}
    assert paths(doc(changes=[change])) == ["changes.0.reason"]


def test_strength_omission_marker_parses_without_brief():
    marker = {
        "change_id": "c1",
        "op": "add",
        "after": {"local_date": "2026-11-24", "kind": "rest", "intent": "Full body A"},
        "material_flags": ["strength_omission"],
        "reason": "Travel prevents the gym session",
    }
    assert paths(doc(changes=[marker])) == []
    assert paths(doc(changes=[{**marker, "reason": "r" * 121}])) == ["changes.0.reason"]


def test_json_schema_shows_limits():
    properties = ProposalDoc.model_json_schema()["properties"]
    assert properties["headline"]["maxLength"] == 100
    assert "summary" not in properties
