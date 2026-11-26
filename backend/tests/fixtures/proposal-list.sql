-- For the Go HTTP comparison. Load into an empty, migrated, disposable test database with psql -1.
DO $$
BEGIN
    IF right(current_database(), 5) <> '_test'
       OR EXISTS (SELECT FROM coach_proposals)
       OR EXISTS (SELECT FROM coach_snapshots)
       OR NOT EXISTS (SELECT FROM app_state WHERE id = 1 AND data_revision = 0) THEN
        RAISE EXCEPTION 'Proposal fixture requires a fresh migrated test database';
    END IF;
END
$$;

UPDATE app_state SET data_revision = 17 WHERE id = 1;

INSERT INTO coach_snapshots (
    id, operation, as_of, generated_at, calendar_version_number, data_revision, payload,
    source_fingerprint, source_versions, kb_digest, payload_sha256, kb_package_version, kb_routes, approx_tokens
) VALUES (
    '00000000-0000-0000-0000-000000000001', 'review_rolling_plan', '2026-01-01',
    '2026-01-01T01:00:00Z', 0, 17, '{}', 'fixture', '{}', 'fixture', 'fixture', 'fixture', '[]', 0
);

-- Row 1 sorts first by time. Other rows tie on time and sort by descending UUID.
-- Only one draft can be open, so stale/invalid filters produce an empty list in this fixture.
INSERT INTO coach_proposals (
    id, operation, snapshot_id, base_calendar_version, status, submitted_at, decided_at,
    discarded_at, headline, confidence, payload, skill_version, input_hash
)
SELECT lpad(to_hex(i), 32, '0')::uuid, 'review_rolling_plan', '00000000-0000-0000-0000-000000000001',
       0, CASE i WHEN 52 THEN 'discarded' WHEN 51 THEN 'pending' WHEN 50 THEN 'partially_accepted'
            WHEN 49 THEN 'rejected' ELSE 'accepted' END,
       CASE i WHEN 1 THEN '2026-01-02T00:00:00.123400Z'::timestamptz ELSE '2026-01-01T00:00:00Z' END,
       CASE i WHEN 50 THEN '2026-01-03T00:00:00.123400Z'::timestamptz END,
       CASE i WHEN 52 THEN '2026-01-03T00:00:00Z'::timestamptz END,
       i::text, '{}', CASE i WHEN 1 THEN '{}'::jsonb ELSE '{"changes":[{},{}]}'::jsonb END, 'fixture', md5(i::text)
FROM generate_series(1, 52) AS i;
