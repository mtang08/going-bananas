-- Synthetic setup captured for the saved contract response.
INSERT INTO activities (id, source_account_id, garmin_id, source_identity, start_at, original_start, source_timezone, local_date, sport, subtype, distance_m, elapsed_s, timer_s, end_at, fit_file_id, workout_rpe, workout_feel, fit_status, moving_s, avg_hr_bpm, cadence_spm, source_workout_label, canonical_revision, resolution_state, field_provenance)
VALUES
    ('00000000000000000000000000015f9a'::uuid, NULL, NULL, NULL, '2026-11-02 03:30:00.123400+00:00'::timestamptz, 'test', NULL, '2026-11-02'::date, 'running', NULL, 5100.5, NULL, 1200.5, NULL, NULL, 6, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb),
    ('00000000000000000000000000015f9b'::uuid, NULL, NULL, NULL, '2026-11-02 03:29:00.123400+00:00'::timestamptz, 'test', NULL, '2026-11-02'::date, 'running', NULL, 8000, NULL, 1200.5, NULL, NULL, 6, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb),
    ('00000000000000000000000000015f9c'::uuid, NULL, NULL, NULL, '2026-11-02 03:28:00.123400+00:00'::timestamptz, 'test', NULL, '2026-11-02'::date, 'running', NULL, 5300.5, NULL, 1200.5, NULL, NULL, 6, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb);

INSERT INTO events (id, name, event_date, distance_m, purpose, goal_time_s, rank, status, result_s, version)
VALUES
    ('00000000000000000000000000015f90'::uuid, 'Fixture race 0', '2026-11-01'::date, 5000, 'benchmark', 1103, 2, 'registered', 1100, 1),
    ('00000000000000000000000000015f91'::uuid, 'Fixture race 1', '2026-11-09'::date, 5000, 'benchmark', 1103, 1, 'planned', NULL, 1),
    ('00000000000000000000000000015f92'::uuid, 'Fixture race 2', '2026-10-04'::date, 5000, 'benchmark', 1103, NULL, 'completed', NULL, 1),
    ('00000000000000000000000000015f93'::uuid, 'Fixture race 3', '2026-10-03'::date, 5000, 'benchmark', 1103, NULL, 'cancelled', NULL, 1);

INSERT INTO session_rpe (id, activity_id, strong_workout_id, manual_session_id, rpe, source, collected_at, collection_delay_s)
VALUES
    ('1befa9f8d2964be88782f0881aed96ed'::uuid, '00000000000000000000000000015f9c'::uuid, NULL, NULL, 8, 'manual', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL);

INSERT INTO activity_annotations (id, activity_id, version, workout_label, notes, excluded)
VALUES
    ('065c983763bf49268bf7d4090b9e6256'::uuid, '00000000000000000000000000015f9b'::uuid, 1, NULL, NULL, true);

INSERT INTO blocks (id, block_uid)
VALUES
    ('5d3455df8bc440ada48494b027c347f6'::uuid, '00000000000000000000000000015fa4'::uuid);

INSERT INTO coach_snapshots (id, operation, as_of, generated_at, calendar_version_number, block_version_id, data_revision, payload, source_fingerprint, source_versions, kb_digest, payload_sha256, kb_package_version, kb_routes, approx_tokens)
VALUES
    ('00000000000000000000000000015fae'::uuid, 'review_rolling_plan', '2026-11-01'::date, '2026-11-02 03:30:00.123400+00:00'::timestamptz, 0, NULL, 0, '{}'::jsonb, 'fixture', '{}'::jsonb, 'fixture', 'fixture', 'fixture', '{}'::jsonb, 0);

INSERT INTO block_benchmarks (id, block_uid, block_version, match_method, activity_id, event_id, protocol, distance_m, local_date, result_s, outcome, compared_with, proposal_id)
VALUES
    ('00000000000000000000000000015fa6'::uuid, '00000000000000000000000000015fa4'::uuid, 1, 'auto', '00000000000000000000000000015f9a'::uuid, NULL, 'race_5k', 5000, '2026-11-01'::date, 1103, 'progress', NULL, NULL);

INSERT INTO block_decisions (id, block_uid, decision, from_version, to_version, rationale, evidence_ids, policy_ids, confidence, proposal_id, decided_at)
VALUES
    ('b723c6b1f0ef482096d0612ec75a286c'::uuid, '00000000000000000000000000015fa4'::uuid, 'start', NULL, 1, 'Fixture', '{}', '{}', 'moderate', NULL, '2026-11-02 03:30:00.123400+00:00'::timestamptz);

INSERT INTO block_versions (id, block_uid, version, status, objective, why, maintained_qualities, non_goals, eligible_recipe_ids, progression_dimension, constraints, start_date, review_date, indicators, early_review_triggers, objective_status, proposal_id, benchmark, target_event_id, build_outline, legacy_text)
VALUES
    ('00000000000000000000000000015fa5'::uuid, '00000000000000000000000000015fa4'::uuid, 1, 'active', 'Race benchmark', '[]'::jsonb, '{}', '{}', '{}', 'none', '{}'::jsonb, '2026-10-11'::date, '2026-11-04'::date, '[]'::jsonb, '{}', 'unresolved', NULL, '{"kind": "event", "event_id": "00000000-0000-0000-0000-000000015f90", "planned_date": "2026-11-01", "protocol": "race_5k"}'::jsonb, '00000000000000000000000000015f90'::uuid, '[]'::jsonb, NULL);

INSERT INTO intensity_anchors (id, anchor_key, kind, value_low, value_high, unit, protocol, confidence, status, calibrated_at, valid_from, review_after, source_activity_id, source_event_id, proposal_id, conditions, notes, supersedes_key)
VALUES
    ('4915ad6c20864e5ea477f3c596c38f63'::uuid, 'fixture', 'hr_aerobic_upper', 140, NULL, 'bpm', 'manual', 'low', 'provisional', '2026-11-02 03:30:00.123400+00:00'::timestamptz, '2026-11-01'::date, '2026-11-11'::date, NULL, NULL, NULL, NULL, NULL, NULL);

INSERT INTO coach_proposals (id, revision, operation, snapshot_id, base_calendar_version, base_block_version_id, status, submitted_at, decided_at, discarded_at, headline, why, uncertainty, change_triggers, coach_note, legacy_text, confidence, evidence_ids, policy_ids, recipe_ids, escalation, payload, decision_idempotency_key, decision_hash, skill_version, input_hash)
VALUES
    ('00000000000000000000000000015fb8'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-0'),
    ('00000000000000000000000000015fb9'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-1'),
    ('00000000000000000000000000015fba'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-2'),
    ('00000000000000000000000000015fbb'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-3'),
    ('00000000000000000000000000015fbc'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-4'),
    ('00000000000000000000000000015fbd'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-5'),
    ('00000000000000000000000000015fbe'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-6'),
    ('00000000000000000000000000015fbf'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-7'),
    ('00000000000000000000000000015fc0'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-8'),
    ('00000000000000000000000000015fc1'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-9'),
    ('00000000000000000000000000015fc2'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-10'),
    ('00000000000000000000000000015fc3'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-11'),
    ('00000000000000000000000000015fc4'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-12'),
    ('00000000000000000000000000015fc5'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-13'),
    ('00000000000000000000000000015fc6'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-14'),
    ('00000000000000000000000000015fc7'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-15'),
    ('00000000000000000000000000015fc8'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-16'),
    ('00000000000000000000000000015fc9'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-17'),
    ('00000000000000000000000000015fca'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-18'),
    ('00000000000000000000000000015fcb'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": []}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-19'),
    ('00000000000000000000000000015fcc'::uuid, 1, 'review_rolling_plan', '00000000000000000000000000015fae'::uuid, 0, NULL, 'accepted', '2026-11-02 03:30:00.123400+00:00'::timestamptz, NULL, NULL, 'Fixture', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{"changes": [{"change_id": "C2", "material_flags": ["strength_omission"]}]}'::jsonb, NULL, NULL, 'fixture', 'fixture-block-20');

INSERT INTO coach_proposal_changes (id, proposal_id, change_id, op, session_uid, reason, decision)
VALUES
    ('ef6abae24b3146cfad9e3a5fab2e9694'::uuid, '00000000000000000000000000015fcc'::uuid, 'C2', 'add', NULL, 'Fixture', 'accepted'),
    ('ae676f88e717418c8d53446d1ac05d33'::uuid, '00000000000000000000000000015fcc'::uuid, 'C1', 'add', NULL, 'Fixture', 'accepted');
