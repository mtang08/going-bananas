-- Synthetic setup captured for the saved contract response.
INSERT INTO calendar_versions (id, number, parent_number, kind, actor, reason, proposal_id, restored_from_number, block_version_id)
VALUES
    ('00000000000000000000000000015fd7'::uuid, 1, 0, 'manual_edit', 'user', NULL, NULL, NULL, NULL);

INSERT INTO calendar_session_revisions (id, session_uid, revision, calendar_version_number, deleted, local_date, slot, kind, recipe_id, custom, locked, legacy_unstructured, placeholder, intent, certainty, planned_duration_s, planned_distance_m, strength_slot_id, notes)
VALUES
    ('00000000000000000000000000015fd8'::uuid, '00000000000000000000000000015fd6'::uuid, 1, 1, false, '2026-11-01'::date, 0, 'run', 'REC009', false, false, false, false, 'Trial', 'committed', NULL, NULL, NULL, NULL);

INSERT INTO session_completions (id, session_uid, activity_id, strong_workout_id, manual_session_id, status, match_method, modification_reason, reason_note, version, input_version, updated_at)
VALUES
    ('00000000000000000000000000015fd9'::uuid, '00000000000000000000000000015fd6'::uuid, '00000000000000000000000000015f9c'::uuid, NULL, NULL, 'completed_as_planned', 'explicit', NULL, NULL, 1, 1, '2026-11-02 03:30:00.123400+00:00'::timestamptz);

UPDATE app_state SET calendar_head_version=1 WHERE app_state.id = 1;
