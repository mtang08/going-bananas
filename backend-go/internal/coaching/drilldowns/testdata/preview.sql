UPDATE activities SET resolution_state='resolved', canonical_revision=1, field_provenance='{}', distance_m=8000;
UPDATE session_rpe SET collected_at='2026-11-03T04:00Z';
UPDATE checkins_v2 SET version=1, idempotency_key='synthetic';
UPDATE calendar_session_revisions SET recipe_id='REC002' WHERE revision=2;
UPDATE metric_results SET config_hash='superseded' ;
