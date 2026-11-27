-- Synthetic setup captured for the saved contract response.
INSERT INTO activities (id, source_account_id, garmin_id, source_identity, start_at, original_start, source_timezone, local_date, sport, subtype, distance_m, elapsed_s, timer_s, end_at, fit_file_id, workout_rpe, workout_feel, fit_status, moving_s, avg_hr_bpm, cadence_spm, source_workout_label, canonical_revision, resolution_state, field_provenance)
VALUES
    ('00000000000000000000000000000064'::uuid, NULL, NULL, NULL, '2026-11-01 03:30:00.125000+00:00'::timestamptz, 'test', NULL, '2026-11-02'::date, 'running', NULL, NULL, NULL, NULL, '2026-11-02 02:15:00.125000+00:00'::timestamptz, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb);

INSERT INTO checkins_v2 (id, idempotency_key, version, kind, observed_at, recorded_at, fatigue, illness, pain_reported, gait_change, context_tags, activity_id, prompt_id, note, schema_version)
VALUES
    ('000000000000000000000000000000c8'::uuid, 'phone-first-steps:0', 1, 'exception', '2026-07-05 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, NULL, NULL, NULL, '{}', '00000000000000000000000000000064'::uuid, NULL, 'First steps: no ankle pain.', 2);

INSERT INTO checkins_v2 (id, idempotency_key, version, kind, observed_at, recorded_at, fatigue, illness, pain_reported, gait_change, context_tags, activity_id, prompt_id, note, schema_version)
VALUES
    ('000000000000000000000000000000c9'::uuid, 'phone-first-steps:1', 1, 'exception', '2026-11-02 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, 4.5, NULL, NULL, NULL, '{}', '00000000000000000000000000000064'::uuid, NULL, 'First-step ankle pain: eased after walking.', 2);

INSERT INTO checkins_v2 (id, idempotency_key, version, kind, observed_at, recorded_at, fatigue, illness, pain_reported, gait_change, context_tags, activity_id, prompt_id, note, schema_version)
VALUES
    ('000000000000000000000000000000ca'::uuid, 'phone-first-steps:2', 1, 'exception', '2026-11-02 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, NULL, NULL, NULL, '{}', NULL, NULL, 'Private synthetic text', 2);

INSERT INTO symptom_reports (id, checkin_id, site, side, severity, timing)
VALUES
    ('000000000000000000000000000003f2'::uuid, '000000000000000000000000000000c9'::uuid, 'ankle', 'left', 2.5, 'next_morning');

INSERT INTO checkins_v2 (id, idempotency_key, version, kind, observed_at, recorded_at, fatigue, illness, pain_reported, gait_change, context_tags, activity_id, prompt_id, note, schema_version)
VALUES
    ('000000000000000000000000000000cb'::uuid, 'phone-first-steps:3', 1, 'exception', '2026-11-02 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, NULL, NULL, NULL, '{}', NULL, NULL, 'First-step ankle pain: eased after walking.', 2);

INSERT INTO symptom_reports (id, checkin_id, site, side, severity, timing)
VALUES
    ('000000000000000000000000000003fd'::uuid, '000000000000000000000000000000ca'::uuid, 'ankle', 'left', 3, 'next_morning');

INSERT INTO symptom_reports (id, checkin_id, site, side, severity, timing)
VALUES
    ('000000000000000000000000000003fc'::uuid, '000000000000000000000000000000ca'::uuid, 'ankle', 'left', 1, 'next_morning');

INSERT INTO checkins_v2 (id, idempotency_key, version, kind, observed_at, recorded_at, fatigue, illness, pain_reported, gait_change, context_tags, activity_id, prompt_id, note, schema_version)
VALUES
    ('000000000000000000000000000000cc'::uuid, 'phone-first-steps:4', 1, 'exception', '2026-07-04 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, NULL, NULL, NULL, '{}', NULL, NULL, NULL, 2);

INSERT INTO symptom_reports (id, checkin_id, site, side, severity, timing)
VALUES
    ('00000000000000000000000000000407'::uuid, '000000000000000000000000000000cb'::uuid, 'ankle', 'left', 2, 'next_morning');

INSERT INTO symptom_reports (id, checkin_id, site, side, severity, timing)
VALUES
    ('00000000000000000000000000000406'::uuid, '000000000000000000000000000000cb'::uuid, 'ankle', 'left', 1, 'next_morning');

INSERT INTO checkins_v2 (id, idempotency_key, version, kind, observed_at, recorded_at, fatigue, illness, pain_reported, gait_change, context_tags, activity_id, prompt_id, note, schema_version)
VALUES
    ('000000000000000000000000000000cd'::uuid, 'phone-first-steps:5', 1, 'exception', '2026-11-02 03:30:00.125000+00:00'::timestamptz, '2026-11-03 03:30:00.125000+00:00'::timestamptz, NULL, NULL, NULL, NULL, '{}', NULL, NULL, NULL, 2);

INSERT INTO checkins_v2 (id, idempotency_key, version, kind, observed_at, recorded_at, fatigue, illness, pain_reported, gait_change, context_tags, activity_id, prompt_id, note, schema_version)
VALUES
    ('000000000000000000000000000000ce'::uuid, 'phone-first-steps:6', 1, 'exception', '2026-11-03 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, NULL, NULL, NULL, '{}', NULL, NULL, NULL, 2);

INSERT INTO checkins_v2 (id, idempotency_key, version, kind, observed_at, recorded_at, fatigue, illness, pain_reported, gait_change, context_tags, activity_id, prompt_id, note, schema_version)
VALUES
    ('000000000000000000000000000000cf'::uuid, 'different-form', 1, 'exception', '2026-11-02 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, NULL, NULL, NULL, '{}', NULL, NULL, 'First steps: no ankle pain.', 2);

INSERT INTO prompts (id, kind, activity_id, session_uid, opens_at, closes_at, status)
VALUES
    ('0000000000000000000000000000012c'::uuid, 'delayed_symptom', NULL, '00000000000000000000000000000190'::uuid, '2026-07-05 03:30:00.125000+00:00'::timestamptz, '2026-11-02 03:30:00.125000+00:00'::timestamptz, 'open');

INSERT INTO prompts (id, kind, activity_id, session_uid, opens_at, closes_at, status)
VALUES
    ('0000000000000000000000000000012d'::uuid, 'delayed_symptom', NULL, '00000000000000000000000000000191'::uuid, '2026-11-02 03:30:00.125000+00:00'::timestamptz, NULL, 'open');

INSERT INTO prompts (id, kind, activity_id, session_uid, opens_at, closes_at, status)
VALUES
    ('0000000000000000000000000000012e'::uuid, 'delayed_symptom', NULL, '00000000000000000000000000000192'::uuid, '2026-11-02 03:30:00.125000+00:00'::timestamptz, '2026-11-01 03:30:00.125000+00:00'::timestamptz, 'answered');

INSERT INTO prompts (id, kind, activity_id, session_uid, opens_at, closes_at, status)
VALUES
    ('0000000000000000000000000000012f'::uuid, 'delayed_symptom', NULL, '00000000000000000000000000000193'::uuid, '2026-11-03 03:30:00.125000+00:00'::timestamptz, NULL, 'open');

INSERT INTO prompts (id, kind, activity_id, session_uid, opens_at, closes_at, status)
VALUES
    ('00000000000000000000000000000130'::uuid, 'delayed_symptom', NULL, '00000000000000000000000000000194'::uuid, '2026-07-04 03:30:00.125000+00:00'::timestamptz, NULL, 'open');
