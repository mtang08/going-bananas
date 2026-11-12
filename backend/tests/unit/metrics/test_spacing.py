from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.domain.analytics import utc_date_bounds
from app.metrics.spacing import _plan_ref, spacing_outcome

TZ = ZoneInfo("America/New_York")
DAY = date(2026, 11, 19)


def exposure(key: str, cls: str, day: date, start_low: datetime, start_high: datetime,
             end_low: datetime, end_high: datetime, source: str = "plan") -> dict:
    return {"subject_key": key, "classes": [cls], "local_date": day, "session_uid": key,
            "activity_id": None, "source": source, "start_low": start_low,
            "start_high": start_high, "end_low": end_low, "end_high": end_high}


def planned(key: str, cls: str, day: date) -> dict:
    start, end = utc_date_bounds(day, day, TZ.key)
    return exposure(key, cls, day, start, end, start, end)


def test_planned_day_ranges_and_nearest_class() -> None:
    current = planned("quality-thu", "quality", DAY)
    prev_long_end = datetime(2026, 11, 17, 13, tzinfo=UTC)
    prev_long = exposure("long-tue", "long", date(2026, 11, 17), prev_long_end, prev_long_end,
                         prev_long_end, prev_long_end, "activity")
    strength_end = datetime(2026, 11, 19, 1, tzinfo=UTC)
    strength = exposure("strength-wed", "lower_body_strength", date(2026, 11, 18),
                        strength_end, strength_end, strength_end, strength_end, "strong")
    next_long = planned("long-sun", "long", date(2026, 11, 22))
    result = spacing_outcome([current, prev_long, strength, next_long], DAY, TZ)
    row = next(s for s in result["value"]["sessions"] if s["subject_key"] == "quality-thu")
    assert row["hours_since"]["long"]["low"] == 40.0
    assert row["hours_since"]["long"]["high"] == 64.0
    assert row["hours_since"]["lower_body_strength"]["low"] == 4.0
    assert row["hours_since"]["lower_body_strength"]["high"] == 28.0
    assert row["hours_until"]["long"]["low"] == 48.0
    assert row["hours_until"]["long"]["high"] == 96.0
    sequence = result["value"]["sequence"]
    assert len(sequence) == 4
    assert sequence[0]["classes"] == ["long"]
    assert sequence[0]["subject_key"] == "long-tue"
    assert sequence[0]["start_low"].endswith("+00:00")


def test_dst_and_negative_overlap_and_no_self_pair() -> None:
    start, end = utc_date_bounds(date(2026, 11, 1), date(2026, 11, 1), TZ.key)
    assert (end - start).total_seconds() == 25 * 3600
    a = exposure("a", "quality", DAY, datetime(2026, 11, 19, 12, tzinfo=UTC),
                 datetime(2026, 11, 19, 12, tzinfo=UTC), datetime(2026, 11, 19, 14, tzinfo=UTC),
                 datetime(2026, 11, 19, 14, tzinfo=UTC))
    b = exposure("b", "long", DAY, datetime(2026, 11, 19, 13, tzinfo=UTC),
                 datetime(2026, 11, 19, 13, tzinfo=UTC), datetime(2026, 11, 19, 15, tzinfo=UTC),
                 datetime(2026, 11, 19, 15, tzinfo=UTC))
    result = spacing_outcome([a, b], DAY, TZ)
    assert result["value"]["gaps"][0]["hours_min"] == -1.0
    assert len(result["value"]["sessions"]) == 2
    duplicate = spacing_outcome([a, a, b, {**b, "classes": []}], DAY, TZ)
    assert len(duplicate["value"]["sequence"]) == 2
    assert len(duplicate["value"]["gaps"]) == 1


def test_plan_lineage_contains_slot_and_completion_hash() -> None:
    slot_id = uuid4()
    slot = SimpleNamespace(id=slot_id, version=3, lower_body_cost="high", active=True)
    session = SimpleNamespace(get=lambda *_args: slot)
    row = SimpleNamespace(id=uuid4(), revision=2, calendar_version_number=5, structure=None,
                          recipe_id=None, session_uid=uuid4(), strength_slot_id=slot_id)
    completion = SimpleNamespace(session_uid=row.session_uid, activity_id=None, strong_workout_id=uuid4(),
                                 manual_session_id=None, match_method="explicit", modification_reason=None,
                                 reason_note=None, input_version=4)
    ref = _plan_ref(session, row, completion)
    assert ref["revision"] == 2
    assert ref["strength_slot"] == {"id": str(slot_id), "version": 3,
                                    "lower_body_cost": "high", "active": True}
    assert len(ref["completion_association_hash"]) == 64
