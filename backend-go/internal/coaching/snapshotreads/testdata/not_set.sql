-- Synthetic setup captured for the saved contract response.
UPDATE app_state SET calendar_head_version=0 WHERE app_state.id = 1;

DELETE FROM session_completions WHERE session_completions.id = '00000000000000000000000000015fd9'::uuid;

DELETE FROM calendar_session_revisions WHERE calendar_session_revisions.id = '00000000000000000000000000015fd8'::uuid;

DELETE FROM calendar_versions WHERE calendar_versions.id = '00000000000000000000000000015fd7'::uuid;

UPDATE block_versions SET benchmark='null'::jsonb WHERE block_versions.id = '00000000000000000000000000015fa5'::uuid;
