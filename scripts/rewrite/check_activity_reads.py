"""Compare the Go activity reader with actual FastAPI responses on independent synthetic schemas."""
import json
import psycopg
from psycopg.types.json import Jsonb
import sys
from pathlib import Path

from check_aerobic import seed as seed_runs
from check_recovery import compare, seed as seed_recovery
from check_self_reports import uid


def seed(env):
    seed_runs(env)
    seed_recovery(env)

    with psycopg.connect(env["PROPOSAL_TEST_DATABASE_URL"],options=env["PGOPTIONS"]) as db:
        value={"n_planned":2,"n_completed":1,"step_completion_ratio":0.5,"cv_speed":None,"last_first_change_pct":None,"target_coverage":.89,"reps":[
            {"fully_completed":True,"speed_status":"available","mean_speed_mps":3.001,"actual_timer_s":200.0,"hr_median_bpm":151.5}]}
        db.execute("""INSERT INTO metric_results(id,metric_id,method_version,subject_type,subject_key,status,value,reason_codes,quality_flags,
                    source_refs,config_hash,dependency_hash,calculated_at,timezone) VALUES(%s,'work_interval_execution','v2','activity',%s,'partial',%s,
                    ARRAY['INCOMPLETE_WORK_STEPS'],'{}','{}','prior','fixture','2026-03-04','UTC')""",(uid(9950),uid(2000),Jsonb(value)))


def reference():
    from fastapi.testclient import TestClient
    from app.main import app
    client=TestClient(app)
    paths=[
        "/metrics/recovery?start=2026-03-24&end=2026-03-30",
        "/metrics/recovery?start=2026-03-30&end=2026-03-28",
        "/activities?start_date=2026-03-01&end_date=2026-03-30",
        "/activities?start_date=2026-03-01&end_date=2026-03-30&limit=2",
        "/activities?start_date=2026-03-01&end_date=2026-03-30&sport=treadmill_running",
        "/activities?start_date=2026-03-01&end_date=2026-03-30&cursor=bad",
        "/activities?limit=0","/activities?limit=201","/activities?limit=bad",
        "/activities/"+uid(2000),"/activities/"+uid(2999),
    ]
    paths.extend("/activities/"+uid(n)+"/workout-history" for n in [2000,2001,2003,2999])
    result=[]
    for path in paths:
        r=client.get("/api/v1"+path)
        body=r.json()
        if "error" in body:body["error"].pop("request_id",None)
        result.append({"path":path,"status":r.status_code,"body":body})
        if path.endswith("&limit=2") and body["data"]["next_cursor"]:
            import urllib.parse
            paths.append(path+"&cursor="+urllib.parse.quote(body["data"]["next_cursor"],safe=""))
    return result


if __name__=="__main__":
    if sys.argv[1:2]==["reference"]:Path(sys.argv[2]).write_text(json.dumps(reference()))
    else:compare(__file__,seed,"./internal/activityhttp","ACTIVITY_READ_CASES")
