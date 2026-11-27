"""Compare calendar reads on a populated, shared, disposable PostgreSQL history."""

from datetime import date, timedelta
from http.client import HTTPConnection
import json
from pathlib import Path
import subprocess
import tempfile

import psycopg


def compare_calendar_views(env, ports):
    corpus = []
    def request(port, path):
        conn = HTTPConnection("127.0.0.1", int(port), timeout=15)
        try:
            conn.request("GET", "/api/v1/calendar" + path)
            response = conn.getresponse()
            body = json.loads(response.read())
            if "error" in body:
                assert body["error"].pop("request_id") == response.getheader("X-Request-ID")
            return response.status, body
        finally:
            conn.close()

    def compare(path, status=200):
        reference, candidate = [request(p, path) for p in ports]
        assert reference == candidate, (path, reference, candidate)
        assert reference[0] == status, (path, reference)
        if status == 200:
            corpus.append({"path": path, "envelope": reference[1]})
        return reference[1].get("data")

    assert compare("")["last_planned_date"] is None
    compare("/week")
    compare("/weekly-digest")
    compare("/weekly-projection")
    for query, status in [
        ("/diff", 422), ("/diff?from=no&to=", 422), ("/week?start=2026-03-03", 422),
        ("?version=9999999999", 404), ("?start=bad&end=bad&version=bad", 422),
        ("?start=2030-01-02&end=2030-01-01", 422),
    ]:
        compare(query, status)

    with psycopg.connect(env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"], autocommit=True) as db:
        assert db.execute("SELECT current_database(),current_schema()").fetchone()[1].startswith("go_parity_")
        day = date.today() + timedelta(days=4)
        db.execute("""INSERT INTO calendar_versions(id,number,parent_number,kind,actor,created_at)
                   SELECT gen_random_uuid(),i,i-1,'manual_edit','user','2026-03-01T12:05:02.123400Z'
                   FROM generate_series(1,3) i""")
        db.execute("UPDATE app_state SET calendar_head_version=3 WHERE id=1")
        db.execute("""INSERT INTO calendar_session_revisions(id,session_uid,revision,calendar_version_number,
                   local_date,slot,kind,intent,certainty,deleted,locked)
                   SELECT gen_random_uuid(),md5(uid)::uuid,rev,v,%s::date+offset_day,slot,'run',
                   intent,'provisional',deleted,locked FROM (VALUES
                   ('first',1,1,0,0,'easy',false,false),('first',2,2,3,0,'easy',false,false),
                   ('lock',1,1,2,1,'protected',false,true),('gone',1,2,1,1,'remove',false,false),
                   ('gone',2,3,1,1,'remove',true,false),('first',3,3,3,0,'shorter',false,false))
                   x(uid,rev,v,offset_day,slot,intent,deleted,locked)""", (day,))
        db.execute("""UPDATE calendar_session_revisions SET structure='[{"type":"warmup","duration_type":"time","duration_value":30},
                   {"type":"repeat","count":2,"steps":[{"type":"work","duration_type":"distance","duration_value":400,"target":{"modality":"speed","low":2,"high":3}},
                   {"type":"recovery","duration_type":"time","duration_value":60,"target":null}]}]',
                   brief='{"effort":{"rpe_low":2,"rpe_high":4,"feel":"easy"},"focus":[],"adjust_if":[{"when":"tired","then":"stop"}],"why":"routine"}'
                   WHERE intent='shorter'""")
        db.execute("""INSERT INTO profile_versions(id,version,effective_at,timezone,anchor_confirmed,
                   strength_days_confirmed,scheduled_strength_days,facts,preferences,unknowns)
                   VALUES(gen_random_uuid(),1,now(),'America/New_York',false,false,'[]',
                   jsonb_build_object('running_restriction',jsonb_build_object('starts_on',%s::date,
                   'pause_running',true,'source','athlete')),'{}','[]')""", (day,))
        db.execute("""INSERT INTO activities(id,start_at,original_start,local_date,sport,timer_s,distance_m,
                   canonical_revision,resolution_state,field_provenance)
                   SELECT md5('calendar-run-'||i)::uuid, (%s::date+i*interval '1 hour') AT TIME ZONE 'America/New_York',
                   'synthetic',%s::date,'running',111,444,1,'resolved','{}' FROM generate_series(1,3) i""",(day,day))
        db.execute("""INSERT INTO activity_annotations(id,activity_id,version,excluded)
                   VALUES(gen_random_uuid(),md5('calendar-run-3')::uuid,1,true)""")
        db.execute("""INSERT INTO session_completions(id,session_uid,activity_id,status,match_method,updated_at)
                   VALUES(gen_random_uuid(),md5('extra')::uuid,md5('calendar-run-1')::uuid,'extra','explicit',
                   '2026-03-01T23:59:07.000010Z'),(gen_random_uuid(),md5('first')::uuid,NULL,'skipped',
                   'user_marked','2026-03-02T00:00:00Z')""")
        bounds = f"?start={day}&end={day+timedelta(days=5)}"
        for version in (0,1,2,3):
            compare(bounds + f"&version=invalid&version={version}.0")
        view=compare(bounds)
        assert [r["intent"] for r in view["sessions"]] == ["protected","shorter"]
        assert all(r.get("running_restriction_conflict") for r in view["sessions"])
        assert len(view["recorded_runs"]) == 1 and len(view["completions"]) == 2
        assert compare("/diff?from=1&to=2")["changes"]
        for pair in ("0&to=3","3&to=0","2&to=3","3&to=3"):
            compare("/diff?from="+pair)
        compare("/diff?from=-1&to=3",404)
        compare("/weekly-projection")
        compare("/weekly-digest?week_start="+(day-timedelta(days=day.weekday())).isoformat())
        compare("/week?start="+(day-timedelta(days=day.weekday())).isoformat())
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(dir=root / "private") as temp:
        fixture = Path(temp) / "calendar-wire.json"
        fixture.write_text(json.dumps(corpus))
        subprocess.run(["go", "test", "-count=1", "./api/calendarwire"], cwd=root / "backend-go",
                       env={**env, "CALENDAR_WIRE_CASES":str(fixture)}, check=True)
    print("PASS calendar history, undo, restrictions, actuals, forward/reverse diffs and date validation",flush=True)
