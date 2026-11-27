-- Synthetic setup captured for the saved contract response.
INSERT INTO coach_snapshots (id, operation, as_of, generated_at, calendar_version_number, block_version_id, data_revision, payload, source_fingerprint, source_versions, kb_digest, payload_sha256, kb_package_version, kb_routes, approx_tokens)
VALUES
    ('0000000000000000000000000aa00001'::uuid, 'review_rolling_plan', '2026-11-02'::date, '2026-11-02 03:30:00.125000+00:00'::timestamptz, 0, NULL, 0, '{}'::jsonb, 'fixture', '{}'::jsonb, 'fixture', 'fixture', 'fixture', '{}'::jsonb, 1);

INSERT INTO coach_proposals (id, revision, operation, snapshot_id, base_calendar_version, base_block_version_id, status, submitted_at, decided_at, discarded_at, headline, why, uncertainty, change_triggers, coach_note, legacy_text, confidence, evidence_ids, policy_ids, recipe_ids, escalation, payload, decision_idempotency_key, decision_hash, skill_version, input_hash)
VALUES
    ('0000000000000000000000000aa00002'::uuid, 1, 'review_rolling_plan', '0000000000000000000000000aa00001'::uuid, 0, NULL, 'accepted', '2026-11-01 03:30:00.125000+00:00'::timestamptz, '2026-11-01 03:30:00.125000+00:00'::timestamptz, NULL, 'Synthetic review', '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, NULL, NULL, '{}'::jsonb, '{}', '{}', '{}', NULL, '{}'::jsonb, NULL, NULL, 'test', 'context-read-fixture');

INSERT INTO events (id, name, event_date, distance_m, purpose, goal_time_s, rank, status, result_s, version)
VALUES
    ('0000000000000000000000000aa00003'::uuid, 'Sample Race', '2026-11-01'::date, NULL, 'training', NULL, NULL, 'completed', NULL, 1);

INSERT INTO exception_patches (id, proposal_id, calendar_version_number, category, severity, ladder_level, window_start, window_end, reassess_on, monitor, return_criteria, escalate_criteria, unchanged, status, resolved_at, resolved_by, resolution_note, created_at, version)
VALUES
    ('0000000000000000000000000aa00004'::uuid, '0000000000000000000000000aa00002'::uuid, 0, 'training_response', 'hold', 'next_days', '2026-10-03'::date, '2026-10-13'::date, '2026-11-02'::date, '["synthetic"]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, 'open', NULL, NULL, NULL, '2026-10-03 03:30:00.125000+00:00'::timestamptz, 1);

INSERT INTO exception_findings (id, rule_code, rule_version, category, severity, entity_key, status, summary, evidence, evidence_at, first_seen_at, last_seen_at, patch_id, reviewed_by_proposal_id, closed_at, close_note, version)
VALUES
    ('0000000000000000000000000aa0000a'::uuid, 'SYNTHETIC_CAUTION', 'test', 'training_response', 'caution', 'fixture:0', 'open', 'Synthetic signal', '[{"synthetic": true}]'::jsonb, '2026-10-03 03:30:00.125000+00:00'::timestamptz, '2026-10-03 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, '0000000000000000000000000aa00004'::uuid, NULL, NULL, NULL, 1),
    ('0000000000000000000000000aa0000b'::uuid, 'SYNTHETIC_ESCALATE', 'test', 'symptoms_illness', 'escalate', 'fixture:1', 'addressed', 'Synthetic signal', '[{"synthetic": true}]'::jsonb, '2026-10-03 03:30:00.125000+00:00'::timestamptz, '2026-10-03 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, '0000000000000000000000000aa00004'::uuid, NULL, NULL, NULL, 1),
    ('0000000000000000000000000aa0000c'::uuid, 'POST_EVENT_REVIEW_DUE', 'test', 'training_response', 'observe', 'event:00000000-0000-0000-0000-00000aa00003', 'open', 'Synthetic signal', '[{"synthetic": true}]'::jsonb, '2026-11-01 03:30:00.125000+00:00'::timestamptz, '2026-11-01 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, NULL, NULL, NULL, 1),
    ('0000000000000000000000000aa0000d'::uuid, 'BLOCK_BENCHMARK_MISSED', 'test', 'training_response', 'observe', 'fixture:3', 'open', 'Synthetic signal', '[{"synthetic": true}]'::jsonb, '2026-11-01 03:30:00.125000+00:00'::timestamptz, '2026-11-01 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, NULL, NULL, NULL, 1),
    ('0000000000000000000000000aa0000e'::uuid, 'BLOCK_BENCHMARK_COMPLETED', 'test', 'training_response', 'observe', 'fixture:4', 'open', 'Synthetic signal', '[{"synthetic": true}]'::jsonb, '2026-11-01 03:30:00.125000+00:00'::timestamptz, '2026-11-01 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, NULL, NULL, NULL, 1),
    ('0000000000000000000000000aa0000f'::uuid, 'RECENT_TERMINAL', 'test', 'training_response', 'hold', 'fixture:5', 'resolved', 'Synthetic signal', '[{"synthetic": true}]'::jsonb, '2026-10-19 03:30:00.125000+00:00'::timestamptz, '2026-10-19 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, NULL, NULL, NULL, 1),
    ('0000000000000000000000000aa00010'::uuid, 'OLD_TERMINAL', 'test', 'training_response', 'hold', 'fixture:6', 'dismissed', 'Synthetic signal', '[{"synthetic": true}]'::jsonb, '2026-10-18 03:30:00.125000+00:00'::timestamptz, '2026-10-18 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, NULL, NULL, NULL, 1);

INSERT INTO trips (id, status, start_date, end_date, destination_label, destination_tz, source, confidence, running_access, gym_access, day_availability, edited, detected, review_reason, version)
VALUES
    ('0000000000000000000000000aa0001e'::uuid, 'pending', '2026-09-26'::date, NULL, 'Synthetic City', 'Asia/Tokyo', 'detected', 'medium', NULL, 'limited', '[{"date": "2026-11-02", "availability": "reduced"}]'::jsonb, false, '{}'::jsonb, NULL, 1),
    ('0000000000000000000000000aa0001f'::uuid, 'confirmed', '2026-09-25'::date, NULL, 'Synthetic City', 'Asia/Tokyo', 'detected', 'medium', NULL, 'limited', '[{"date": "2026-11-02", "availability": "reduced"}]'::jsonb, false, '{}'::jsonb, NULL, 1),
    ('0000000000000000000000000aa00020'::uuid, 'confirmed', '2027-03-02'::date, '2027-03-03'::date, 'Synthetic City', 'Asia/Tokyo', 'detected', 'medium', NULL, 'limited', '[{"date": "2026-11-02", "availability": "reduced"}]'::jsonb, false, '{}'::jsonb, NULL, 1),
    ('0000000000000000000000000aa00021'::uuid, 'confirmed', '2027-03-03'::date, '2027-03-04'::date, 'Synthetic City', 'Asia/Tokyo', 'detected', 'medium', NULL, 'limited', '[{"date": "2026-11-02", "availability": "reduced"}]'::jsonb, false, '{}'::jsonb, NULL, 1),
    ('0000000000000000000000000aa00022'::uuid, 'dismissed', '2026-11-02'::date, NULL, 'Synthetic City', 'Asia/Tokyo', 'detected', 'medium', NULL, 'limited', '[{"date": "2026-11-02", "availability": "reduced"}]'::jsonb, false, '{}'::jsonb, NULL, 1);

INSERT INTO gcal_events (id, google_event_id, event_type, google_status, summary, location_codes, all_day, start_at, end_at, start_date, end_date, start_tz, end_tz, transparency, response_status, busy, flight_code, destination_label, category, auto_category, category_source, flight_confidence, content_hash, google_updated_at, first_seen_at, changed_at, removed_at, version)
VALUES
    ('0000000000000000000000000aa00028'::uuid, 'snapshot-test-0', 'default', 'confirmed', 'Private synthetic text', '[]'::jsonb, false, '2026-11-02 03:30:00.125000+00:00'::timestamptz, '2026-11-03 03:30:00.125000+00:00'::timestamptz, NULL, NULL, 'America/New_York', 'Asia/Tokyo', 'opaque', NULL, true, NULL, NULL, 'flight', 'flight', 'auto', NULL, 'test', NULL, '2026-11-02 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, 1);

INSERT INTO gcal_events (id, google_event_id, event_type, google_status, summary, location_codes, all_day, start_at, end_at, start_date, end_date, start_tz, end_tz, transparency, response_status, busy, flight_code, destination_label, category, auto_category, category_source, flight_confidence, content_hash, google_updated_at, first_seen_at, changed_at, removed_at, version)
VALUES
    ('0000000000000000000000000aa00029'::uuid, 'snapshot-test-1', 'default', 'confirmed', 'Private synthetic text', '[]'::jsonb, false, '2026-11-03 03:30:00.125000+00:00'::timestamptz, '2026-11-04 03:30:00.125000+00:00'::timestamptz, NULL, NULL, 'Bad/Zone', 'Asia/Tokyo', 'opaque', NULL, true, NULL, NULL, 'flight', 'flight', 'auto', NULL, 'test', NULL, '2026-11-02 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, 1);

INSERT INTO trip_legs (id, trip_id, gcal_event_id, leg_hash, seq)
VALUES
    ('0000000000000000000000000aa00032'::uuid, '0000000000000000000000000aa0001e'::uuid, '0000000000000000000000000aa00028'::uuid, 'test', 0);

INSERT INTO gcal_events (id, google_event_id, event_type, google_status, summary, location_codes, all_day, start_at, end_at, start_date, end_date, start_tz, end_tz, transparency, response_status, busy, flight_code, destination_label, category, auto_category, category_source, flight_confidence, content_hash, google_updated_at, first_seen_at, changed_at, removed_at, version)
VALUES
    ('0000000000000000000000000aa0002a'::uuid, 'snapshot-test-2', 'default', 'confirmed', 'Private synthetic text', '[]'::jsonb, false, '2026-11-04 03:30:00.125000+00:00'::timestamptz, '2026-11-05 03:30:00.125000+00:00'::timestamptz, NULL, NULL, 'UTC', 'UTC', 'opaque', 'declined', true, NULL, NULL, 'flight', 'flight', 'auto', NULL, 'test', NULL, '2026-11-02 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, 1);

INSERT INTO trip_legs (id, trip_id, gcal_event_id, leg_hash, seq)
VALUES
    ('0000000000000000000000000aa00033'::uuid, '0000000000000000000000000aa0001e'::uuid, '0000000000000000000000000aa00029'::uuid, 'test', 1);

INSERT INTO import_batches (id, source_kind, status, finished_at, adapter_version, counters, error_code)
VALUES
    ('0000000000000000000000000aa0003c'::uuid, 'google_calendar', 'complete', '2026-11-02 03:30:00.125000+00:00'::timestamptz, 'unknown', '{}'::jsonb, NULL),
    ('0000000000000000000000000aa0003d'::uuid, 'google_calendar', 'failed', '2026-11-03 03:30:00.125000+00:00'::timestamptz, 'unknown', '{}'::jsonb, NULL);

INSERT INTO trip_legs (id, trip_id, gcal_event_id, leg_hash, seq)
VALUES
    ('0000000000000000000000000aa00034'::uuid, '0000000000000000000000000aa0001e'::uuid, '0000000000000000000000000aa0002a'::uuid, 'test', 2);
