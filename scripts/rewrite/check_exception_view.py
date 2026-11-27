"""Compare dashboard exception projections against Python in a migrated disposable schema."""

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import psycopg
from check_assessment_db import conn, id, seed
from check_gcal_replay import test_url
from fastapi.encoders import jsonable_encoder
from test_proposal_slice import BACKEND, MODULE, ROOT, migrated_schema

NOW = datetime.fromisoformat("2026-11-02T04:59:59.123400+00:00")
TICK = timedelta(microseconds=1)


def populate(env):
    seed(env)
    with conn(env) as db:
        db.execute(
            """INSERT INTO coach_snapshots(id,operation,as_of,generated_at,calendar_version_number,
            data_revision,payload,source_fingerprint,source_versions,kb_digest,payload_sha256,kb_package_version,
            kb_routes,approx_tokens) VALUES (%s,'review_rolling_plan',current_date,now(),1,1,'{}','x','{}','x','x','v1','{}',1)""",
            (id(300),),
        )
        for n, status in enumerate(
            ("open", "open", "resolved", "resolved", "escalated", "superseded")
        ):
            db.execute(
                """INSERT INTO coach_proposals(id,operation,snapshot_id,base_calendar_version,status,
                submitted_at,headline,confidence,payload,skill_version,input_hash)
                VALUES (%s,'review_rolling_plan',%s,1,'rejected',now(),'fixture','{}','{}','v1',%s)""",
                (id(310 + n), id(300), str(n)),
            )
            resolved = (
                NOW - timedelta(days=14) - (TICK if n == 3 else timedelta())
                if status == "resolved"
                else None
            )
            db.execute(
                """INSERT INTO exception_patches(id,proposal_id,calendar_version_number,category,severity,
                ladder_level,window_start,window_end,reassess_on,status,resolved_at,resolved_by,resolution_note,
                monitor,return_criteria,escalate_criteria,unchanged,created_at,version)
                VALUES (%s,%s,%s,'post_event','hold','next_days','2026-10-01','2026-11-04',%s,%s,%s,%s,%s,
                '["monitor"]','["return"]','["escalate"]','["unchanged"]',%s,2)""",
                (
                    id(320 + n),
                    id(310 + n),
                    1 if n % 2 == 0 else 99,
                    "2026-11-02" if n == 1 else "2026-11-01",
                    status,
                    resolved,
                    "athlete" if resolved else None,
                    "synthetic close note" if resolved else None,
                    NOW - timedelta(days=n // 2),
                ),
            )
        race = "abcd1234-1234-5678-9012-123456789abc"
        db.execute(
            "INSERT INTO events(id,name,event_date,purpose,status) VALUES (%s,'Fixture race','2026-10-20','training','completed')",
            (race,),
        )
        for n, (code, key, status, sev) in enumerate(
            [
                ("POST_EVENT_REVIEW_DUE", "event:" + race, "open", "observe"),
                ("POST_EVENT_REVIEW_DUE", race.upper(), "open", "observe"),
                ("POST_EVENT_REVIEW_DUE", "invalid", "open", "observe"),
                ("BLOCK_BENCHMARK_COMPLETED", "completed", "open", "caution"),
                ("BLOCK_BENCHMARK_MISSED", "missed", "open", "hold"),
                ("ESCALATION", "symptoms", "addressed", "escalate"),
                ("CLOSED", "included", "dismissed", "caution"),
                ("CLOSED", "excluded", "resolved", "hold"),
            ]
        ):
            closed = (
                NOW - timedelta(days=28) - (TICK if n == 7 else timedelta())
                if n >= 6
                else None
            )
            db.execute(
                """INSERT INTO exception_findings(id,rule_code,rule_version,entity_key,status,severity,
            category,summary,evidence,evidence_at,first_seen_at,last_seen_at,patch_id,closed_at,close_note,version)
            VALUES (%s,%s,'v1',%s,%s,%s,'symptoms_illness','fixture','[{"value":2}]',%s,%s,%s,%s,%s,%s,3)""",
                (
                    id(340 + n),
                    code,
                    key,
                    status,
                    sev,
                    NOW - timedelta(days=n // 2),
                    NOW + TICK * (n - 3),
                    NOW,
                    id(320) if n in (3, 5) else None,
                    closed,
                    "internal note" if closed else None,
                ),
            )


def reference(path):
    from app.db import SessionLocal
    from app.services.exceptions.detector import exceptions_view

    with SessionLocal() as session:
        cases = [
            {
                "now": at,
                "include": include,
                "expected": exceptions_view(session, at, include),
            }
            for at in (NOW, NOW + TICK, NOW + timedelta(seconds=1))
            for include in ("active", "recent")
        ]
    path.write_text(json.dumps(jsonable_encoder(cases)))


def exercise(env, scratch):
    target = scratch / "view.json"
    for phase in ("empty", "populated", "reviewed"):
        if phase == "populated":
            populate(env)
        elif phase == "reviewed":
            with conn(env) as db:
                for n, operation, status, delta in [
                    (0, "review_rolling_plan", "accepted", -1),
                    (1, "review_training_block", "partially_accepted", 0),
                    (2, "exception_review", "accepted", 10),
                    (3, "review_training_block", "rejected", 12),
                ]:
                    db.execute(
                        "UPDATE coach_proposals SET operation=%s,status=%s,decided_at=%s WHERE id=%s",
                        (operation, status, NOW + TICK * delta, id(310 + n)),
                    )
        subprocess.run(
            [sys.executable, __file__, "reference", target],
            env={**env, "PYTHONPATH": str(BACKEND)},
            check=True,
        )
        subprocess.run(
            [
                "go",
                "test",
                "-count=1",
                "-run",
                "^TestPythonView$",
                "./internal/exceptions",
            ],
            cwd=MODULE,
            env={**env, "EXCEPTION_VIEW_REFERENCE": str(target)},
            check=True,
        )


def main():
    url = test_url()
    with (
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as scratch,
        migrated_schema(db, url, Path(scratch) / "view", "0") as env,
    ):
        exercise(env, Path(scratch))


if __name__ == "__main__":
    if sys.argv[1:2] == ["reference"]:
        reference(Path(sys.argv[2]))
    else:
        main()
