import pytest

from app.domain.athlete_facts import CLINICAL_RESTRICTION_KEY, clinical_restriction


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (None, None),
        ({}, None),
        ({"clinical_restriction": "No running"}, "No running"),
        ({"clinical_restriction": " none "}, None),
        ({"clinical_restriction": "Unknown"}, None),
        ({"clinical_restriction": ""}, None),
        ({"clinical_restriction": 5}, None),
        ({"clinician_restriction": "restricted"}, "restricted"),
        ({"clinical_restriction_active": True}, "restricted"),
        ({"clinical_restriction_active": False}, None),
        ({"clinical_restriction": "none", "clinician_restriction": "Walk only"}, "Walk only"),
        ({"clinical_restriction": "Bike only", "clinician_restriction": "Walk only"}, "Bike only"),
    ],
)
def test_clinical_restriction(facts, expected):
    assert clinical_restriction(facts) == expected


def test_clinical_restriction_key():
    assert CLINICAL_RESTRICTION_KEY == "clinical_restriction"


def test_review_without_confirmed_end_leaves_running_limit_in_effect():
    from datetime import date

    from app.domain.athlete_facts import running_restriction
    from app.domain.running_limits import restriction_conflict

    first = date(2026, 11, 17)
    review = date(2026, 11, 20)
    next_week = date(2026, 11, 23)
    limit = running_restriction(
        {
            "running_restriction": {
                "starts_on": first.isoformat(),
                "review_on": review.isoformat(),
                "pause_running": True,
                "source": "Athlete",
            },
        }
    )
    assert limit is not None
    assert not limit.applies_on(date(2026, 11, 16))
    assert limit.applies_on(first) and limit.applies_on(next_week)
    assert limit.snapshot_data(review)["needs_confirmation"]
    assert restriction_conflict(limit, {"kind": "rehab", "local_date": next_week}) is None
    assert "pauses running" in (restriction_conflict(limit, {"kind": "run", "local_date": next_week}) or "")


def test_no_quality_requires_compatible_recipe_and_structure():
    from datetime import date

    from app.domain.athlete_facts import RunningRestriction
    from app.domain.running_limits import restriction_conflict

    day = date(2026, 11, 17)
    limit = RunningRestriction(starts_on=day, ends_on=day, no_quality=True, source="Athlete")
    easy = {"kind": "run", "local_date": day, "recipe_id": "REC001"}
    quality = {**easy, "recipe_id": "REC003"}
    work = {"type": "work", "duration_type": "time", "duration_value": 60}
    mislabeled = {**easy, "structure": [{"type": "repeat", "count": 2, "steps": [work]}]}
    assert restriction_conflict(limit, easy) is None
    assert "excludes quality" in (restriction_conflict(limit, quality) or "")
    assert "excludes quality" in (restriction_conflict(limit, mislabeled) or "")
    assert restriction_conflict(limit, {**quality, "local_date": date(2026, 11, 18)}) is None
