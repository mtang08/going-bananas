-- name: ListProposals :many
SELECT id, revision, operation, status, submitted_at, decided_at, discarded_at,
       extract(timezone FROM submitted_at)::integer AS submitted_offset,
       coalesce(extract(timezone FROM decided_at), 0)::integer AS decided_offset,
       coalesce(extract(timezone FROM discarded_at), 0)::integer AS discarded_offset,
       headline, base_calendar_version, coalesce(jsonb_array_length(payload->'changes'), 0)::int AS change_count
FROM coach_proposals
WHERE CASE sqlc.arg(status_filter)::text
  WHEN '' THEN status <> 'discarded'
  WHEN 'open' THEN status IN ('pending','stale','invalid')
  ELSE status = sqlc.arg(status_filter)::text
END
ORDER BY submitted_at DESC, id DESC
LIMIT 50;

-- name: DataRevision :one
SELECT coalesce((SELECT data_revision FROM app_state WHERE id = 1), 0)::integer AS data_revision;
