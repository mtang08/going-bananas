"""Compare both aerobic trend widths using independently seeded immutable activity metric IDs."""

import json
import sys
from pathlib import Path

import psycopg
from check_recovery import compare
from check_self_reports import uid
from psycopg.types.json import Jsonb

STATE = """SELECT jsonb_agg(to_jsonb(m)-'id'-'calculated_at' ORDER BY subject_key,dependency_hash) FROM metric_results m WHERE metric_id='aerobic_efficiency' AND subject_type='window'"""
START = "2026-03-30"
CHANGE = f"UPDATE metric_results SET is_current=false WHERE id='{uid(5001)}'"


def seed(env):
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


def reference():
    from app.db import SessionLocal
    from app.metrics import aerobic, engine
    from sqlalchemy import text

    result = []
    for change in ["", "", CHANGE]:
        with SessionLocal.begin() as s:
            if change:
                s.execute(text(change))
            for d in [28, 84]:
                engine.upsert_results(s, aerobic.compute(s, f"w{d}:{START}"))
            s.flush()
            result.append({"sql": change, "state": s.execute(text(STATE)).scalar_one()})
    return {"cases": result, "query": STATE}


if __name__ == "__main__":
    if sys.argv[1:2] == ["reference"]:
        Path(sys.argv[2]).write_text(json.dumps(reference()))
    else:
        compare(__file__, seed, "./internal/metrics/trainingwindows", "AEROBIC_CASES")
