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
