"""Compare the Go activity reader with actual FastAPI responses on independent synthetic schemas."""

import json
import sys
from pathlib import Path

import psycopg
from check_aerobic import seed as seed_runs
from check_recovery import compare
from check_recovery import seed as seed_recovery
from check_self_reports import uid
from psycopg.types.json import Jsonb


def seed(env):
    seed_runs(env)
    seed_recovery(env)

    with psycopg.connect(
        env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]
    ) as db:
        value = {
            "n_planned": 2,
            "n_completed": 1,
            "step_completion_ratio": 0.5,
            "cv_speed": None,
            "last_first_change_pct": None,
            "target_coverage": 0.89,
            "reps": [
                {
                    "fully_completed": True,
                    "speed_status": "available",
                    "mean_speed_mps": 3.001,
                    "actual_timer_s": 200.0,
                    "hr_median_bpm": 151.5,
                }
            ],
        }
        db.execute(
            """INSERT INTO metric_results(id,metric_id,method_version,subject_type,subject_key,status,value,reason_codes,quality_flags,
                    source_refs,config_hash,dependency_hash,calculated_at,timezone) VALUES(%s,'work_interval_execution','v2','activity',%s,'partial',%s,
                    ARRAY['INCOMPLETE_WORK_STEPS'],'{}','{}','prior','fixture','2026-03-04','UTC')""",
            (uid(9950), uid(2000), Jsonb(value)),
        )

        db.execute(
            """INSERT INTO coverage_intervals(id,dataset,start_date,end_date,status,completed_at,fully_enumerated)
                    VALUES(%s,'activities','2026-03-01','2026-03-31','complete','2026-04-01T20:30:00.500Z',true)""",
            (uid(9949),),
        )
        db.execute("UPDATE session_completions SET updated_at='2026-03-04 13:00Z'")
        db.execute(
            "UPDATE activities SET end_at=start_at + interval '1 hour' WHERE id=%s",
            (uid(2000),),
        )
        db.execute(
            """INSERT INTO prompts(id,kind,activity_id,opens_at,closes_at,status)
           VALUES(%s,'delayed_symptom',%s,'2026-03-05','2026-03-06','open')""",
            (uid(9901), uid(2000)),
        )
        db.execute(
            """INSERT INTO checkins_v2(id,idempotency_key,kind,activity_id,prompt_id,observed_at,recorded_at,pain_reported)
           VALUES(%s,'response','delayed_followup',%s,%s,'2026-03-05T12:00Z','2026-03-05T13:00Z',true)""",
            (uid(9902), uid(2000), uid(9901)),
        )
        db.execute(
            """INSERT INTO symptom_reports(id,checkin_id,site,side,severity,timing)
           VALUES(%s,%s,'knee','left',2,'next_morning')""",
            (uid(9903), uid(9902)),
        )
        db.execute(
            """INSERT INTO session_rpe(id,activity_id,rpe,source,collected_at) VALUES(%s,%s,6,'manual','2026-03-06')""",
            (uid(9904), uid(2000)),
        )


def reference():
    from datetime import UTC, datetime

    from app.db import SessionLocal, get_session
    from app.main import app
    from fastapi.testclient import TestClient

    def session():
        with SessionLocal() as s:
            s.info["metrics_now"] = datetime(2026, 11, 26, 12, tzinfo=UTC)
            yield s

    app.dependency_overrides[get_session] = session
    client = TestClient(app)
    paths = [
        "/metrics/windows",
        "/metrics/windows?as_of=2026-03-30",
        "/metrics/windows?as_of=bad",
        "/metrics/long-runs?start=2026-03-01&end=2026-03-31",
        "/metrics/long-runs?start=2026-03-31&end=2026-03-01",
        "/metrics/long-runs",
        "/metrics/long-runs?start=bad",
        "/metrics/workout-progression",
        "/metrics/workout-progression?start=2026-03-01&end=2026-03-31",
        "/metrics/workout-progression?start=2026-03-01&end=2026-03-31&group_by=recipe",
        "/metrics/workout-progression?start=2026-03-01&end=2027-01-01",
        "/metrics/workout-progression?start=bad&end=bad&group_by=bad",
        "/metrics/recovery?start=2026-03-24&end=2026-03-30",
        "/metrics/recovery?start=2026-03-30&end=2026-03-28",
        "/activities?start_date=2026-03-01&end_date=2026-03-30",
        "/activities?start_date=2026-03-01&end_date=2026-03-30&limit=2",
        "/activities?start_date=2026-03-01&end_date=2026-03-30&sport=treadmill_running",
        "/activities?start_date=2026-03-01&end_date=2026-03-30&cursor=bad",
        "/activities?limit=0",
        "/activities?limit=201",
        "/activities?limit=bad",
        "/activities/" + uid(2000),
        "/activities/" + uid(2999),
    ]
    paths.extend(
        "/activities/" + uid(n) + "/workout-history" for n in [2000, 2001, 2003, 2999]
    )
    paths.extend(
        "/activities/" + uid(n) + "/execution" for n in [2000, 2001, 2003, 2999]
    )
    paths.extend(
        [
            "/metrics/recovery?start=x&end=banana",
            "/metrics/recovery?start=2026-15-32",
            "/activities/abc",
            "/activities/invalid-id",
            "/activities/abc/workout-history",
            "/activities?start_date=2026-03-02T00:00:00&end_date=2026-03-04",
        ]
    )
    paths.extend(
        [
            "/activities?limit=2.0&start_date=not-a-date",
            "/activities?start_date=bad&limit=no",
            "/activities/bad/workout-history?limit=100",
            "/activities?start_date=2026-03-01&end_date=2026-03-30&limit=2.0",
        ]
    )
    result = []
    for path in paths:
        r = client.get("/api/v1" + path)
        body = r.json()
        if "error" in body:
            body["error"].pop("request_id", None)
        result.append({"path": path, "status": r.status_code, "body": body})
        if path.endswith("&limit=2") and body["data"]["next_cursor"]:
            import urllib.parse

            paths.append(
                path
                + "&cursor="
                + urllib.parse.quote(body["data"]["next_cursor"], safe="")
            )
    return result


if __name__ == "__main__":
    if sys.argv[1:2] == ["reference"]:
        Path(sys.argv[2]).write_text(json.dumps(reference()))
    else:
        compare(__file__, seed, "./internal/activityhttp", "ACTIVITY_READ_CASES")
