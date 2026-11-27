-- Synthetic setup captured for the saved contract response.
INSERT INTO activities (id, source_account_id, garmin_id, source_identity, start_at, original_start, source_timezone, local_date, sport, subtype, distance_m, elapsed_s, timer_s, end_at, fit_file_id, workout_rpe, workout_feel, fit_status, moving_s, avg_hr_bpm, cadence_spm, source_workout_label, canonical_revision, resolution_state, field_provenance)
VALUES
    ('000000000000000000000000000017d4'::uuid, NULL, NULL, NULL, '2021-07-10 04:00:00+00:00'::timestamptz, 'fixture', NULL, '2000-01-01'::date, 'running', NULL, 1000.5, NULL, 0, NULL, NULL, 3.5, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb),
    ('000000000000000000000000000017d5'::uuid, NULL, NULL, NULL, '2021-11-08 04:59:59.999999+00:00'::timestamptz, 'fixture', NULL, '2000-01-01'::date, 'trail_running', NULL, 1000.5, NULL, NULL, NULL, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb),
    ('000000000000000000000000000017d6'::uuid, NULL, NULL, NULL, '2021-07-10 04:00:00+00:00'::timestamptz, 'fixture', NULL, '2000-01-01'::date, 'treadmill_running', NULL, 1000.5, NULL, NULL, NULL, NULL, 3.5, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb),
    ('000000000000000000000000000017d7'::uuid, NULL, NULL, NULL, '2021-07-10 04:00:00+00:00'::timestamptz, 'fixture', NULL, '2000-01-01'::date, 'running', NULL, 1000.5, NULL, NULL, NULL, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb),
    ('000000000000000000000000000017d8'::uuid, NULL, NULL, NULL, '2021-07-09 04:00:00+00:00'::timestamptz, 'fixture', NULL, '2000-01-01'::date, 'running', NULL, 1000.5, NULL, NULL, NULL, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb),
    ('000000000000000000000000000017d9'::uuid, NULL, NULL, NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'fixture', NULL, '2000-01-01'::date, 'running', NULL, 1000.5, NULL, NULL, NULL, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb),
    ('000000000000000000000000000017da'::uuid, NULL, NULL, NULL, '2021-07-10 04:00:00+00:00'::timestamptz, 'fixture', NULL, '2000-01-01'::date, 'cycling', NULL, 1000.5, NULL, NULL, NULL, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb),
    ('000000000000000000000000000017db'::uuid, NULL, NULL, NULL, '2021-07-10 04:00:00+00:00'::timestamptz, 'fixture', NULL, '2000-01-01'::date, 'running', NULL, 1000.5, NULL, NULL, NULL, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb),
    ('000000000000000000000000000017dc'::uuid, NULL, NULL, NULL, '2021-07-10 04:00:00+00:00'::timestamptz, 'fixture', NULL, '2000-01-01'::date, 'running', NULL, 1000.5, NULL, NULL, NULL, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'unresolved', '{}'::jsonb);

INSERT INTO session_rpe (id, activity_id, strong_workout_id, manual_session_id, rpe, source, collected_at, collection_delay_s)
VALUES
    ('b13934d9fb9746d1bb62e0963bb30f44'::uuid, '000000000000000000000000000017d4'::uuid, NULL, NULL, 0, 'manual', '2021-07-10 04:00:00+00:00'::timestamptz, NULL),
    ('a9601ce91743469292899b62a7ac7089'::uuid, '000000000000000000000000000017d4'::uuid, NULL, NULL, 2, 'garmin_fit', '2021-07-11 04:00:00+00:00'::timestamptz, NULL),
    ('4b49e8784b9e4a56900dada2de231d15'::uuid, '000000000000000000000000000017d5'::uuid, NULL, NULL, 4, 'garmin_fit', '2021-11-08 05:00:00+00:00'::timestamptz, NULL);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('00000000000000000000000000001838'::uuid, 'work_interval_execution', 'v2', 'activity', '00000000-0000-0000-0000-0000000017d4', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('00000000000000000000000000001839'::uuid, 'planned_actual_session', 'v2', 'activity', '00000000-0000-0000-0000-0000000017d4', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('0000000000000000000000000000183a'::uuid, 'run_volume_frequency', 'v1', 'activity', '00000000-0000-0000-0000-0000000017d4', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('0000000000000000000000000000183b'::uuid, 'symptom_response_timeline', 'v1', 'activity', '00000000-0000-0000-0000-0000000017d4', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('0000000000000000000000000000183c'::uuid, 'long_run_exposure', 'v1', 'activity', '00000000-0000-0000-0000-0000000017d4', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('0000000000000000000000000000183d'::uuid, 'session_rpe_load', 'v1', 'activity', '00000000-0000-0000-0000-0000000017d4', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('0000000000000000000000000000183e'::uuid, 'intensity_time_distribution', 'v1', 'activity', '00000000-0000-0000-0000-0000000017d4', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('0000000000000000000000000000183f'::uuid, 'recovery_multisignal_summary', 'v1', 'activity', '00000000-0000-0000-0000-0000000017d4', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('00000000000000000000000000001840'::uuid, 'hard_session_spacing', 'v1', 'activity', '00000000-0000-0000-0000-0000000017d4', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('00000000000000000000000000001841'::uuid, 'aerobic_efficiency', 'v1', 'activity', '00000000-0000-0000-0000-0000000017d4', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('00000000000000000000000000001842'::uuid, 'work_interval_execution', 'v2', 'night', 'night:2021-07-11', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('00000000000000000000000000001843'::uuid, 'work_interval_execution', 'v2', 'night', 'night:2021-07-10', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('00000000000000000000000000001844'::uuid, 'work_interval_execution', 'v2', 'window', 'w84:2021-11-07:run', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('00000000000000000000000000001845'::uuid, 'work_interval_execution', 'v2', 'window', 'w7:2021-11-07:strength', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('00000000000000000000000000001846'::uuid, 'work_interval_execution', 'v2', 'window', 'w14:2021-11-07', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('00000000000000000000000000001847'::uuid, 'work_interval_execution', 'v2', 'window', 'w14:2021-11-08', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('00000000000000000000000000001848'::uuid, 'work_interval_execution', 'v2', 'activity', '00000000-0000-0000-0000-0000000017db', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('00000000000000000000000000001849'::uuid, 'work_interval_execution', 'old', 'activity', '00000000-0000-0000-0000-0000000017d4', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('0000000000000000000000000000184a'::uuid, 'work_interval_execution', 'v2', 'activity', '00000000-0000-0000-0000-0000000017d5', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', false);

INSERT INTO metric_results (id, metric_id, method_version, subject_type, subject_key, window_start, window_end, window_label, status, quality_status, value, unit, reason_codes, quality_flags, source_refs, anchor_keys, config_hash, anchor_set_hash, calculated_at, dependency_hash, timezone, is_current)
VALUES
    ('0000000000000000000000000000184b'::uuid, 'unknown_metric', 'v1', 'activity', '00000000-0000-0000-0000-0000000017d4', NULL, NULL, NULL, 'available', 'limited', '{"measured": 12.5}'::jsonb, 'm', '{fixture}', '{}', '{"private": "excluded"}'::jsonb, '{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2021-11-08 05:00:00+00:00'::timestamptz, 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'America/New_York', true);

INSERT INTO activity_annotations (id, activity_id, version, workout_label, notes, excluded)
VALUES
    ('863155266da545cdb507c11e0e6752ff'::uuid, '000000000000000000000000000017d4'::uuid, 1, NULL, NULL, true),
    ('298b36f45aea4460a3d9124200633e33'::uuid, '000000000000000000000000000017d4'::uuid, 2, NULL, NULL, false),
    ('c2c0dc58e4ff49ef9e3c4863de9fd171'::uuid, '000000000000000000000000000017db'::uuid, 1, NULL, NULL, true);

INSERT INTO coverage_intervals (id, dataset, start_date, end_date, observed_start, observed_end, status, completed_at, reason, fully_enumerated)
VALUES
    ('df95898fe96f40788ac5e003dbaa55bc'::uuid, 'activities', '2021-07-09'::date, '2021-07-10'::date, NULL, NULL, 'complete', '2021-11-08 05:00:00+00:00'::timestamptz, NULL, true),
    ('cd12da3fd6fe4288ba33adca765deb44'::uuid, 'sleep', '2021-11-07'::date, '2021-11-08'::date, NULL, NULL, 'partial', NULL, 'synthetic', false),
    ('5b8dafb5fc584bada3f7e0c3262fd51a'::uuid, 'excluded', '2021-07-09'::date, '2021-07-09'::date, NULL, NULL, 'complete', '2021-11-08 05:00:00+00:00'::timestamptz, NULL, true),
    ('af4d1b761f0c423da8d4367d4148b18d'::uuid, 'excluded', '2021-11-08'::date, '2021-11-08'::date, NULL, NULL, 'complete', '2021-11-08 05:00:00+00:00'::timestamptz, NULL, true);
