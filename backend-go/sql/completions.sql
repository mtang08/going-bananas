-- name: LockCalendarHead :one
SELECT calendar_head_version FROM app_state WHERE id = 1 FOR UPDATE;

-- name: CompletionPlanAtHead :one
SELECT local_date, kind, deleted FROM calendar_session_revisions
WHERE session_uid = $1 AND calendar_version_number <= $2
ORDER BY calendar_version_number DESC, revision DESC LIMIT 1;

-- name: CompletionForSession :one
SELECT * FROM session_completions WHERE session_uid = $1 FOR UPDATE;

-- name: CalendarTimezone :one
SELECT COALESCE((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1), 'America/New_York')::text AS timezone;

-- name: CompletionSubjectDate :one
SELECT (a.start_at AT TIME ZONE sqlc.arg(athlete_zone)::text)::date AS local_date
FROM activities a WHERE a.id = sqlc.narg(activity_id)::uuid
UNION ALL SELECT s.local_date FROM strong_workouts s WHERE s.id = sqlc.narg(strong_workout_id)::uuid
UNION ALL SELECT m.date FROM manual_sessions m WHERE m.id = sqlc.narg(manual_session_id)::uuid;

-- name: SaveCompletion :one
INSERT INTO session_completions (id,session_uid,activity_id,strong_workout_id,manual_session_id,status,match_method,modification_reason,reason_note,
    version,input_version,updated_at)
VALUES (gen_random_uuid(),sqlc.arg(session_uid),sqlc.narg(activity_id),sqlc.narg(strong_workout_id),
    sqlc.narg(manual_session_id),sqlc.arg(status),sqlc.arg(match_method),sqlc.narg(modification_reason),
    sqlc.narg(reason_note),sqlc.arg(version),sqlc.arg(input_version),sqlc.arg(updated_at))
ON CONFLICT (session_uid) DO UPDATE SET
    status=excluded.status, match_method=excluded.match_method, activity_id=excluded.activity_id, strong_workout_id=excluded.strong_workout_id,
    manual_session_id=excluded.manual_session_id, modification_reason=excluded.modification_reason, reason_note=excluded.reason_note,
    version=excluded.version, input_version=excluded.input_version, updated_at=excluded.updated_at
RETURNING *;

-- name: DeleteCompletion :exec
DELETE FROM session_completions WHERE session_uid = $1;

-- name: RecordingHolder :one
SELECT * FROM session_completions
WHERE session_uid <> sqlc.arg(session_uid) AND
    (activity_id = sqlc.narg(activity_id) OR strong_workout_id = sqlc.narg(strong_workout_id)
     OR manual_session_id = sqlc.narg(manual_session_id))
FOR UPDATE;

-- name: RestoreMovedStatus :exec
UPDATE session_completions SET status = 'moved' WHERE session_uid = $1 AND status <> 'moved';
