-- Python's app.db.global_write_lock uses this transaction-scoped advisory lock.
-- name: LockGlobalWriter :exec
SELECT pg_advisory_xact_lock(71382413);

-- name: GoalVersion :one
SELECT version FROM goals WHERE id = $1 FOR UPDATE;

-- name: PatchGoal :one
UPDATE goals
SET text = coalesce(sqlc.narg(goal_text)::text, text),
    horizon = coalesce(sqlc.narg(horizon)::varchar, horizon),
    priority = coalesce(sqlc.narg(priority)::bigint, priority),
    status = coalesce(sqlc.narg(status)::varchar, status),
    version = version + 1
WHERE id = sqlc.arg(id)
RETURNING *;

-- name: BumpDataRevision :one
-- A transaction-local setting follows PostgreSQL savepoints and resets on commit
-- or rollback. Calendar writes and their derived assessments share one revision.
WITH bumped AS (
    UPDATE app_state SET data_revision = data_revision + 1
    WHERE id = 1 AND current_setting('going_bananas.revision_bumped', true) IS DISTINCT FROM '1'
    RETURNING data_revision
)
SELECT data_revision FROM bumped WHERE set_config('going_bananas.revision_bumped', '1', true) = '1'
UNION ALL
SELECT data_revision FROM app_state WHERE id = 1 AND NOT EXISTS (SELECT 1 FROM bumped);

-- name: ListGoals :many
SELECT * FROM goals ORDER BY priority, id;
