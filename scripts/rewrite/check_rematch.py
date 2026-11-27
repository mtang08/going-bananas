"""Run the native rematch PostgreSQL cases."""

import psycopg
from training_fixture import check_cases, seed_self_reports, uid


def seed_rematch(env):
    seed_self_reports(env)
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


if __name__ == "__main__":
    check_cases(
        "internal/calendar",
        "rematch.json",
        "REMATCH_CASES",
        "TestDerivedPostgres",
        seed_rematch,
    )
