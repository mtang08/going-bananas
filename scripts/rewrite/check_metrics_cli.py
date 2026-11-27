"""Compare operational metric commands with app.cli on two isolated migrated schemas."""

import contextlib
import io
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from check_assessment_db import conn, id, seed
from check_recovery import compare

STATE = """
SELECT jsonb_build_object(
 'revision',(SELECT data_revision FROM app_state WHERE id=1),
 'metrics',(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY metric_id,subject_key,is_current,status,value::text),'[]') FROM (
 SELECT metric_id,method_version,subject_key,is_current,status,quality_status,reason_codes,quality_flags,config_hash,value
 FROM metric_results)p),
 'completions',(SELECT jsonb_agg(jsonb_build_array(session_uid,status,version,input_version) ORDER BY session_uid) FROM session_completions),
 'configs',(SELECT jsonb_agg(config_hash ORDER BY metric_id,config_hash) FROM metric_configs),
 'prompts',(SELECT jsonb_agg(jsonb_build_array(kind,activity_id,session_uid,status,opens_at,closes_at) ORDER BY kind,activity_id,session_uid) FROM prompts))
"""


def reference():
    from app.cli import main
    from app.metrics import refresh

    args = []
    for key, apply in [(999, False), (1, False), (1, True), (1, True), (4, False)]:
        args.append(
            ["metrics-assess-session", "--session-uid", id(key)]
            + (["--apply"] if apply else [])
        )
    for name in [
        "invalid",
        "run_volume_frequency",
        "symptom_response_timeline",
        "long_run_exposure",
        "hard_session_spacing",
        "planned_actual_session",
        "session_rpe_load",
        "intensity_time_distribution",
        "aerobic_efficiency",
        "recovery_multisignal_summary",
        "work_interval_execution",
        "all",
    ]:
        args.append(
            [
                "metrics-recompute",
                "--metric",
                name,
                "--since",
                "2026-11-22",
                "--until",
                "2026-11-22",
            ]
        )
    args.extend(
        [
            ["metrics-recompute", "--since", "2026-11-27"],
            [
                "metrics-recompute",
                "--metric",
                "work_interval_execution",
                "--until",
                "2026-09-06",
            ],
            [
                "metrics-recompute",
                "--metric",
                "run_volume_frequency",
                "--since",
                "2026-11-25",
            ],
            ["metrics-refresh-today"],
            ["metrics-refresh-today"],
        ]
    )
    cases = []
    with (
        conn(os.environ) as db,
        patch.object(
            refresh, "clock", lambda _: datetime(2026, 11, 26, 12, tzinfo=UTC)
        ),
    ):
        for flags in args:
            out, err = io.StringIO(), io.StringIO()
            with (
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
                patch.object(sys, "argv", ["app.cli", *flags]),
            ):
                code = main()
            response = json.loads(
                (err if code else out).getvalue().strip().splitlines()[-1]
            )
            response.pop("ms", None)
            cases.append(
                {
                    "args": flags,
                    "response": response,
                    "state": db.execute(STATE).fetchone()[0],
                }
            )
    return {"query": STATE, "cases": cases}


if __name__ == "__main__":
    if sys.argv[1:2] == ["reference"]:
        Path(sys.argv[2]).write_text(json.dumps(reference()))
    else:
        compare(__file__, seed, "./cmd/metrics", "METRICS_CLI_CASES")
