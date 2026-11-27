"""Synthetic SQL fixtures for native training and activity checks."""

import os
import re
import subprocess
import tempfile
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url
from test_proposal_slice import MODULE, ROOT, migrated_schema


def test_url():
    raw = os.environ.get("TEST_DATABASE_URL")
    if (
        not raw
        or raw != os.environ.get("DATABASE_URL")
        or os.environ.get("APP_MODE") != "test"
    ):
        raise SystemExit("use scripts/test-db.py with the isolated test database")
    url = make_url(raw)
    if (
        url.database != "garmin_test"
        or url.host not in {"localhost", "127.0.0.1"}
        or str(url.port) != os.environ.get("TEST_DATABASE_PORT")
        or url.query
    ):
        raise SystemExit("expected the dedicated local garmin_test database")
    return url


def check_cases(package, fixture, env_key, test, populate):
    url = test_url()
    dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with (
        psycopg.connect(dsn, autocommit=True) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as scratch,
    ):
        directory = Path(scratch)
        with migrated_schema(db, url, directory / "case", "5173") as env:
            populate(env)
            path = MODULE / package / "testdata" / fixture
            subprocess.run(
                [
                    "go",
                    "test",
                    "-race",
                    "-count=1",
                    "-run",
                    "^" + test + "$",
                    "./" + package,
                ],
                cwd=MODULE,
                env={**env, env_key: str(path)},
                check=True,
            )


def uid(n):
    return str(UUID(int=n))


def seed_self_reports(env):
    with psycopg.connect(
        env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]
    ) as db:
        name, schema = db.execute(
            "SELECT current_database(), current_schema()"
        ).fetchone()
        if name != "garmin_test" or not re.fullmatch(r"go_parity_[0-9a-f]{32}", schema):
            raise ValueError("expected the runner's migrated test schema")
        for version in (1, 2):
            db.execute(
                "INSERT INTO calendar_versions(id,number,kind,actor) VALUES(gen_random_uuid(),%s,'manual_edit','user')",
                (version,),
            )
        db.execute(
            "UPDATE app_state SET data_revision=10,calendar_head_version=1 WHERE id=1"
        )
        # Newer revisions above the head are invisible to completion.
        for n, version, day, kind, deleted in [
            (1, 1, 8, "run", False),
            (1, 2, 9, "rest", True),
            (2, 1, 8, "strength", False),
            (3, 1, 8, "rest", False),
            (4, 1, 9, "run", False),
            (5, 1, 8, "run", True),
            (6, 1, 8, "run", False),
            (7, 1, 8, "run", False),
        ]:
            db.execute(
                """INSERT INTO calendar_session_revisions
                (id, session_uid, revision, calendar_version_number, deleted, local_date, kind, intent, certainty)
                VALUES(gen_random_uuid(),%s,%s,%s,%s,make_date(2026,3,%s),%s,'fixture','committed')""",
                (uid(n), version, version, deleted, day, kind),
            )
        db.execute(
            """INSERT INTO activities (id,start_at,original_start,local_date,sport,canonical_revision,resolution_state,field_provenance)
            VALUES (%s,'2026-03-08 03:30Z','2026-03-08T03:30Z','2026-03-08','running',1,'resolved','{}')""",
            (uid(80),),
        )
        db.execute(
            """INSERT INTO session_completions(id,session_uid,activity_id,status,match_method,input_version,version,updated_at)
            VALUES(gen_random_uuid(),%s,%s,'moved','confirmed_move',3,5,now())""",
            (uid(6), uid(80)),
        )

        db.execute(
            "INSERT INTO manual_sessions(id,version,date,kind) VALUES (%s,1,'2026-03-08','strength')",
            (uid(81),),
        )
        db.execute(
            "INSERT INTO source_accounts(id,provider,account_scope) VALUES (%s,'strong','fixture')",
            (uid(82),),
        )
        db.execute(
            """INSERT INTO raw_objects(id,sha256,relative_path,byte_size,media_type)
                    VALUES (%s,'fixture','fixture',0,'text/plain')""",
            (uid(83),),
        )
        db.execute(
            """INSERT INTO source_records(id,source_account_id,raw_object_id,source_identity,payload_hash,
                  fetched_at,parser_version,source_kind,fields) VALUES (%s,%s,%s,'fixture','fixture',now(),'1','strong','{}')""",
            (uid(84), uid(82), uid(83)),
        )
        db.execute(
            """INSERT INTO strong_workouts(id,source_account_id,source_identity,source_record_id,raw_object_id,
                  payload_hash,local_date,local_start,workout_name,sets,row_count,resolution_state)
                  VALUES (%s,%s,'fixture',%s,%s,'fixture','2026-03-08','2026-03-08T10:00:00','Fixture','[]',0,'resolved')""",
            (uid(85), uid(82), uid(84), uid(83)),
        )
        for n, key, subject, status, method in [
            (8, "manual_session_id", 81, "partial", "auto_same_day"),
            (9, "strong_workout_id", 85, "extra", "none"),
        ]:
            db.execute(
                f"""INSERT INTO session_completions(id,session_uid,{key},status,match_method,version,input_version,updated_at)
                     VALUES(gen_random_uuid(),%s,%s,%s,%s,4,2,now())""",
                (uid(n), uid(subject), status, method),
            )


id = uid


def conn(env):
    return psycopg.connect(
        env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"], autocommit=True
    )


def seed_assessment(env):
    with conn(env) as db:

        def execute(sql, *args):
            db.execute(sql, args)

        execute(
            "INSERT INTO calendar_versions(id,number,kind,actor) VALUES(%s,1,'bootstrap','system')",
            id(60),
        )
        execute("UPDATE app_state SET calendar_head_version=1 WHERE id=1")
        steps = [
            {
                "type": "repeat",
                "count": 2,
                "steps": [
                    {
                        "type": "work",
                        "duration_type": "time",
                        "duration_value": 300,
                        "target": {"modality": "speed", "low": 2.5, "high": 4.0},
                    }
                ],
            }
        ]
        for n, day, kind, duration in [
            (1, 10, "run", 1800),
            (2, 11, "strength", 2700),
            (3, 12, "strength", 2400),
            (4, 13, "run", 1800),
            (5, 15, "run", 1800),
            (6, 22, "run", 600),
        ]:
            execute(
                """INSERT INTO calendar_session_revisions(id,session_uid,revision,calendar_version_number,local_date,kind,certainty,intent,planned_duration_s,structure)
                VALUES(%s,%s,1,1,%s,%s,'committed','fixture',%s,%s)""",
                id(100 + n),
                id(n),
                f"2026-11-{day}",
                kind,
                duration,
                Jsonb(steps) if n == 1 else None,
            )
        execute(
            "INSERT INTO source_accounts(id,provider,account_scope) VALUES(%s,'synthetic','synthetic')",
            id(80),
        )
        execute(
            "INSERT INTO raw_objects(id,sha256,relative_path,byte_size,media_type) VALUES(%s,%s,'raw/test',5,'application/json')",
            id(81),
            "a" * 64,
        )
        execute(
            """INSERT INTO source_records(id,source_account_id,raw_object_id,source_identity,payload_hash,fetched_at,source_modified_at,parser_version,source_kind,fields)
            VALUES(%s,%s,%s,'fixture',%s,'2026-11-10 10:00:00Z','2026-11-10 11:12:13.123400Z','v1','synthetic','{}')""",
            id(82),
            id(80),
            id(81),
            "b" * 64,
        )
        for n, stamp, timer in [
            (21, "2026-11-10 09:00:00.123400Z", 1800),
            (22, "2026-11-15 11:00:00Z", 1798),
            (23, "2026-11-15 09:00:00Z", 1801),
            (24, "2026-11-20 09:00:00Z", 2400),
        ]:
            execute(
                """INSERT INTO activities(id,start_at,original_start,local_date,sport,timer_s,elapsed_s,distance_m,canonical_revision,resolution_state,field_provenance)
                VALUES(%s,%s,%s,%s,'running',%s,1900,5000,1,'resolved','{"distance_m":{"accuracy":0.95,"rank":1}}')""",
                id(n),
                stamp,
                stamp,
                stamp[:10],
                timer,
            )
        execute(
            "INSERT INTO activity_sources(id,activity_id,source_record_id,selected_fields) VALUES(%s,%s,%s,%s)",
            id(83),
            id(21),
            id(82),
            Jsonb(["distance_m", "start_at"]),
        )
        execute(
            """INSERT INTO activity_annotations(id,activity_id,version,workout_label,excluded) VALUES(%s,%s,1,'easy',false)""",
            id(85),
            id(21),
        )
        execute(
            """INSERT INTO fit_files(id,activity_id,raw_object_id,zip_sha256,fit_sha256,sdk_version,profile_version,device,message_inventory) VALUES(%s,%s,%s,%s,%s,'fixture','1','{}','{}')""",
            id(86),
            id(21),
            id(81),
            "c" * 64,
            "d" * 64,
        )
        execute(
            """INSERT INTO activity_laps(id,activity_id,lap_index,start_at,end_at,timer_s,elapsed_s,distance_m,avg_speed_mps,intensity,wkt_step_index)
            VALUES(%s,%s,0,'2026-11-10 09:00:00.123400Z','2026-11-10 09:30:00.123400Z',1800,1900,5000,3.12,'active',0)""",
            id(87),
            id(21),
        )
        execute(
            """INSERT INTO activity_workout_steps(id,activity_id,message_index,intensity,duration_type,duration_value,target_low) VALUES(%s,%s,0,'active','time',300,2.5)""",
            id(88),
            id(21),
        )
        execute(
            """INSERT INTO activity_streams(activity_id,t_s,hr_bpm,speed_mps,distance_m,altitude_m,cadence,timer_on,sample_count,max_gap_s,quality_flags)
            VALUES(%s,'{0,1}','{123,NULL}','{2.1234567,NULL}','{0,2}','{NULL,1}','{80.5,81}','{{0,1}}',2,1,'{fixture}')""",
            id(21),
        )
        execute(
            """INSERT INTO strong_workouts(id,source_account_id,source_identity,source_record_id,raw_object_id,payload_hash,local_date,local_start,workout_name,duration_s,sets,row_count)
            VALUES(%s,%s,%s,%s,%s,%s,'2026-11-11','2026-11-11 11:00:00','Synthetic',2100,'[]',1)""",
            id(30),
            id(80),
            "e" * 64,
            id(82),
            id(81),
            "f" * 64,
        )
        execute(
            """INSERT INTO manual_sessions(id,version,date,time,kind,duration_s) VALUES(%s,2,'2026-11-12','10:15:00.125','strength',2400)""",
            id(31),
        )
        for n, column, key in [
            (1, "activity_id", 21),
            (2, "strong_workout_id", 30),
            (3, "manual_session_id", 31),
            (7, "activity_id", 24),
        ]:
            execute(
                f"""INSERT INTO session_completions(id,session_uid,{column},status,match_method,updated_at)
                VALUES(%s,%s,%s,%s,'explicit','2026-11-10 10:00:00Z')""",
                id(110 + n),
                id(n),
                id(key),
                "extra" if n == 7 else "unknown",
            )
        execute(
            """INSERT INTO session_completions(id,session_uid,status,match_method,updated_at)
            VALUES(%s,%s,'completed_as_planned','user_marked','2026-11-13 10:00:00Z')""",
            id(114),
            id(4),
        )
        execute(
            """INSERT INTO metric_results(id,metric_id,method_version,subject_type,subject_key,status,value,source_refs,config_hash,calculated_at,dependency_hash,timezone)
            VALUES(%s,'work_interval_execution','v2','activity',%s,'available',%s,'{}',%s,now(),%s,'America/New_York')""",
            id(84),
            id(21),
            Jsonb(
                {
                    "n_planned": 2,
                    "n_completed": 2,
                    "reps": [{"target_valid_s": 1000, "target_in_range_s": 749.6}],
                }
            ),
            "1" * 64,
            "2" * 64,
        )
        execute(
            """INSERT INTO coverage_intervals(id,dataset,start_date,end_date,status,fully_enumerated)
            VALUES(%s,'activities','2026-11-10','2026-11-20','complete',true)""",
            id(89),
        )


def seed_recovery(env):
    with psycopg.connect(
        env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]
    ) as db:
        db.execute(
            "INSERT INTO source_accounts(id,provider,account_scope) VALUES(%s,'garmin','fixture')",
            (uid(101),),
        )
        db.execute(
            "INSERT INTO raw_objects(id,sha256,relative_path,media_type,byte_size) VALUES(%s,'abc','fixture','application/json',5)",
            (uid(102),),
        )
        db.execute(
            """INSERT INTO source_records(id,source_account_id,raw_object_id,source_identity,payload_hash,fetched_at,parser_version,source_kind,fields)
          VALUES(%s,%s,%s,'fixture','abc',now(),'1','recovery','{}')""",
            (uid(103), uid(101), uid(102)),
        )
        for d in range(30):
            for i, (metric, stat, base) in enumerate(
                [
                    ("sleep", "main_sleep_duration", 22000),
                    ("hrv", "last_night_average", 48),
                    ("resting_hr", "daily_resting", 55),
                ]
            ):
                value = base + (d % 6 if i != 2 else 0)
                if d == 29 and i == 1:
                    value = 20
                if d == 17 and i == 0:
                    value = -1
                db.execute(
                    """INSERT INTO recovery_observations(id,source_account_id,source_record_id,metric,source_date,time_semantics,value,unit,statistic,source_revision)
                VALUES(%s,%s,%s,%s,date '2026-03-01'+%s,'source_night',%s,'test',%s,'r1')""",
                    (
                        uid(1000 + d * 3 + i),
                        uid(101),
                        uid(103) if d != 2 else None,
                        metric,
                        d,
                        value,
                        stat,
                    ),
                )
        db.execute(
            """INSERT INTO checkins_v2(id,idempotency_key,kind,observed_at,fatigue,illness)
           VALUES(%s,'night','exception','2026-03-31 01:15:10.120Z',8,'present')""",
            (uid(105),),
        )


def seed_runs(env):
    with psycopg.connect(
        env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"]
    ) as db:
        for n, d in enumerate([4, 5, 6, 18, 19, 20, 23, 25, 29]):
            db.execute(
                """INSERT INTO activities(id,sport,start_at,original_start,local_date,canonical_revision,resolution_state,field_provenance)
               VALUES(%s,'running',make_date(2026,3,%s)+time '12:00','fixture',make_date(2026,3,%s),1,'resolved','{}')""",
                (uid(2000 + n), d, d),
            )
            if n == 8:
                continue
            val = {
                "ef_m_per_beat": 1 + 0.1 * n,
                "mean_hr_bpm": 125.0,
                "mean_speed_mps": 3.2,
                "session_class": "easy",
                "decoupling": {"pct": None if n == 1 else n * 0.5},
            }
            db.execute(
                """INSERT INTO metric_results(id,metric_id,method_version,subject_type,subject_key,status,value,reason_codes,quality_flags,
                     source_refs,config_hash,dependency_hash,calculated_at,timezone)
                     VALUES(%s,'aerobic_efficiency','v1','activity',%s,%s,%s,%s,%s,'{}','fixture',%s,now(),'UTC')""",
                (
                    uid(5000 + n),
                    uid(2000 + n),
                    "not_assessable" if n == 7 else "available",
                    Jsonb(val) if n != 7 else None,
                    ["LOW_COVERAGE"] if n == 7 else [],
                    ["TREADMILL"] if n == 6 else [],
                    str(n),
                ),
            )

        for n in (0, 1, 2, 3, 4):
            db.execute(
                """INSERT INTO activity_streams(activity_id,t_s,hr_bpm,speed_mps,distance_m,altitude_m,cadence,timer_on,sample_count,max_gap_s,quality_flags)
                SELECT %s,array_agg(t ORDER BY t),array_agg((CASE WHEN t<1900 THEN 135 ELSE 146 END)::smallint ORDER BY t),
                  array_agg((CASE WHEN %s=2 AND (t/60)%%2=0 THEN 6.5 WHEN %s=3 AND t<1700 THEN 0 ELSE 3.2 END)::real ORDER BY t),
                  array_agg(t*3.2::real ORDER BY t),array_agg((t/75)::real ORDER BY t),array_agg(80::real ORDER BY t),
                  ARRAY[[0,1900],[1920,3600]],361,10,'{}' FROM generate_series(0,3600,10) t""",
                (uid(2000 + n), n, n),
            )
        db.execute(
            "UPDATE activities SET sport='treadmill_running' WHERE id=%s", (uid(2001),)
        )
        db.execute(
            """INSERT INTO activity_annotations(id,activity_id,version,excluded,workout_label)
                    VALUES(%s,%s,1,false,'quality')""",
            (uid(8200), uid(2004)),
        )

        for i, (kind, limit) in enumerate(
            [
                ("hr_aerobic_upper", 140),
                ("hr_threshold_lower", 160),
                ("speed_aerobic_upper", 3),
                ("speed_threshold_lower", 4),
            ]
        ):
            db.execute(
                """INSERT INTO intensity_anchors(id,anchor_key,kind,value_low,unit,protocol,confidence,status,calibrated_at,valid_from,review_after)
            VALUES(%s,%s,%s,%s,%s,'manual','low','active','2026-02-01T12:00Z','2026-02-01','2026-03-01')""",
                (
                    uid(9000 + i),
                    "anchor" + str(i),
                    kind,
                    limit,
                    "bpm" if i < 2 else "mps",
                ),
            )

        db.execute(
            "INSERT INTO calendar_versions(id,number,kind,actor) VALUES(%s,1,'manual_edit','user')",
            (uid(9500),),
        )
        db.execute("UPDATE app_state SET calendar_head_version=1")
        for n in (0, 1, 2):
            structure = [
                {
                    "type": "work",
                    "duration_type": "time",
                    "duration_value": 200,
                    "target": {"modality": "speed", "low": 3.0, "high": 3.5},
                },
                {"type": "recovery", "duration_type": "time", "duration_value": 60},
                {"type": "work", "duration_type": "time", "duration_value": 200},
            ]
            db.execute(
                """INSERT INTO calendar_session_revisions(id,session_uid,revision,calendar_version_number,local_date,kind,intent,certainty,structure)
                    VALUES(%s,%s,1,1,'2026-03-04','run','quality','committed',%s)""",
                (uid(9510 + n), uid(9520 + n), Jsonb(structure)),
            )
            db.execute(
                """INSERT INTO session_completions(id,session_uid,activity_id,status,match_method,version,input_version,updated_at)
                    VALUES(%s,%s,%s,'unknown','explicit',1,1,now())""",
                (uid(9530 + n), uid(9520 + n), uid(2000 + n)),
            )
            if n == 2:
                continue
            for j, (intensity, offset, duration) in enumerate(
                [("active", 0, 200), ("recovery", 200, 60), ("active", 260, 200)]
            ):
                db.execute(
                    """INSERT INTO activity_workout_steps(id,activity_id,message_index,intensity,duration_type,duration_value)
                    VALUES(%s,%s,%s,%s,'time',%s)""",
                    (uid(9540 + n * 10 + j), uid(2000 + n), j, intensity, duration),
                )
                db.execute(
                    """INSERT INTO activity_laps(id,activity_id,lap_index,start_at,end_at,timer_s,elapsed_s,distance_m,wkt_step_index,intensity)
                    SELECT %s,id,%s,start_at+%s*interval '1s',start_at+%s*interval '1s',%s,%s,%s,%s,%s FROM activities WHERE id=%s""",
                    (
                        uid(9570 + n * 10 + j),
                        j,
                        offset,
                        offset + duration,
                        duration,
                        duration,
                        duration * 3,
                        j,
                        intensity,
                        uid(2000 + n),
                    ),
                )
        db.execute(
            """UPDATE activities SET treadmill_interval_paces=jsonb_build_object('0',jsonb_build_object(
            'pace_s_per_mile',450.0,'lap_identity','2026-03-05T12:00:00+00:00|2026-03-05T12:03:20+00:00|200.0|200.0|0')) WHERE id=%s""",
            (uid(2001),),
        )
