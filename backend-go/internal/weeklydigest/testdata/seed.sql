-- Synthetic setup captured for the saved contract response.
INSERT INTO coach_snapshots (id, operation, as_of, generated_at, calendar_version_number, block_version_id, data_revision, payload, source_fingerprint, source_versions, kb_digest, payload_sha256, kb_package_version, kb_routes, approx_tokens)
VALUES
    ('e1b7c471c8f049f59d87c1be4db76c1c'::uuid, 'review_rolling_plan', '2030-01-09'::date, '2030-01-09 18:30:00+00:00'::timestamptz, 0, NULL, 0, '{}'::jsonb, 'weekly', '{}'::jsonb, 'fixture', 'weekly', 'fixture', '{}'::jsonb, 0);

INSERT INTO coach_proposals (id, revision, operation, snapshot_id, base_calendar_version, base_block_version_id, status, submitted_at, decided_at, discarded_at, headline, why, uncertainty, change_triggers, next_check, coach_note, legacy_text, confidence, evidence_ids, policy_ids, recipe_ids, escalation, payload, decision_idempotency_key, decision_hash, skill_version, input_hash)
VALUES
    ('cd8735dc1cc84f88a7a03b76be42bf6b'::uuid, 1, 'review_rolling_plan', 'e1b7c471c8f049f59d87c1be4db76c1c'::uuid, 0, NULL, 'accepted', '2030-01-02 18:30:00+00:00'::timestamptz, '2030-01-04 18:30:00+00:00'::timestamptz, NULL, 'Synthetic', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '{"when": "post-run"}'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{}'::jsonb, NULL, NULL, 'fixture', 'weekly-digest-fixture');

INSERT INTO calendar_versions (id, number, parent_number, kind, actor, reason, proposal_id, restored_from_number, block_version_id)
VALUES
    ('55243902814b4fa9a3cc8b9f62eabe76'::uuid, 1, NULL, 'proposal_accept', 'user', NULL, 'cd8735dc1cc84f88a7a03b76be42bf6b'::uuid, NULL, NULL),
    ('5bd0aee435c9458daf474098bdaa4409'::uuid, 2, 1, 'manual_edit', 'user', NULL, NULL, NULL, NULL);

INSERT INTO calendar_session_revisions (id, session_uid, revision, calendar_version_number, deleted, local_date, slot, kind, recipe_id, custom, locked, legacy_unstructured, placeholder, intent, certainty, planned_duration_s, planned_distance_m, strength_slot_id, notes)
VALUES
    ('bf57d71af81146dc8a0ea0626b756ef4'::uuid, 'c786ea52ebc64a1fa9745d7fdb47029d'::uuid, 1, 1, false, '2030-01-07'::date, 0, 'run', 'REC002', false, false, false, false, 'Long', 'committed', 1800, NULL, NULL, NULL),
    ('4335242e234643e3959e8c93ca362ffe'::uuid, '3e194f7ade44421c889e78beca161286'::uuid, 1, 1, false, '2030-01-08'::date, 0, 'run', 'REC003', false, false, false, false, 'Tempo', 'committed', 1200, NULL, NULL, NULL),
    ('ebe2b5a35e834c91a472085934af19cd'::uuid, '5eacb7f13e874912bfc9f456003dcd4a'::uuid, 1, 1, false, '2030-01-08'::date, 0, 'strength', NULL, true, false, false, false, 'Lift', 'committed', NULL, NULL, NULL, NULL),
    ('4c1b646c185d4939906a53eb6d33c76a'::uuid, '81359c7e2d6d4fa3b6ebefa4b4e0ffb0'::uuid, 1, 1, false, '2030-01-09'::date, 0, 'run', NULL, true, false, false, false, 'Easy', 'committed', 1000, NULL, NULL, NULL),
    ('dd8d883eea5f4511919c182e198021ad'::uuid, '6f3e92aa23e347cd9a934633f4c54ce9'::uuid, 1, 1, false, '2030-01-12'::date, 0, 'run', NULL, true, false, false, false, 'Future', 'committed', NULL, NULL, NULL, NULL),
    ('c7de67da96a9471d9cce1d49c2ade8df'::uuid, 'a7c8cdcad3554fc4bee5aaa84b77173f'::uuid, 1, 1, false, '2030-01-11'::date, 0, 'run', NULL, true, false, false, false, 'Moved', 'committed', 1600, NULL, NULL, NULL),
    ('91ac0097841e4b41ad5cd9e9b24a8486'::uuid, 'f0f6c95ff2fa4523852baa44e7680b72'::uuid, 1, 1, false, '2030-01-07'::date, 0, 'mobility', NULL, true, false, false, false, 'Mobility', 'committed', NULL, NULL, NULL, NULL),
    ('2efd97fec83e40538ea48f8544b1272e'::uuid, 'ced87c392a4a4f24963ea9ee52418a07'::uuid, 1, 1, false, '2030-01-08'::date, 0, 'run', NULL, true, false, false, false, 'Removed', 'committed', NULL, NULL, NULL, NULL),
    ('51d420b0355142198b637431cddbbf95'::uuid, 'acfa3b12b268410a93030bb8703c8ab0'::uuid, 1, 1, false, '2030-01-08'::date, 0, 'run', NULL, true, false, false, false, 'Self-reported', 'committed', 1800, NULL, NULL, NULL),
    ('35ef16d824f442f096765956ce3d13bf'::uuid, '3e194f7ade44421c889e78beca161286'::uuid, 2, 2, false, '2030-01-08'::date, 0, 'run', 'REC003', false, false, false, false, 'Tempo modified', 'committed', 1500, 5000, NULL, NULL),
    ('bc413a5a9d42469f8601f26d19bd7c06'::uuid, 'ced87c392a4a4f24963ea9ee52418a07'::uuid, 2, 2, true, '2030-01-09'::date, 0, 'run', NULL, true, false, false, false, 'Removed', 'committed', NULL, NULL, NULL, NULL);

UPDATE app_state SET calendar_head_version=2 WHERE app_state.id = 1;

UPDATE calendar_session_revisions SET brief='{"effort": "Firm"}'::jsonb WHERE calendar_session_revisions.id = '4335242e234643e3959e8c93ca362ffe'::uuid;

INSERT INTO coach_proposal_changes (id, proposal_id, change_id, op, session_uid, reason, decision)
VALUES
    ('eef57fc377254acb89230159491423b9'::uuid, 'cd8735dc1cc84f88a7a03b76be42bf6b'::uuid, 'C1', 'modify', '3e194f7ade44421c889e78beca161286'::uuid, 'Adjust dose', 'accepted');

INSERT INTO activities (id, source_account_id, garmin_id, source_identity, start_at, original_start, source_timezone, local_date, sport, subtype, distance_m, elapsed_s, timer_s, end_at, fit_file_id, workout_rpe, workout_feel, fit_status, moving_s, avg_hr_bpm, cadence_spm, source_workout_label, canonical_revision, resolution_state, field_provenance)
VALUES
    ('a9c701b456004f3fa5122e38d7e4216d'::uuid, NULL, NULL, NULL, '2030-01-07 12:00:00+00:00'::timestamptz, '2030-01-07T12:00:00+00:00', NULL, '2030-01-07'::date, 'running', NULL, 4100, NULL, 1800, NULL, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb);

INSERT INTO activities (id, source_account_id, garmin_id, source_identity, start_at, original_start, source_timezone, local_date, sport, subtype, distance_m, elapsed_s, timer_s, end_at, fit_file_id, workout_rpe, workout_feel, fit_status, moving_s, avg_hr_bpm, cadence_spm, source_workout_label, canonical_revision, resolution_state, field_provenance)
VALUES
    ('4d8b60f81b994cb0adc4fd11367a3b79'::uuid, NULL, NULL, NULL, '2030-01-08 12:00:00+00:00'::timestamptz, '2030-01-08T12:00:00+00:00', NULL, '2030-01-08'::date, 'running', NULL, 3800, NULL, 1050, NULL, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb);

INSERT INTO activities (id, source_account_id, garmin_id, source_identity, start_at, original_start, source_timezone, local_date, sport, subtype, distance_m, elapsed_s, timer_s, end_at, fit_file_id, workout_rpe, workout_feel, fit_status, moving_s, avg_hr_bpm, cadence_spm, source_workout_label, canonical_revision, resolution_state, field_provenance)
VALUES
    ('89520a5e7a5b4db6b3878768c1af0f46'::uuid, NULL, NULL, NULL, '2030-01-06 12:00:00+00:00'::timestamptz, '2030-01-06T12:00:00+00:00', NULL, '2030-01-06'::date, 'running', NULL, 3700, NULL, 1550, NULL, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb);

INSERT INTO session_rpe (id, activity_id, strong_workout_id, manual_session_id, rpe, source, collected_at, collection_delay_s)
VALUES
    ('021af5ab9bca412698370796977faba9'::uuid, '4d8b60f81b994cb0adc4fd11367a3b79'::uuid, NULL, NULL, 6.5, 'manual', '2030-01-09 18:30:00+00:00'::timestamptz, NULL);

UPDATE activities SET end_at='2030-01-08 12:17:30+00:00'::timestamptz, moving_s=990, avg_hr_bpm=133 WHERE activities.id = '4d8b60f81b994cb0adc4fd11367a3b79'::uuid;

INSERT INTO activities (id, source_account_id, garmin_id, source_identity, start_at, original_start, source_timezone, local_date, sport, subtype, distance_m, elapsed_s, timer_s, end_at, fit_file_id, workout_rpe, workout_feel, fit_status, moving_s, avg_hr_bpm, cadence_spm, source_workout_label, canonical_revision, resolution_state, field_provenance)
VALUES
    ('6a1fd76e3ab748efb2e113a37a7268ed'::uuid, NULL, NULL, NULL, '2030-01-08 12:00:00+00:00'::timestamptz, '2030-01-08T12:00:00+00:00', NULL, '2030-01-08'::date, 'running', NULL, 9999, NULL, 900, NULL, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb);

INSERT INTO activities (id, source_account_id, garmin_id, source_identity, start_at, original_start, source_timezone, local_date, sport, subtype, distance_m, elapsed_s, timer_s, end_at, fit_file_id, workout_rpe, workout_feel, fit_status, moving_s, avg_hr_bpm, cadence_spm, source_workout_label, canonical_revision, resolution_state, field_provenance)
VALUES
    ('25c87078b7224788afcf5640ba6f6247'::uuid, NULL, NULL, NULL, '2030-01-07 12:00:00+00:00'::timestamptz, '2030-01-07T12:00:00+00:00', NULL, '2030-01-07'::date, 'running', NULL, 999, NULL, 350, NULL, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb);

INSERT INTO activity_annotations (id, activity_id, version, workout_label, notes, excluded)
VALUES
    ('3c2e0fc305694a078ccc194c3f2b5cc9'::uuid, '6a1fd76e3ab748efb2e113a37a7268ed'::uuid, 1, NULL, NULL, true);

INSERT INTO activities (id, source_account_id, garmin_id, source_identity, start_at, original_start, source_timezone, local_date, sport, subtype, distance_m, elapsed_s, timer_s, end_at, fit_file_id, workout_rpe, workout_feel, fit_status, moving_s, avg_hr_bpm, cadence_spm, source_workout_label, canonical_revision, resolution_state, field_provenance)
VALUES
    ('81e63737d5b44399ac2b547212fa9de9'::uuid, NULL, NULL, NULL, '2030-01-07 02:00:00+00:00'::timestamptz, '2030-01-07T02:00:00+00:00', NULL, '2030-01-07'::date, 'running', NULL, 400, NULL, 200, NULL, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb);

INSERT INTO raw_objects (id, sha256, relative_path, byte_size, media_type)
VALUES
    ('966b0bdf2a2640a6a7d8020bfad5ec44'::uuid, '15da56889b5b4b82a2acafd579a2452d15da56889b5b4b82a2acafd579a2452d', '15da56889b5b4b82a2acafd579a2452d', 1, 'text/csv');

INSERT INTO source_accounts (id, provider, account_scope)
VALUES
    ('2bd60491a71a4b73aaa26f172eebcd64'::uuid, 'strong', '15da56889b5b4b82a2acafd579a2452d');

INSERT INTO source_records (id, source_account_id, import_batch_id, raw_object_id, source_identity, payload_hash, fetched_at, source_modified_at, parser_version, source_kind, fields, rejected_reason)
VALUES
    ('42c096cbafa847f386ff2fc19766e46f'::uuid, '2bd60491a71a4b73aaa26f172eebcd64'::uuid, NULL, '966b0bdf2a2640a6a7d8020bfad5ec44'::uuid, '15da56889b5b4b82a2acafd579a2452d', '15da56889b5b4b82a2acafd579a2452d15da56889b5b4b82a2acafd579a2452d', '2026-11-27 22:42:56.540664+00:00'::timestamptz, NULL, 't', 'strong_csv', '{}'::jsonb, NULL);

INSERT INTO strong_workouts (id, source_account_id, source_identity, source_record_id, raw_object_id, payload_hash, local_date, local_start, workout_name, duration_s, sets, row_count, resolution_state)
VALUES
    ('4da46eba21064030abcf7936d30ebe01'::uuid, '2bd60491a71a4b73aaa26f172eebcd64'::uuid, '15da56889b5b4b82a2acafd579a2452d', '42c096cbafa847f386ff2fc19766e46f'::uuid, '966b0bdf2a2640a6a7d8020bfad5ec44'::uuid, '15da56889b5b4b82a2acafd579a2452d15da56889b5b4b82a2acafd579a2452d', '2030-01-08'::date, '2030-01-08T12:00:00', 'w', 3000, '[]'::jsonb, 0, 'resolved');

INSERT INTO session_completions (id, session_uid, activity_id, strong_workout_id, manual_session_id, status, match_method, modification_reason, reason_note, version, input_version, updated_at)
VALUES
    ('a07fe21194b244a481a377f0795ef943'::uuid, 'c786ea52ebc64a1fa9745d7fdb47029d'::uuid, 'a9c701b456004f3fa5122e38d7e4216d'::uuid, NULL, NULL, 'completed_as_planned', 'explicit', NULL, NULL, 1, 1, '2030-01-09 18:30:00+00:00'::timestamptz),
    ('e44e003287b6480da2ee1ea6aa3ae324'::uuid, '3e194f7ade44421c889e78beca161286'::uuid, '4d8b60f81b994cb0adc4fd11367a3b79'::uuid, NULL, NULL, 'completed_modified', 'explicit', NULL, NULL, 1, 1, '2030-01-09 18:30:00+00:00'::timestamptz),
    ('98f5bb74fc6d4fca93ea87a9085b037f'::uuid, '5eacb7f13e874912bfc9f456003dcd4a'::uuid, NULL, '4da46eba21064030abcf7936d30ebe01'::uuid, NULL, 'completed_as_planned', 'explicit', NULL, NULL, 1, 1, '2030-01-09 18:30:00+00:00'::timestamptz),
    ('90bb2960f6864d959c9f061f9b075e43'::uuid, 'a7c8cdcad3554fc4bee5aaa84b77173f'::uuid, '89520a5e7a5b4db6b3878768c1af0f46'::uuid, NULL, NULL, 'moved', 'confirmed_move', NULL, NULL, 1, 1, '2030-01-09 18:30:00+00:00'::timestamptz),
    ('7b8f591c360b4829b5de392e92cf6b9e'::uuid, 'acfa3b12b268410a93030bb8703c8ab0'::uuid, NULL, NULL, NULL, 'completed_as_planned', 'user_marked', NULL, NULL, 1, 1, '2030-01-09 18:30:00+00:00'::timestamptz);

INSERT INTO checkins_v2 (id, idempotency_key, version, kind, observed_at, recorded_at, fatigue, illness, pain_reported, gait_change, context_tags, activity_id, prompt_id, note, schema_version)
VALUES
    ('5ca3ee1e1b7a4c50ac95859d025bfa3a'::uuid, 'weekly-digest', 1, 'delayed_followup', '2030-01-09 18:10:00+00:00'::timestamptz, '2030-01-09 18:30:00+00:00'::timestamptz, NULL, NULL, true, 'no', '{}', '4d8b60f81b994cb0adc4fd11367a3b79'::uuid, NULL, NULL, 2);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('4a45fcc68d91490fa42d5ad85f850b71'::uuid, 'planned_actual_session', 'v2', 'session', '3e194f7a-de44-421c-889e-78beca161286', NULL, NULL, NULL, 'available', NULL, '{"components": [{"name": "time", "value": 0.8, "status": "met"}]}'::jsonb, NULL, '{}', '{}', '{}'::jsonb, '{}', 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', NULL, '2026-11-27 22:42:56.542502+00:00'::timestamptz, 'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd', 'America/New_York', true),
    ('8848d8b330ab4da6a11153b713ecc500'::uuid, 'work_interval_execution', 'v2', 'activity', '4d8b60f8-1b99-4cb0-adc4-fd11367a3b79', NULL, NULL, NULL, 'available', NULL, '{"n_planned": 4, "n_completed": 3}'::jsonb, NULL, '{}', '{}', '{}'::jsonb, '{}', 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', NULL, '2026-11-27 22:42:56.542526+00:00'::timestamptz, 'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd', 'America/New_York', true);

INSERT INTO coverage_intervals (id, dataset, start_date, end_date, observed_start, observed_end, status, completed_at, reason, fully_enumerated)
VALUES
    ('20160bc9bfd94f4fa0544f6a394543f6'::uuid, 'activities', '2030-01-06'::date, '2030-01-09'::date, NULL, NULL, 'complete', NULL, NULL, true);

INSERT INTO manual_sessions (id, version, date, time, kind, duration_s, effort, note, linked_activity_id)
VALUES
    ('d4006d34168243a8b4bbfd825b2f3476'::uuid, 1, '2030-01-09'::date, NULL::TIME WITHOUT TIME ZONE, 'cross', 600, NULL, NULL, NULL),
    ('a8146777ae53408caa1e8bf619eacf04'::uuid, 1, '2030-01-09'::date, NULL::TIME WITHOUT TIME ZONE, 'run', 150, NULL, NULL, '4d8b60f81b994cb0adc4fd11367a3b79'::uuid);

INSERT INTO symptom_reports (id, checkin_id, site, side, severity, timing)
VALUES
    ('10cbc67fee6c48ed90e2069426df57a8'::uuid, '5ca3ee1e1b7a4c50ac95859d025bfa3a'::uuid, 'ankle', 'left', 2.5, 'next_morning');
