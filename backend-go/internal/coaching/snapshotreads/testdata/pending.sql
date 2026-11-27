-- Synthetic setup captured for the saved contract response.
UPDATE block_benchmarks SET match_method='auto' WHERE block_benchmarks.id = '00000000000000000000000000015fa6'::uuid;

UPDATE block_versions SET benchmark='{"kind": "time_trial", "protocol": "time_trial_5k", "planned_date": "2026-11-01"}'::jsonb WHERE block_versions.id = '00000000000000000000000000015fa5'::uuid;
