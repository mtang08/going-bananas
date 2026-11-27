-- Synthetic setup captured for the saved contract response.
INSERT INTO calendar_versions (id, number, parent_number, kind, actor, reason, proposal_id, restored_from_number, block_version_id)
VALUES
    ('5838825f0931400c8d3e28ef3d523a76'::uuid, 1, NULL, 'manual_edit', 'user', NULL, NULL, NULL, NULL),
    ('9d3f552e2e8b41d7913cd97ee8c680cd'::uuid, 2, NULL, 'manual_edit', 'user', NULL, NULL, NULL, NULL),
    ('76bdaf60fd7644a6880dae76b32a92dd'::uuid, 3, NULL, 'manual_edit', 'user', NULL, NULL, NULL, NULL);

INSERT INTO calendar_session_revisions (id, session_uid, revision, calendar_version_number, deleted, local_date, slot, kind, recipe_id, custom, locked, legacy_unstructured, placeholder, intent, certainty, planned_duration_s, planned_distance_m, strength_slot_id, notes)
VALUES
    ('30e9322881f54c95a4a9b5ea566cad44'::uuid, '00000000000000000000000000003e81'::uuid, 1, 1, false, '2026-03-08'::date, 0, 'run', NULL, false, false, false, false, 'Synthetic', 'committed', NULL, NULL, NULL, NULL),
    ('35aa19a10f7a4d79a5c822d4cdf779fd'::uuid, '00000000000000000000000000003e81'::uuid, 2, 2, false, '2026-03-15'::date, 0, 'run', NULL, false, false, false, false, 'Synthetic', 'committed', NULL, NULL, NULL, NULL),
    ('988c81bf751a47bf8c882dfa06d6382b'::uuid, '00000000000000000000000000003e81'::uuid, 3, 3, false, '2026-03-08'::date, 0, 'run', NULL, false, false, false, false, 'Synthetic', 'committed', NULL, NULL, NULL, NULL),
    ('118b650c8ca14f33b1cdd08690d44f30'::uuid, '00000000000000000000000000003e82'::uuid, 1, 1, false, '2025-11-08'::date, 0, 'run', NULL, false, false, false, false, 'Synthetic', 'committed', NULL, NULL, NULL, NULL),
    ('d31f37e7e8224056a2903009f8cc95c5'::uuid, '00000000000000000000000000003e83'::uuid, 1, 1, false, '2025-11-07'::date, 0, 'run', NULL, false, false, false, false, 'Synthetic', 'committed', NULL, NULL, NULL, NULL),
    ('ad258a9d0369458f9cc4dbc7c31e5160'::uuid, '00000000000000000000000000003e84'::uuid, 1, 1, false, '2026-04-19'::date, 0, 'run', NULL, false, false, false, false, 'Synthetic', 'committed', NULL, NULL, NULL, NULL),
    ('091a51176d3646c889a70d284665335a'::uuid, '00000000000000000000000000003e85'::uuid, 1, 1, false, '2026-04-20'::date, 0, 'run', NULL, false, false, false, false, 'Synthetic', 'committed', NULL, NULL, NULL, NULL),
    ('f9055f80b60a4bb4814266564f7b6a52'::uuid, '00000000000000000000000000003e86'::uuid, 1, 1, false, '2026-03-09'::date, 0, 'run', NULL, false, false, false, false, 'Synthetic', 'committed', NULL, NULL, NULL, NULL),
    ('60aac5f290f84c7ea92b511277016d76'::uuid, '00000000000000000000000000003e86'::uuid, 2, 2, true, '2026-03-09'::date, 0, 'run', NULL, false, false, false, false, 'Synthetic', 'committed', NULL, NULL, NULL, NULL);

INSERT INTO session_completions (id, session_uid, activity_id, strong_workout_id, manual_session_id, status, match_method, modification_reason, reason_note, version, input_version, updated_at)
VALUES
    ('720fba4dc37d4ad6aaa124b5cb32c437'::uuid, '00000000000000000000000000003e81'::uuid, NULL, NULL, NULL, 'skipped', 'user_marked', NULL, NULL, 1, 1, '2026-03-08 00:00:00+00:00'::timestamptz);

UPDATE app_state SET calendar_head_version=2 WHERE app_state.id = 1;

INSERT INTO raw_objects (id, sha256, relative_path, byte_size, media_type)
VALUES
    ('7b450cfe1d4a4a51974c0f80509cb340'::uuid, 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', 'synthetic', 0, 'text/csv');

INSERT INTO source_accounts (id, provider, account_scope)
VALUES
    ('c09a08ac9c044ac9a56e684abe05008c'::uuid, 'strong', 'snapshot-parity');

INSERT INTO goals (id, text, horizon, priority, status, version)
VALUES
    ('30503ff83e164fceb569cc51d46c51cc'::uuid, 'Synthetic goal', 'season', 1, 'active', 1),
    ('8243211dcc7d491a8dda6aca51050c8c'::uuid, 'Synthetic goal', 'season', 2, 'paused', 1);

INSERT INTO strength_routine_slots (id, label, default_weekday, lower_body_cost, typical_duration_s, main_lower_body_lifts, active, version)
VALUES
    ('ba9c6fc1477a4b18b9609a733cfc836d'::uuid, 'Synthetic', 1, 'low', NULL, '{}', true, 1);

INSERT INTO source_records (id, source_account_id, import_batch_id, raw_object_id, source_identity, payload_hash, fetched_at, source_modified_at, parser_version, source_kind, fields, rejected_reason)
VALUES
    ('f203ffba0e884e78a50b47b9c84d46e3'::uuid, 'c09a08ac9c044ac9a56e684abe05008c'::uuid, NULL, '7b450cfe1d4a4a51974c0f80509cb340'::uuid, 'synthetic', 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', '2026-03-08 00:00:00+00:00'::timestamptz, NULL, '1', 'strength', '{}'::jsonb, NULL);

INSERT INTO strong_workouts (id, source_account_id, source_identity, source_record_id, raw_object_id, payload_hash, local_date, local_start, workout_name, duration_s, sets, row_count, resolution_state)
VALUES
    ('fb31e62f2f98429785d41ac2e2ddebdd'::uuid, 'c09a08ac9c044ac9a56e684abe05008c'::uuid, '1', 'f203ffba0e884e78a50b47b9c84d46e3'::uuid, '7b450cfe1d4a4a51974c0f80509cb340'::uuid, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', '2026-03-08'::date, '2026-03-08T08:00:00', 'Synthetic', 1200, '[]'::jsonb, 1, 'resolved');

INSERT INTO session_rpe (id, activity_id, strong_workout_id, manual_session_id, rpe, source, collected_at, collection_delay_s)
VALUES
    ('4802ad099b234cf698356a1c9a2269ff'::uuid, NULL, 'fb31e62f2f98429785d41ac2e2ddebdd'::uuid, NULL, 3, 'manual', '2026-03-08 00:00:00+00:00'::timestamptz, NULL),
    ('ea8da5810a164e03b39f19555eb1041e'::uuid, NULL, 'fb31e62f2f98429785d41ac2e2ddebdd'::uuid, NULL, 6, 'garmin_fit', '2026-03-08 00:00:00+00:00'::timestamptz, NULL);

INSERT INTO strong_workouts (id, source_account_id, source_identity, source_record_id, raw_object_id, payload_hash, local_date, local_start, workout_name, duration_s, sets, row_count, resolution_state)
VALUES
    ('d95528d271e94e4f953396080ca4e6eb'::uuid, 'c09a08ac9c044ac9a56e684abe05008c'::uuid, '2', 'f203ffba0e884e78a50b47b9c84d46e3'::uuid, '7b450cfe1d4a4a51974c0f80509cb340'::uuid, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', '2025-11-07'::date, '2026-03-08T08:00:00', 'Synthetic', 1200, '[]'::jsonb, 1, 'resolved');

INSERT INTO session_rpe (id, activity_id, strong_workout_id, manual_session_id, rpe, source, collected_at, collection_delay_s)
VALUES
    ('950323b73cb74a90a7c96a85a4f73694'::uuid, NULL, 'd95528d271e94e4f953396080ca4e6eb'::uuid, NULL, 3, 'manual', '2026-03-08 00:00:00+00:00'::timestamptz, NULL),
    ('930f5f9ff37a4c6187e77eefa81bbe51'::uuid, NULL, 'd95528d271e94e4f953396080ca4e6eb'::uuid, NULL, 6, 'garmin_fit', '2026-03-08 00:00:00+00:00'::timestamptz, NULL);

INSERT INTO strong_workouts (id, source_account_id, source_identity, source_record_id, raw_object_id, payload_hash, local_date, local_start, workout_name, duration_s, sets, row_count, resolution_state)
VALUES
    ('8312b46225904113adea58b7c2c9b61b'::uuid, 'c09a08ac9c044ac9a56e684abe05008c'::uuid, '3', 'f203ffba0e884e78a50b47b9c84d46e3'::uuid, '7b450cfe1d4a4a51974c0f80509cb340'::uuid, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', '2026-03-09'::date, '2026-03-08T08:00:00', 'Synthetic', 1200, '[]'::jsonb, 1, 'resolved');

INSERT INTO session_rpe (id, activity_id, strong_workout_id, manual_session_id, rpe, source, collected_at, collection_delay_s)
VALUES
    ('4101c42c179744978c5c4663cddb1b56'::uuid, NULL, '8312b46225904113adea58b7c2c9b61b'::uuid, NULL, 3, 'manual', '2026-03-08 00:00:00+00:00'::timestamptz, NULL),
    ('d9dc4e9085eb43d49ddae6c092166f29'::uuid, NULL, '8312b46225904113adea58b7c2c9b61b'::uuid, NULL, 6, 'garmin_fit', '2026-03-08 00:00:00+00:00'::timestamptz, NULL);
