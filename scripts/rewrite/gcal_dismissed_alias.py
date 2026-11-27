"""Verify stable trip identities as duplicate synthetic calendar flights change."""

from copy import deepcopy


def dismissed_alias(run, env, connect):
    outbound = {
        "id": "alias-original",
        "eventType": "default",
        "status": "confirmed",
        "summary": "Flight to Alias City (ZZ 721)",
        "start": {
            "dateTime": "2027-02-12T09:00:00-05:00",
            "timeZone": "America/New_York",
        },
        "end": {
            "dateTime": "2027-02-12T12:00:00-08:00",
            "timeZone": "America/Los_Angeles",
        },
    }
    gmail = dict(outbound, id="alias-gmail", eventType="fromGmail")
    returning = deepcopy(gmail)
    returning.update(
        id="alias-return",
        summary="Flight to Synthetic Home (ZZ 722)",
        start={
            "dateTime": "2027-02-17T09:00:00-08:00",
            "timeZone": "America/Los_Angeles",
        },
        end={"dateTime": "2027-02-17T17:00:00-05:00", "timeZone": "America/New_York"},
    )

    def state(env):
        with connect(env) as db:
            return db.execute("""
                SELECT t.id,t.status,t.version,t.detected,array_agg(e.google_event_id ORDER BY l.seq)
                FROM trips t JOIN trip_legs l ON t.id=l.trip_id JOIN gcal_events e ON e.id=l.gcal_event_id
                WHERE t.start_date='2027-02-12' GROUP BY t.id""").fetchone()

    run(10, [{"items": [outbound]}])
    trip_id = state(env)[0]
    preferred = run(11, [{"items": [gmail]}])
    assert preferred["trips"] == {
        "created": 0,
        "updated": 1,
        "flagged": 0,
        "deleted": 0,
    }
    row = state(env)
    assert row[0] == trip_id and row[-1] == ["alias-gmail"]
    with connect(env) as db:
        db.execute(
            "UPDATE trips SET status='dismissed',version=version+1 WHERE id=%s",
            (trip_id,),
        )
    before = state(env)
    result = run(12, [{"items": [outbound, returning]}])
    assert not any(result["trips"].values())
    row = state(env)
    assert row[:-1] == before[:-1]
    assert row[-1] == ["alias-gmail", "alias-original", "alias-return"]
    run(13, [{"items": [outbound, returning]}])
    assert state(env) == row
