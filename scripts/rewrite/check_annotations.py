"""Compare annotation PATCH responses and refreshed source, calendar, metric and prompt state."""

from check_activity_reads import exercise
from check_assessment_db import conn, seed


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
    exercise(seed, "annotations", state)
