-- Synthetic proposal rows used to capture both historical HTTP response fixtures.
UPDATE app_state SET data_revision = 17 WHERE id = 1;

INSERT INTO coach_snapshots (
    id, operation, as_of, generated_at, calendar_version_number, data_revision, payload,
    source_fingerprint, source_versions, kb_digest, payload_sha256, kb_package_version, kb_routes, approx_tokens
) VALUES (
    '00000000-0000-0000-0000-000000000701', 'review_rolling_plan', '2026-01-01',
    '2026-01-01T01:00:00Z', 0, 17, '{}', 'fixture', '{}', 'fixture', 'fixture', 'fixture', '[]', 0
);

INSERT INTO coach_proposals (
    id, operation, snapshot_id, base_calendar_version, status, submitted_at, decided_at, headline,
    confidence, payload, skill_version, input_hash, revision, why, decision_result
) VALUES
(
    '00000000-0000-0000-0000-000000000702', 'review_rolling_plan', '00000000-0000-0000-0000-000000000701',
    0, 'pending', '2026-01-01T15:33:22.493820Z', NULL, 'Revised easy run', '{"decision":"moderate"}',
    '{"operation":"review_rolling_plan","headline":"Revised easy run","changes":[{"change_id":"c1","material_flags":["volume"]}]}',
    'fixture', 'proposal-view-pending', 2, '[{"kind":"observation","text":"Synthetic session"}]', NULL
),
(
    '00000000-0000-0000-0000-000000000703', 'review_rolling_plan', '00000000-0000-0000-0000-000000000701',
    0, 'accepted', '2026-01-02T15:33:22Z', '2026-01-03T15:33:22.123400Z', 'Accepted easy run', '{}',
    '{"headline":"Accepted easy run"}',
    'fixture', 'proposal-view-accepted', 1, '[]',
    '{"status":"accepted","calendar_version":0,"block_version_id":null,"anchor_keys":[],"stale_proposals":[]}'
);

INSERT INTO coach_proposal_revisions (
    proposal_id, revision, saved_at, reason, payload, changed_change_ids, changed_fields
)
SELECT id, 1, submitted_at, 'Initial draft',
       CASE status WHEN 'pending' THEN '{"headline":"Original easy run"}'::jsonb ELSE payload END,
       '{}', '{}' FROM coach_proposals;
INSERT INTO coach_proposal_revisions (
    proposal_id, revision, saved_at, reason, payload, changed_change_ids, changed_fields
)
SELECT id, 2, '2026-01-01T16:00:00Z', 'Update headline', payload, '{}', '{headline}'
FROM coach_proposals WHERE id='00000000-0000-0000-0000-000000000702';

INSERT INTO coach_proposal_changes (
    id, proposal_id, change_id, op, session_uid, before, after, reason, decision
) VALUES (
    '00000000-0000-0000-0000-000000000704', '00000000-0000-0000-0000-000000000702',
    'c1', 'add', NULL, NULL, '{"kind":"run","planned_duration_s":1800}', 'Easy volume', 'pending'
);
