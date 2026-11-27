"""Verify native assessment refresh, rollback and metric scope on isolated PostgreSQL."""

import subprocess
import tempfile
from pathlib import Path

import psycopg
from test_proposal_slice import MODULE, ROOT, migrated_schema
from training_fixture import conn, id, seed_assessment, test_url

NOW = "2026-11-22T12:00:00Z"


def run_fixture(binary, env, test, **options):
    subprocess.run(
        [binary, "-test.run", "^" + test + "$"],
        env=dict(
            env,
            ASSESSMENT_TEST_DATABASE_URL=env["PROPOSAL_TEST_DATABASE_URL"],
            ASSESSMENT_NOW=NOW,
            GORACE="atexit_sleep_ms=0",
            **options,
        ),
        check=True,
    )


def snapshot(env):
    with conn(env) as db:
        return {
            "results": db.execute(
                """SELECT to_jsonb(m)-'id' FROM metric_results m WHERE metric_id='planned_actual_session' ORDER BY subject_key,dependency_hash"""
            ).fetchall(),
            "completions": db.execute(
                "SELECT session_uid,status,version,input_version,reason_note,updated_at FROM session_completions ORDER BY session_uid"
            ).fetchall(),
            "config": db.execute(
                "SELECT config,config_hash FROM metric_configs WHERE metric_id='planned_actual_session' ORDER BY config_hash"
            ).fetchall(),
            "revision": db.execute(
                "SELECT data_revision FROM app_state WHERE id=1"
            ).fetchone(),
        }


def exercise(binary, env):
    seed_assessment(env)

    def refresh(keys, **kwargs):
        run_fixture(
            binary,
            env,
            "TestAssessmentPostgres",
            ASSESSMENT_SUBJECTS=",".join(keys),
            **kwargs,
        )

    before = snapshot(env)
    with conn(env) as db:
        db.execute("""CREATE FUNCTION fail_assess() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'synthetic assessment failure'; END $$;
            CREATE TRIGGER fail_assess BEFORE UPDATE OF status ON session_completions FOR EACH ROW EXECUTE FUNCTION fail_assess()""")
    refresh([id(1)], ASSESSMENT_INJECT="1")
    assert snapshot(env) == before
    with conn(env) as db:
        db.execute("DROP TRIGGER fail_assess ON session_completions")

    keys = [id(n) for n in range(1, 9)]
    refresh(keys)
    stable = snapshot(env)
    assert len(stable["results"]) == 7
    refresh(keys)
    assert snapshot(env) == stable

    def result_id(db):
        return db.execute(
            "SELECT id FROM metric_results WHERE metric_id='planned_actual_session' AND subject_key=%s AND is_current",
            (id(1),),
        ).fetchone()

    with conn(env) as db:
        original = result_id(db)
        assert original
        db.execute(
            "UPDATE activity_annotations SET excluded=true WHERE id=%s", (id(85),)
        )
    refresh([id(1)])
    with conn(env) as db:
        assert result_id(db) != original
        db.execute(
            "UPDATE activity_annotations SET excluded=false WHERE id=%s", (id(85),)
        )
    refresh([id(1)])
    with conn(env) as db:
        assert result_id(db) == original
        db.execute(
            "UPDATE calendar_session_revisions SET deleted=true WHERE session_uid=%s",
            (id(6),),
        )
    refresh([id(6)])
    with conn(env) as db:
        assert not db.execute(
            "SELECT EXISTS(SELECT 1 FROM metric_results WHERE metric_id='planned_actual_session' AND subject_key=%s AND is_current)",
            (id(6),),
        ).fetchone()[0]
    print(
        "PASS assessment replay, source revision restoration, invalidation and caller rollback"
    )


def scope_check(binary, env):
    with conn(env) as db:
        db.execute(
            "INSERT INTO checkins_v2(id,idempotency_key,kind,observed_at) VALUES(%s,'scope','exception','2026-11-20T23:30Z')",
            (id(250),),
        )
    for mode in [
        "plan",
        "manual",
        "recovery_dates:2026-11-20",
        "checkin:" + id(250),
        "since:2026-11-19;coverage_date:2026-11-20",
        "link",
    ]:
        if mode == "link":
            with conn(env) as db:
                db.execute(
                    "INSERT INTO calendar_versions(id,number,kind,actor) VALUES(%s,1,'bootstrap','system')",
                    (id(253),),
                )
                db.execute("UPDATE app_state SET calendar_head_version=1 WHERE id=1")
                db.execute(
                    """INSERT INTO calendar_session_revisions(id,session_uid,revision,calendar_version_number,local_date,kind,certainty,intent,planned_duration_s,recipe_id)
                    VALUES(%s,%s,1,1,'2026-11-22','run','committed','synthetic',1800,'REC002')""",
                    (id(254), id(251)),
                )
                db.execute(
                    """INSERT INTO activities(id,start_at,end_at,original_start,local_date,sport,timer_s,elapsed_s,distance_m,canonical_revision,resolution_state,field_provenance)
                    VALUES(%s,'2026-11-22 10:00Z','2026-11-22 10:30Z','2026-11-22T10:00Z','2026-11-22','running',1800,1800,4000,1,'resolved','{}')""",
                    (id(252),),
                )
            with conn(env) as db:
                before = db.execute(
                    "SELECT data_revision,(SELECT count(*) FROM metric_results) FROM app_state WHERE id=1"
                ).fetchone()
                db.execute("""CREATE FUNCTION fail_link() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic linked metric failure'; END $$;
                CREATE TRIGGER fail_link BEFORE INSERT ON metric_results FOR EACH ROW WHEN (NEW.metric_id='run_volume_frequency') EXECUTE FUNCTION fail_link()""")
            run_fixture(binary, env, "TestScopeDatabase", ASSESSMENT_SCOPE="link-fail")
            with conn(env) as db:
                assert (
                    db.execute(
                        "SELECT data_revision,(SELECT count(*) FROM metric_results) FROM app_state WHERE id=1"
                    ).fetchone()
                    == before
                )
                assert db.execute(
                    "SELECT count(*) FROM session_completions WHERE session_uid=%s",
                    (id(251),),
                ).fetchone() == (0,)
                db.execute("DROP TRIGGER fail_link ON metric_results")
        run_fixture(binary, env, "TestScopeDatabase", ASSESSMENT_SCOPE=mode)

    with conn(env) as db:
        assert db.execute(
            "SELECT activity_id::text FROM session_completions WHERE session_uid=%s",
            (id(251),),
        ).fetchone() == (id(252),)
    run_fixture(binary, env, "TestScopeDatabase", ASSESSMENT_SCOPE="read-stored")
    with conn(env) as db:
        db.execute(
            "UPDATE metric_results SET config_hash=%s WHERE is_current AND (subject_key=%s OR subject_key='night:2026-11-22')",
            ("0" * 64, id(252)),
        )
    run_fixture(binary, env, "TestScopeDatabase", ASSESSMENT_SCOPE="read-preview")
    run_fixture(binary, env, "TestScopeDatabase", ASSESSMENT_SCOPE="marker")
    print(
        "PASS linked completion rollback, scope refresh, preview identities and pooled revision savepoints"
    )


def main():
    url = test_url()
    dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with (
        psycopg.connect(dsn, autocommit=True) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
    ):
        directory = Path(tmp)
        binary = directory / "assessment.test"
        subprocess.run(
            [
                "go",
                "test",
                "-race",
                "-c",
                "-o",
                binary,
                "./internal/metrics/assessment",
            ],
            cwd=MODULE,
            check=True,
        )
        with migrated_schema(db, url, directory / "assessment", "5173") as env:
            exercise(binary, env)
        binary = directory / "refresh.test"
        subprocess.run(
            ["go", "test", "-race", "-c", "-o", binary, "./internal/metrics/refresh"],
            cwd=MODULE,
            check=True,
        )
        with migrated_schema(db, url, directory / "scope", "5173") as env:
            scope_check(binary, env)


if __name__ == "__main__":
    main()
