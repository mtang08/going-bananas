"""Compare annotation PATCH responses and refreshed source, calendar, metric and prompt state."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

from check_assessment_db import conn, id, seed
from check_recovery import compare


def reference():
    from datetime import UTC, datetime

    from app.main import app
    from app.metrics import refresh
    from fastapi.testclient import TestClient

    results = []
    with (
        patch.object(
            refresh, "clock", lambda _: datetime(2026, 11, 26, 12, tzinfo=UTC)
        ),
        TestClient(app) as client,
    ):
        for activity, raw in [
            ("bad", "{"),
            ("bad", '{"notes":12,"excluded":4}'),
            (id(21), "null"),
            (id(21), "{}"),
            (
                id(21),
                '{"expected_version":-1,"workout_label":"bad","notes":5,"excluded":"bad"}',
            ),
            (id(21), json.dumps({"expected_version": 0, "notes": "a" * 4001})),
            (id(2022), '{"expected_version":0}'),
            (
                id(21),
                '{"expected_version":"1","workout_label":"long","notes":"test trail","excluded":"on","unknown":3}',
            ),
            (id(21), '{"expected_version":0}'),
            (id(21), '{"expected_version":2,"notes":null,"workout_label":null}'),
        ]:
            path = f"/activities/{activity}/annotations"
            r = client.patch(
                "/api/v1" + path,
                content=raw,
                headers={"content-type": "application/json", "X-Local-Request": "1"},
            )
            value = r.json()
            if "error" in value:
                value["error"].pop("request_id", None)
            results.append(
                {"path": path, "payload": raw, "status": r.status_code, "body": value}
            )
    return results


def state(env):
    queries = {
        "annotations": "SELECT activity_id,version,workout_label,notes,excluded FROM activity_annotations ORDER BY activity_id,version",
        "revision": "SELECT data_revision FROM app_state WHERE id=1",
        "completions": "SELECT session_uid,activity_id,match_method,status,version,input_version FROM session_completions ORDER BY session_uid",
        "metrics": "SELECT metric_id,subject_key,status,quality_status,reason_codes,quality_flags,value FROM metric_results WHERE is_current ORDER BY metric_id,subject_key",
        "prompts": "SELECT kind,activity_id,session_uid,status,opens_at,closes_at FROM prompts ORDER BY kind,activity_id,session_uid",
    }
    with conn(env) as db:
        return {k: db.execute(q).fetchall() for k, q in queries.items()}


if __name__ == "__main__":
    if sys.argv[1:2] == ["reference"]:
        Path(sys.argv[2]).write_text(json.dumps(reference()))
    else:
        compare(__file__, seed, "./internal/activityhttp", "ANNOTATION_CASES", state)
