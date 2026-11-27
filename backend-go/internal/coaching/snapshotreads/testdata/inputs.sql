-- Synthetic setup captured for the saved contract response.
INSERT INTO activities (id, source_account_id, garmin_id, source_identity, start_at, original_start, source_timezone, local_date, sport, subtype, distance_m, elapsed_s, timer_s, end_at, fit_file_id, workout_rpe, workout_feel, fit_status, moving_s, avg_hr_bpm, cadence_spm, source_workout_label, canonical_revision, resolution_state, field_provenance)
VALUES
    ('20996acc368b4d18843da158c0eee444'::uuid, NULL, NULL, NULL, '2027-03-11 14:00:00+00:00'::timestamptz, 'fixture', NULL, '2027-03-11'::date, 'running', NULL, 3920, NULL, 1500, NULL, NULL, NULL, NULL, 'not_fetched', NULL, NULL, NULL, NULL, 1, 'resolved', '{}'::jsonb);

INSERT INTO coverage_intervals (id, dataset, start_date, end_date, observed_start, observed_end, status, completed_at, reason, fully_enumerated)
VALUES
    ('66c448b204a449e78ffc2ab8e5f50a96'::uuid, 'activities', '2026-11-14'::date, '2027-01-22'::date, NULL, NULL, 'complete', NULL, NULL, true),
    ('3be39410bae24dafb80b4d51d252b24d'::uuid, 'activities', '2027-01-23'::date, '2027-03-14'::date, NULL, NULL, 'complete', NULL, NULL, true);

INSERT INTO profile_versions (id, version, effective_at, timezone, cycle_anchor, anchor_confirmed, strength_days_confirmed, scheduled_strength_days, strength_schedule_mode, strength_week_a_start, strength_week_a_days, strength_week_b_days, mobility_week_a_days, mobility_week_b_days, mobility_optional_days, facts, preferences, unknowns)
VALUES
    ('6471ff7d5d67419f8c69e67f58ad206f'::uuid, 1, '2027-02-28 14:00:00+00:00'::timestamptz, 'America/New_York', NULL, true, true, '[1, 3]'::jsonb, 'weekly', NULL, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '{"running_interruption": {"starts_on": "2027-03-13", "review_on": "2027-03-17", "reason": "schedule"}}'::jsonb, '{}'::jsonb, '[]'::jsonb);
