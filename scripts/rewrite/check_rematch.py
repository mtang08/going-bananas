"""Compare rematch, prompt transitions and the completion refresh transaction in two test schemas."""

import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import psycopg
from check_self_reports import NOW, seed, uid
from sqlalchemy.engine import make_url
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema


def fixtures(env):
    seed(env)
    with psycopg.connect(
        env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]
    ) as db:
        db.execute("DELETE FROM session_completions")
        for n, day in [(1, 6), (2, 5), (3, 4), (4, 3), (5, 2), (6, 1), (7, 9)]:
            db.execute(
                """UPDATE calendar_session_revisions SET local_date=make_date(2026,3,%s),kind='run',
                       deleted=false,planned_distance_m=5000,planned_duration_s=1800 WHERE session_uid=%s AND calendar_version_number=1""",
                (day, uid(n)),
            )
        db.execute(
            """UPDATE activities SET start_at='2026-03-06T20:00Z', end_at='2026-03-06T20:30Z',
                   timer_s=1800,distance_m=5000 WHERE id=%s""",
            (uid(80),),
        )
        db.execute(
            """INSERT INTO activities(id,start_at,end_at,original_start,local_date,sport,canonical_revision,resolution_state,field_provenance)
                   VALUES (%s,'2026-03-07 20:00Z','2026-03-07 20:40Z','fixture','2026-03-06','trail_running',1,'resolved','{}')""",
            (uid(88),),
        )
        db.execute(
            """INSERT INTO session_completions(id,session_uid,status,match_method,version,input_version,updated_at)
                   VALUES(gen_random_uuid(),%s,'completed_as_planned','user_marked',2,2,now())""",
            (uid(1),),
        )
        db.execute(
            """INSERT INTO checkins_v2(id,idempotency_key,kind,observed_at) VALUES(%s,'prior','exception','2026-02-21')""",
            (uid(92),),
        )
        db.execute(
            """INSERT INTO symptom_reports(id,checkin_id,site,side,severity,timing)
                    VALUES(gen_random_uuid(),%s,'knee','na',3,'unknown')""",
            (uid(92),),
        )
        for metric, version, kind, key, val, codes in [
            (
                "long_run_exposure",
                "v1",
                "activity",
                88,
                '{"classification":"long"}',
                [],
            ),
            ("planned_actual_session", "v2", "session", 2, "{}", ["NO_ACTIVITY_FOUND"]),
            ("planned_actual_session", "v2", "session", 3, "{}", ["MOVE_CANDIDATE"]),
        ]:
            db.execute(
                """INSERT INTO metric_results(id,metric_id,method_version,subject_type,subject_key,status,
                    reason_codes,value,source_refs,config_hash,dependency_hash,timezone,calculated_at)
                    VALUES(gen_random_uuid(),%s,%s,%s,%s,'available',%s,%s,'{}','fixture','fixture','UTC',now())""",
                (metric, version, kind, uid(key), codes, val),
            )


def cases():
    return [
        ("initial", ["2026-03-05", "2026-03-08"], "", NOW),
        ("unchanged", ["2026-03-05", "2026-03-08"], "", NOW),
        (
            "exclude linked run and answer old prompt",
            ["2026-03-06"],
            f"""
             INSERT INTO activity_annotations(id,activity_id,version,excluded) VALUES(gen_random_uuid(),'{uid(80)}',1,true);
             UPDATE activities SET workout_rpe=6 WHERE id='{uid(88)}';
             UPDATE prompts SET status='dismissed' WHERE kind='unmatched_session';
             INSERT INTO session_completions(id,session_uid,status,match_method,updated_at)
             VALUES(gen_random_uuid(),'{uid(2)}','skipped','user_marked',now())""",
            NOW,
        ),
        (
            "reselect run and expire delayed prompt",
            ["2026-03-06"],
            f"""
             INSERT INTO activity_annotations(id,activity_id,version,excluded) VALUES(gen_random_uuid(),'{uid(80)}',2,false);
             UPDATE metric_results SET is_current=false WHERE metric_id='planned_actual_session'""",
            datetime(2026, 3, 11, tzinfo=UTC),
        ),
        (
            "delete historical plan redistributes subject",
            ["2026-03-06"],
            f"""
             UPDATE calendar_session_revisions SET deleted=true WHERE session_uid='{uid(1)}' AND calendar_version_number=1""",
            NOW,
        ),
        (
            "delayed followup by prompt id answers expired prompt",
            [],
            f"""
             INSERT INTO checkins_v2(id,idempotency_key,kind,observed_at,prompt_id)
             SELECT gen_random_uuid(),'followup','delayed_followup','2026-03-10',id FROM prompts
             WHERE kind='delayed_symptom' AND activity_id='{uid(88)}'""",
            NOW,
        ),
        ("before original calendar", ["2024-01-01"], "", NOW),
        ("empty", [], "", NOW),
    ]


def reference():
    from datetime import date

    from app.db import SessionLocal
    from app.services.matching import rematch_dates
    from app.services.prompts import generate_prompts
    from sqlalchemy import text

    result = []
    for name, days, sql, clock in cases():
        with SessionLocal.begin() as session:
            session.info["metrics_now"] = clock
            for statement in sql.split(";"):
                if statement.strip():
                    session.execute(text(statement))
            matched = rematch_dates(session, {date.fromisoformat(d) for d in days})
            session.flush()
            counts = generate_prompts(session, clock)
            session.flush()
            state = session.execute(text(STATE)).scalar()
            result.append(
                {
                    "name": name,
                    "days": days,
                    "sql": sql,
                    "clock": clock.isoformat(),
                    "matched": sorted(map(str, matched)),
                    "counts": counts,
                    "state": state,
                }
            )
    from app.services import calendar, derived

    derived.install()
    for kind, target, body in [
        ("integrated self report", 3, {"status": "completed_as_planned"}),
        (
            "integrated recording link",
            3,
            {"expected_version": 1, "manual_session_id": uid(81)},
        ),
    ]:
        captured = {}

        def metrics(session, targets, matched, captured=captured, **kwargs):
            captured.update(
                manual=targets.manual_completion_only,
                days=sorted(d.isoformat() for d in targets.dates),
                matched=sorted(map(str, matched)),
            )
            return dict.fromkeys(
                ("dates", "activities", "plans", "windows", "nights"), 0
            )

        with (
            patch.object(derived.refresh, "refresh_targets", metrics),
            patch.object(calendar, "calendar_today", lambda s: NOW.date()),
            SessionLocal.begin() as session,
        ):
            session.info["metrics_now"] = NOW
            calendar.put_completion(
                session, UUID(int=target), body, assess=lambda s, uid: None
            )
        with SessionLocal() as session:
            state = session.execute(text(STATE)).scalar()
            assert captured
            result.append(
                dict(
                    name=kind,
                    command=kind,
                    uid=uid(target),
                    clock=NOW.isoformat(),
                    state=state,
                    **captured,
                )
            )
    for label, plan, since, dates in [
        ("plan scope", 1, "", []),
        ("anchor scope", None, "2026-03-06", []),
        ("mixed plan date anchor scopes", 4, "2026-03-07", ["2026-03-02"]),
        ("revision-only", None, "", []),
    ]:
        captured = {}
        scopes = {"revision", *(f"date:{d}" for d in dates)}
        if plan:
            scopes.add(f"plan:{uid(plan)}")
        if since:
            scopes.add(f"since:{since}")
        with (
            SessionLocal.begin() as session,
            patch.object(
                derived.refresh,
                "refresh_targets",
                lambda s, t, m, captured=captured, **kw: capture_scope(captured, t, m),
            ),
        ):
            session.info["metrics_now"] = NOW
            with derived.refresh.refreshing(session):
                if scopes != {"revision"}:
                    derived.refresh_scopes(session, scopes)
                state = session.execute(text(STATE)).scalar()
        result.append(
            {
                "name": label,
                "command": "plans",
                "clock": NOW.isoformat(),
                "scope": {
                    "PlanUIDs": [uid(plan)] if plan else [],
                    "Dates": dates,
                    "Since": since,
                },
                "state": state,
                **captured,
            }
        )
    return result


def capture_scope(captured, targets, matched):
    captured.update(
        days=sorted(d.isoformat() for d in targets.dates),
        matched=sorted(map(str, matched)),
    )
    return dict.fromkeys(("dates", "activities", "plans", "windows", "nights"), 0)


STATE = """SELECT jsonb_build_object('completions',coalesce((SELECT jsonb_agg(to_jsonb(c)-'id'-'updated_at' ORDER BY session_uid)
 FROM session_completions c),'[]'), 'prompts',coalesce((SELECT jsonb_agg(to_jsonb(p)-'id' ORDER BY kind,coalesce(activity_id,session_uid))
 FROM prompts p),'[]'))"""


def main():
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if not (
        os.getenv("APP_MODE") == "test"
        and url.database == "garmin_test"
        and url.host in {"localhost", "127.0.0.1"}
        and str(url.port) == os.getenv("TEST_DATABASE_PORT")
        and not url.query
        and os.getenv("DATABASE_URL") == os.environ["TEST_DATABASE_URL"]
    ):
        raise SystemExit("requires isolated garmin_test")
    with (
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
    ):
        d = Path(tmp)
        with (
            migrated_schema(db, url, d / "python", "5173") as py,
            migrated_schema(db, url, d / "go", "5173") as go,
        ):
            for env in (py, go):
                fixtures(env)
            data = d / "cases.json"
            subprocess.run(
                [sys.executable, __file__, "reference", str(data)],
                env={**py, "PYTHONPATH": str(BACKEND)},
                cwd=BACKEND,
                check=True,
            )
            subprocess.run(
                [
                    "go",
                    "test",
                    "-race",
                    "-v",
                    "-count=1",
                    "-run",
                    "TestDerivedPostgres",
                    "./internal/calendar",
                ],
                env={**go, "REMATCH_CASES": str(data)},
                cwd=MODULE,
                check=True,
            )


if __name__ == "__main__":
    if sys.argv[1:2] == ["reference"]:
        Path(sys.argv[2]).write_text(json.dumps(reference()))
    else:
        main()
