from datetime import date

import pytest

from app.errors import AppError
from app.services import calendar

BRIEF = {
    "effort": {"rpe_low": 3, "rpe_high": 4, "feel": "conversational"},
    "focus": ["Relax shoulders"],
    "adjust_if": [{"when": "Calf tight", "then": "walk 5 min"}],
    "why": "Easy aerobic volume",
}


def _run(session, version):
    return next(row for row in calendar.state_at(session, version) if row["kind"] == "run")


def _modify(session, version, fields, *, actor="user"):
    edit = {"op": "modify", "session_uid": _run(session, version)["session_uid"], "fields": fields}
    return calendar.apply_edits(session, version, [edit], "Session edit", actor=actor)


def test_coach_edit_stores_brief(proposal_session):
    _modify(proposal_session, 1, {"brief": BRIEF}, actor="coach")
    assert _run(proposal_session, 2)["brief"] == BRIEF


@pytest.mark.parametrize(("actor", "brief"), [("user", BRIEF), ("coach", "free text")])
def test_brief_requires_coach_and_object_or_null(proposal_session, actor, brief):
    with pytest.raises(AppError) as exc:
        _modify(proposal_session, 1, {"brief": brief}, actor=actor)
    assert exc.value.code == "invalid_session_fields"


@pytest.mark.parametrize(
    ("actor", "changes"),
    [
        (
            "user",
            {
                "structure": [{"type": "work", "duration_type": "time", "duration_value": 900}],
                "recipe_id": None,
                "custom": True,
            },
        ),
        ("coach", {"intent": "Easy aerobic"}),
    ],
)
def test_rework_without_brief_clears_it(proposal_session, actor, changes):
    _modify(proposal_session, 1, {"brief": BRIEF}, actor="coach")
    _modify(proposal_session, 2, changes, actor=actor)
    assert _run(proposal_session, 3)["brief"] is None


def test_athlete_notes_edit_keeps_brief(proposal_session):
    _modify(proposal_session, 1, {"brief": BRIEF}, actor="coach")
    _modify(proposal_session, 2, {"notes": "Felt flat"})
    row = _run(proposal_session, 3)
    assert row["brief"] == BRIEF
    assert row["notes"] == "Felt flat"


@pytest.mark.parametrize(("changes", "expected_brief"), [({}, BRIEF), ({"intent": "Recovery run"}, None)])
def test_move_clears_brief_only_when_session_changes(proposal_session, changes, expected_brief):
    _modify(proposal_session, 1, {"brief": BRIEF}, actor="coach")
    uid = _run(proposal_session, 2)["session_uid"]
    new_date = date(2026, 11, 28)
    edit = {"op": "move", "session_uid": uid, "fields": {"local_date": new_date, **changes}}
    calendar.apply_edits(proposal_session, 2, [edit], "Move run")

    row = _run(proposal_session, 3)
    assert row["local_date"] == new_date
    assert row["brief"] == expected_brief


def test_coach_rework_preserves_athlete_notes(proposal_session):
    _modify(proposal_session, 1, {"notes": "Felt flat"})
    _modify(proposal_session, 2, {"intent": "Recovery run", "brief": BRIEF}, actor="coach")
    assert _run(proposal_session, 3)["notes"] == "Felt flat"
    with pytest.raises(AppError) as exc:
        _modify(proposal_session, 3, {"notes": "Coach text"}, actor="coach")
    assert exc.value.code == "invalid_session_fields"
