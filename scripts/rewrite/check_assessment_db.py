"""Compare assessment rows, identities and completion writes in separately migrated schemas."""
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url

from test_proposal_slice import BACKEND, ROOT, MODULE, migrated_schema

NOW = "2026-11-22T12:00:00Z"


def id(n):
    return str(UUID(int=n))


def conn(env):
    return psycopg.connect(env["PROPOSAL_TEST_DATABASE_URL"], options=env["PGOPTIONS"], autocommit=True)


def seed(env):
    with conn(env) as db:
        def execute(sql, *args):
            db.execute(sql, args)
        execute("INSERT INTO calendar_versions(id,number,kind,actor) VALUES(%s,1,'bootstrap','system')", id(60))
        execute("UPDATE app_state SET calendar_head_version=1 WHERE id=1")
        steps = [{"type":"repeat","count":2,"steps":[{"type":"work","duration_type":"time","duration_value":300,
            "target":{"modality":"speed","low":2.5,"high":4.0}}]}]
        for n, day, kind, duration in [(1,10,"run",1800),(2,11,"strength",2700),(3,12,"strength",2400),(4,13,"run",1800),(5,15,"run",1800),(6,22,"run",600)]:
            execute("""INSERT INTO calendar_session_revisions(id,session_uid,revision,calendar_version_number,local_date,kind,certainty,intent,planned_duration_s,structure)
                VALUES(%s,%s,1,1,%s,%s,'committed','fixture',%s,%s)""",id(100+n),id(n),f"2026-11-{day}",kind,duration,Jsonb(steps) if n==1 else None)
        execute("INSERT INTO source_accounts(id,provider,account_scope) VALUES(%s,'synthetic','synthetic')",id(80))
        execute("INSERT INTO raw_objects(id,sha256,relative_path,byte_size,media_type) VALUES(%s,%s,'raw/test',5,'application/json')",id(81),"a"*64)
        execute("""INSERT INTO source_records(id,source_account_id,raw_object_id,source_identity,payload_hash,fetched_at,source_modified_at,parser_version,source_kind,fields)
            VALUES(%s,%s,%s,'fixture',%s,'2026-11-10 10:00:00Z','2026-11-10 11:12:13.123400Z','v1','synthetic','{}')""",id(82),id(80),id(81),"b"*64)
        for n, stamp, timer in [(21,'2026-11-10 09:00:00.123400Z',1800),(22,'2026-11-15 11:00:00Z',1798),(23,'2026-11-15 09:00:00Z',1801),(24,'2026-11-20 09:00:00Z',2400)]:
            execute("""INSERT INTO activities(id,start_at,original_start,local_date,sport,timer_s,elapsed_s,distance_m,canonical_revision,resolution_state,field_provenance)
                VALUES(%s,%s,%s,%s,'running',%s,1900,5000,1,'resolved','{"distance_m":{"accuracy":0.95,"rank":1}}')""",id(n),stamp,stamp,stamp[:10],timer)
        execute("INSERT INTO activity_sources(id,activity_id,source_record_id,selected_fields) VALUES(%s,%s,%s,%s)",id(83),id(21),id(82),Jsonb(["distance_m","start_at"]))
        execute("""INSERT INTO activity_annotations(id,activity_id,version,workout_label,excluded) VALUES(%s,%s,1,'easy',false)""", id(85), id(21))
        execute("""INSERT INTO fit_files(id,activity_id,raw_object_id,zip_sha256,fit_sha256,sdk_version,profile_version,device,message_inventory) VALUES(%s,%s,%s,%s,%s,'fixture','1','{}','{}')""", id(86),id(21),id(81),"c"*64,"d"*64)
        execute("""INSERT INTO activity_laps(id,activity_id,lap_index,start_at,end_at,timer_s,elapsed_s,distance_m,avg_speed_mps,intensity,wkt_step_index)
            VALUES(%s,%s,0,'2026-11-10 09:00:00.123400Z','2026-11-10 09:30:00.123400Z',1800,1900,5000,3.12,'active',0)""",id(87),id(21))
        execute("""INSERT INTO activity_workout_steps(id,activity_id,message_index,intensity,duration_type,duration_value,target_low) VALUES(%s,%s,0,'active','time',300,2.5)""",id(88),id(21))
        execute("""INSERT INTO activity_streams(activity_id,t_s,hr_bpm,speed_mps,distance_m,altitude_m,cadence,timer_on,sample_count,max_gap_s,quality_flags)
            VALUES(%s,'{0,1}','{123,NULL}','{2.1234567,NULL}','{0,2}','{NULL,1}','{80.5,81}','{{0,1}}',2,1,'{fixture}')""",id(21))
        execute("""INSERT INTO strong_workouts(id,source_account_id,source_identity,source_record_id,raw_object_id,payload_hash,local_date,local_start,workout_name,duration_s,sets,row_count)
            VALUES(%s,%s,%s,%s,%s,%s,'2026-11-11','2026-11-11 11:00:00','Synthetic',2100,'[]',1)""",id(30),id(80),"e"*64,id(82),id(81),"f"*64)
        execute("""INSERT INTO manual_sessions(id,version,date,time,kind,duration_s) VALUES(%s,2,'2026-11-12','10:15:00.125','strength',2400)""",id(31))
        for n,column,key in [(1,"activity_id",21),(2,"strong_workout_id",30),(3,"manual_session_id",31),(7,"activity_id",24)]:
            execute(f"""INSERT INTO session_completions(id,session_uid,{column},status,match_method,updated_at)
                VALUES(%s,%s,%s,%s,'explicit','2026-11-10 10:00:00Z')""", id(110+n),id(n),id(key),"extra" if n==7 else "unknown")
        execute("""INSERT INTO session_completions(id,session_uid,status,match_method,updated_at)
            VALUES(%s,%s,'completed_as_planned','user_marked','2026-11-13 10:00:00Z')""",id(114),id(4))
        execute("""INSERT INTO metric_results(id,metric_id,method_version,subject_type,subject_key,status,value,source_refs,config_hash,calculated_at,dependency_hash,timezone)
            VALUES(%s,'work_interval_execution','v2','activity',%s,'available',%s,'{}',%s,now(),%s,'America/New_York')""",
            id(84),id(21),Jsonb(dict(n_planned=2,n_completed=2,reps=[dict(target_valid_s=1000,target_in_range_s=749.6)])),"1"*64,"2"*64)
        execute("""INSERT INTO coverage_intervals(id,dataset,start_date,end_date,status,fully_enumerated)
            VALUES(%s,'activities','2026-11-10','2026-11-20','complete',true)""",id(89))


def python_assess(keys, now):
    from app.db import SessionLocal, bump_data_revision, global_write_lock
    from app.metrics.engine import ensure_metric_config, upsert_results
    from app.metrics.planned_actual import CONFIG, METRIC_ID, METHOD_VERSION, compute, write_completion_status
    from app.metric_models import MetricResult as MetricResultRow
    for key in keys:
        with SessionLocal.begin() as session:
            session.info["metrics_now"] = now
            global_write_lock(session)
            rows = compute(session, key)
            if not rows:
                session.query(MetricResultRow).filter_by(metric_id="planned_actual_session",method_version="v2",subject_key=key,is_current=True).update({"is_current":False})
            if rows:
                ensure_metric_config(session,METRIC_ID,METHOD_VERSION,CONFIG)
            upsert_results(session, rows)
            if any(write_completion_status(session,row,now) for row in rows):
                bump_data_revision(session)


def snapshot(env):
    with conn(env) as db:
        return {
            "results": db.execute("""SELECT to_jsonb(m)-'id' FROM metric_results m WHERE metric_id='planned_actual_session' ORDER BY subject_key,dependency_hash""").fetchall(),
            "completions": db.execute("SELECT session_uid,status,version,input_version,reason_note,updated_at FROM session_completions ORDER BY session_uid").fetchall(),
            "config": db.execute("SELECT config,config_hash FROM metric_configs WHERE metric_id='planned_actual_session' ORDER BY config_hash").fetchall(),
            "revision": db.execute("SELECT data_revision FROM app_state WHERE id=1").fetchone(),
        }


def compare(py, go):
    left,right=snapshot(py),snapshot(go)
    for key in left:
        if left[key]!=right[key]:
            if key=="results":
                for (a,), (b,) in zip(left[key],right[key]):
                    if a!=b:
                        diff={k:(a[k],b[k]) for k in a if a[k]!=b[k]}
                        raise AssertionError(f"{a['subject_key']} differing metric columns {diff}")
            raise AssertionError(f"{key} differs: {left[key]} vs {right[key]}")


WINDOW_METRICS={"volume":"run_volume_frequency","symptoms":"symptom_response_timeline","long":"long_run_exposure","intensity":"intensity_time_distribution"}

def python_spacing(mode, uid):
    from datetime import date
    from app.db import SessionLocal
    from app.metrics.refresh import _manual_completion_spacing, compute_subjects
    with SessionLocal.begin() as session:
        now = datetime.fromisoformat(NOW)
        session.info["metrics_now"] = now
        if mode in WINDOW_METRICS:
            compute_subjects(session,WINDOW_METRICS[mode],[f"w{width}:2026-11-22" for width in ((28,) if mode=="symptoms" else (7,14,28,56,84))])
        elif mode == "date":
            compute_subjects(session, "hard_session_spacing", ["w14:2026-11-11"])
        else:
            _manual_completion_spacing(session, {UUID(uid)}, now.date(), associations_changed=mode=="association")


def spacing_check(binary, py, go):
    for env in [py, go]:
        with conn(env) as db:
            for n,stamp,gait in [(192,"2026-11-15 03:20:00.000400Z","yes"),(193,"2026-11-15 12:00Z","no")]:
                db.execute("INSERT INTO checkins_v2(id,idempotency_key,kind,observed_at,gait_change) VALUES(%s,%s,'exception',%s,%s)",(id(n),str(n),stamp,gait))
                db.execute("INSERT INTO symptom_reports(id,checkin_id,site,side,severity,timing) VALUES(%s,%s,%s,'left',%s,'later')",(id(n+10),id(n)," Knee " if n==192 else "knee",2.5 if n==192 else 1.0))
            result={"status":"partial","easy_s":80.0,"moderate_s":10.0,"high_s":0.0,"valid_s":90.0,"unknown_s":10.0,"eligible_timer_s":100.0,"unclassified_s":0.0}
            db.execute("""INSERT INTO metric_results(id,metric_id,method_version,subject_type,subject_key,status,value,source_refs,config_hash,calculated_at,dependency_hash,timezone,anchor_set_hash,anchor_keys)
                VALUES(%s,'intensity_time_distribution','v1','activity',%s,'partial',%s,'{}',%s,now(),%s,'America/New_York',%s,'{hr_threshold_lower}')""",
                (id(194),id(21),Jsonb({"hr":result,"speed":{"status":"not_assessable","reason_codes":["ANCHOR_MISSING"]}}),"5"*64,"6"*64,"7"*64))
            db.execute("INSERT INTO strength_routine_slots(id,label,default_weekday,lower_body_cost) VALUES(%s,'Fixture',1,'high')", (id(190),))
            db.execute("UPDATE calendar_session_revisions SET strength_slot_id=%s WHERE kind='strength'", (id(190),))
            db.execute("UPDATE calendar_session_revisions SET recipe_id='REC003' WHERE session_uid IN (%s,%s)",(id(1),id(4)))
            db.execute("UPDATE activities SET source_workout_label='long' WHERE id=%s",(id(22),))
            db.execute("""INSERT INTO metric_results(id,metric_id,method_version,subject_type,subject_key,status,value,source_refs,config_hash,calculated_at,dependency_hash,timezone)
                VALUES(%s,'long_run_exposure','v1','activity',%s,'available',%s,'{}',%s,now(),%s,'America/New_York')""",
                (id(191), id(21), Jsonb({"classification":"long"}), "3"*64,"4"*64))
    def snapshots(metric):
        values = []
        for env in [py,go]:
            with conn(env) as db:
                values.append(db.execute("SELECT to_jsonb(m)-'id' FROM metric_results m WHERE metric_id=%s AND subject_type='window' ORDER BY subject_key,dependency_hash",(metric,)).fetchall())
        return values
    for mode, n in [("volume",1),("long",1),("intensity",1),("symptoms",1),("date",1),("manual",5),("manual",1),("association",5)]:
        if mode=="association":
            for env in [py,go]:
                with conn(env) as db:
                    db.execute("UPDATE strength_routine_slots SET lower_body_cost='low',version=2 WHERE id=%s",(id(190),))
        subprocess.run([sys.executable,__file__,"spacing",mode,id(n)],env=dict(py,PYTHONPATH=str(BACKEND)),check=True)
        env=dict(go,ASSESSMENT_TEST_DATABASE_URL=go["PROPOSAL_TEST_DATABASE_URL"],ASSESSMENT_NOW=NOW,
                 ASSESSMENT_SUBJECTS=id(n),ASSESSMENT_SPACING=mode,GORACE="atexit_sleep_ms=0")
        subprocess.run([binary,"-test.run","^TestPythonDatabase$"],env=env,check=True)
        left,right=snapshots(WINDOW_METRICS.get(mode,"hard_session_spacing"))
        if left!=right:
            for (a,), (b,) in zip(left,right):
                if a!=b:
                    raise AssertionError({k:(a[k],b[k]) for k in a if a[k]!=b[k]})
            raise AssertionError("spacing row count")
    assert len(left)==4
    print("PASS spacing windows, exposure and provenance payloads, manual selection and association refresh")


def exercise(binary,py,go):
    for env in [py,go]:seed(env)
    def golang(keys,inject=False,now=NOW):
        env=dict(go,ASSESSMENT_TEST_DATABASE_URL=go["PROPOSAL_TEST_DATABASE_URL"],ASSESSMENT_NOW=now,
                 ASSESSMENT_SUBJECTS=",".join(keys),ASSESSMENT_INJECT="1" if inject else "",GORACE="atexit_sleep_ms=0")
        subprocess.run([binary,"-test.run","^TestPythonDatabase$"],env=env,check=True)
    def both(keys,now=NOW):
        subprocess.run([sys.executable,__file__,"python",now,*keys],env=dict(py,PYTHONPATH=str(BACKEND)),check=True)
        golang(keys,now=now)
        compare(py,go)
    with conn(go) as db:
        db.execute("""CREATE FUNCTION fail_assess() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'synthetic assessment failure'; END $$;
            CREATE TRIGGER fail_assess BEFORE UPDATE OF status ON session_completions FOR EACH ROW EXECUTE FUNCTION fail_assess()""")
    golang([id(1)],inject=True)
    compare(py,go)
    with conn(go) as db:db.execute("DROP TRIGGER fail_assess ON session_completions")
    keys=[id(n) for n in range(1,9)]
    both(keys)
    with conn(go) as db:
        saved=db.execute("SELECT id FROM metric_results WHERE metric_id='planned_actual_session' AND subject_key=%s AND is_current",(id(1),)).fetchone()
    both(keys)
    with conn(go) as db:
        assert db.execute("SELECT count(*) FROM metric_results WHERE metric_id='planned_actual_session'").fetchone()==(7,)
    # An excluded recording changes status and identity. Reverting its annotation restores the original row ID.
    for env in [py,go]:
        with conn(env) as db:db.execute("UPDATE activity_annotations SET excluded=true WHERE id=%s",(id(85),))
    both([id(1)])
    for env in [py,go]:
        with conn(env) as db:db.execute("UPDATE activity_annotations SET excluded=false WHERE id=%s",(id(85),))
    both([id(1)])
    with conn(go) as db:
        assert db.execute("SELECT id FROM metric_results WHERE metric_id='planned_actual_session' AND subject_key=%s AND is_current",(id(1),)).fetchone()==saved
    for env in [py,go]:
        with conn(env) as db:db.execute("UPDATE calendar_session_revisions SET deleted=true WHERE session_uid=%s",(id(6),))
    both([id(6)])
    spacing_check(binary,py,go)
    print("PASS assessment results, source/dependency hashes, linked and self-reported statuses, invalidation, historical restoration, caller rollback")


def main():
    url=make_url(os.environ["TEST_DATABASE_URL"])
    if (os.environ.get("APP_MODE")!="test" or url.database!="garmin_test" or url.host not in {"localhost","127.0.0.1"}
            or str(url.port)!=os.environ.get("TEST_DATABASE_PORT") or os.environ["TEST_DATABASE_URL"]!=os.environ["DATABASE_URL"] or url.query):
        raise SystemExit("run with an isolated test DB")
    pgurl=url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(pgurl,autocommit=True) as db,tempfile.TemporaryDirectory(dir=ROOT/"private") as tmp:
        directory=Path(tmp);binary=directory/"assessment.test"
        subprocess.run(["go","test","-race","-c","-o",binary,"./internal/metrics/assessment"],cwd=MODULE,check=True)
        with migrated_schema(db,url,directory/"reference","5173") as py,migrated_schema(db,url,directory/"go","5173") as go:
            exercise(binary,py,go)


if __name__=="__main__":
    if sys.argv[1:2]==["python"]:python_assess(sys.argv[3:],datetime.fromisoformat(sys.argv[2]))
    elif sys.argv[1:2]==["spacing"]:python_spacing(*sys.argv[2:])
    else:main()
