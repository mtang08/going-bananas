from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.calendar_models import CalendarSessionRevision
from app.domain.running_interruption import RunningInterruption
from app.services.running_interruption import _bounded_affected

START = date(2026, 11, 25)


def test_review_only_episode_remains_unavailable_after_reassessment_date():
    interruption = RunningInterruption(reason="illness", starts_on=START, review_on=START)
    assert interruption.phase_on(START - timedelta(days=1)) == "planned"
    assert interruption.phase_on(START) == "review_due"
    assert interruption.unavailable_on(START + timedelta(days=14))


def test_known_return_day_is_available_and_does_not_end_record():
    return_day = START + timedelta(days=3)
    interruption = RunningInterruption(reason="travel", starts_on=START, return_on=return_day)
    assert interruption.phase_on(START) == "paused"
    assert interruption.unavailable_on(START)
    assert interruption.unavailable_on(return_day - timedelta(days=1))
    assert interruption.phase_on(return_day) == "returning"
    assert not interruption.unavailable_on(return_day)
    assert interruption.phase_on(return_day + timedelta(days=5)) == "returning"


@pytest.mark.parametrize(
    ("return_on", "review_on"),
    [(None, None), (START, None), (None, START - timedelta(days=1)), (START + timedelta(days=1), START)],
)
def test_interruption_requires_one_valid_boundary(return_on, review_on):
    with pytest.raises(ValidationError):
        RunningInterruption(reason="other", starts_on=START, return_on=return_on, review_on=review_on)


def test_affected_preview_fills_spare_rows_with_most_recent_past_runs():
    interruption = RunningInterruption(reason="travel", starts_on=START, review_on=START)
    days = [START + timedelta(days=offset) for offset in range(11)]
    rows = [CalendarSessionRevision(local_date=day) for day in days]

    preview, omitted = _bounded_affected(rows, interruption, days[8])

    assert [row["local_date"] for row in preview] == days[3:]
    assert omitted == 3
