-- Session-local projections of the migrated schema keep parity fixtures isolated.
CREATE TEMP TABLE profile_versions AS TABLE profile_versions WITH NO DATA;
CREATE TEMP TABLE activities AS TABLE activities WITH NO DATA;
CREATE TEMP TABLE activity_annotations AS TABLE activity_annotations WITH NO DATA;
CREATE TEMP TABLE app_state AS TABLE app_state WITH NO DATA;
CREATE TEMP TABLE calendar_versions AS TABLE calendar_versions WITH NO DATA;
CREATE TEMP TABLE calendar_session_revisions AS TABLE calendar_session_revisions WITH NO DATA;
CREATE TEMP TABLE session_completions AS TABLE session_completions WITH NO DATA;
CREATE TEMP TABLE manual_sessions AS TABLE manual_sessions WITH NO DATA;
CREATE TEMP TABLE coverage_intervals AS TABLE coverage_intervals WITH NO DATA;
INSERT INTO app_state (id,data_revision,calendar_head_version) VALUES (1,17,0);
INSERT INTO profile_versions (id,version,timezone) VALUES (gen_random_uuid(),1,'America/Denver');
