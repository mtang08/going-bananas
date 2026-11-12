from datetime import date, timedelta
from uuid import UUID, uuid5

from app.services.matching import EXTRA_NAMESPACE, plan_matches

DAY = date(2026, 11, 19)
P1 = "00000000-0000-0000-0000-000000000001"
P2 = "00000000-0000-0000-0000-000000000002"
R1 = "00000000-0000-0000-0000-000000000011"
R2 = "00000000-0000-0000-0000-000000000012"


def plan(uid: str, day: date = DAY, kind: str = "run") -> dict:
    return {"session_uid": uid, "local_date": day, "kind": kind}


def actual(key: str, day: date = DAY, kind: str = "run") -> dict:
    return {"subject_key": key, "local_date": day, "kind": kind}


def test_one_pair_and_ambiguity() -> None:
    one = plan_matches([DAY], [plan(P1)], [actual(R1)], [])
    assert one["links"] == [{"session_uid": P1, "subject_key": R1, "match_method": "auto_same_day"}]
    assert plan_matches([DAY], [plan(P1)], [actual(R1), actual(R2)], [])["links"] == []
    assert plan_matches([DAY], [plan(P1), plan(P2)], [actual(R1)], [])["links"] == []


def test_explicit_preserved_and_move_requires_confirmation() -> None:
    protected = plan_matches([DAY], [plan(P1)], [actual(R1)], [
        {"session_uid": P1, "subject_key": R1, "match_method": "explicit", "status": "unknown"}])
    assert protected["links"] == protected["delete_auto_session_uids"] == []
    moved = plan_matches([DAY, DAY + timedelta(days=1)], [plan(P1)],
                         [actual(R1, DAY + timedelta(days=1))], [])
    assert moved["links"] == []
    assert moved["candidates"][P1][0]["reason"] == "MOVE_CANDIDATE"


def test_extra_uuid_repeat_and_strength() -> None:
    result = plan_matches([DAY], [], [actual(R1)], [])
    expected = str(uuid5(EXTRA_NAMESPACE, f"extra:{R1}"))
    assert result["extras"][0]["session_uid"] == expected
    assert result == plan_matches([DAY], [], [actual(R1)], [])
    strong = f"strong:{UUID(int=51)}"
    strength = plan_matches([DAY], [plan(P1, kind="strength")], [actual(strong, kind="strength")], [])
    assert strength["links"][0]["subject_key"] == strong


def test_stale_auto_and_adjacent_unique_link() -> None:
    stale = plan_matches([DAY, DAY + timedelta(days=1)], [plan(P1)],
                         [actual(R1, DAY + timedelta(days=1))], [
        {"session_uid": P1, "subject_key": R1, "match_method": "auto_same_day", "status": "unknown"}])
    assert stale["delete_auto_session_uids"] == [P1]
    adjacent = plan_matches([DAY, DAY + timedelta(days=1)],
                            [plan(P1), plan(P2, DAY + timedelta(days=1))], [actual(R1)], [])
    assert adjacent["links"][0]["session_uid"] == P1
    assert adjacent["candidates"][P2] == []
