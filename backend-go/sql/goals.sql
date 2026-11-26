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
UPDATE app_state
SET data_revision = data_revision + 1
WHERE id = 1
RETURNING data_revision;

-- name: ListGoals :many
SELECT * FROM goals ORDER BY priority, id;

-- name: CreateGoal :one
INSERT INTO goals (id, text, horizon, priority, status, version)
VALUES (sqlc.arg(id), sqlc.arg(goal_text), sqlc.arg(horizon), sqlc.arg(priority)::bigint, 'active', 1)
RETURNING *;
