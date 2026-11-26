"""Compare the Go activity reader with actual FastAPI responses on independent synthetic schemas."""
import json
import sys
from pathlib import Path

from check_aerobic import seed as seed_runs
from check_recovery import compare, seed as seed_recovery
from check_self_reports import uid


def seed(env):
    seed_runs(env)
    seed_recovery(env)


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
