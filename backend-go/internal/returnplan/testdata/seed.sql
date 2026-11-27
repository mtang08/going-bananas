CREATE TEMP TABLE profile_versions AS SELECT * FROM profile_versions WITH NO DATA;
CREATE TEMP TABLE app_state AS SELECT * FROM app_state WITH NO DATA;
CREATE TEMP TABLE calendar_session_revisions AS SELECT * FROM calendar_session_revisions WITH NO DATA;
CREATE TEMP TABLE session_completions AS SELECT * FROM session_completions WITH NO DATA;
CREATE TEMP TABLE activity_annotations AS SELECT * FROM activity_annotations WITH NO DATA;
CREATE TEMP TABLE activities AS SELECT * FROM activities WITH NO DATA;
CREATE TEMP TABLE trips AS SELECT * FROM trips WITH NO DATA;

INSERT INTO profile_versions(id,version,timezone,facts) VALUES(md5('profile')::uuid,4,'America/Denver','{}');
INSERT INTO app_state(id,calendar_head_version,data_revision) VALUES(1,3,11);

INSERT INTO calendar_session_revisions(id,session_uid,calendar_version_number,revision,deleted,locked,kind,slot,
    local_date,intent,recipe_id,planned_duration_s,custom,placeholder,brief,structure)
SELECT md5('id'||n)::uuid,md5('uid'||n)::uuid,2,1,false,n=1,'run',0,
    date '2026-11-01'+n,'Run '||n,CASE WHEN n=12 THEN 'REC002' ELSE 'REC001' END,
    CASE WHEN n=15 THEN 3000 WHEN n=16 THEN null ELSE 1200 END,false,false,
    CASE WHEN n=17 THEN '{"effort":{"rpe_low":2,"rpe_high":7}}'::jsonb END,
    CASE WHEN n=18 THEN '[{"type":"repeat","count":2,"steps":[{"type":"work","duration_type":"time","duration_value":600}]}]'::jsonb END
FROM generate_series(0,20) n;
INSERT INTO calendar_session_revisions(id,session_uid,calendar_version_number,revision,deleted,locked,kind,slot,local_date,intent,custom,placeholder)
VALUES(md5('latest')::uuid,md5('uid2')::uuid,3,2,true,false,'run',0,'2026-11-03','deleted',false,false);
INSERT INTO session_completions(id, session_uid,status) VALUES(md5('complete')::uuid,md5('uid3')::uuid,'skipped');
INSERT INTO session_completions(id, session_uid,status,activity_id) VALUES(md5('linked')::uuid,md5('uid4')::uuid,'unknown',md5('link')::uuid);
INSERT INTO trips(id,start_date,end_date,status,day_availability,running_access)
VALUES(md5('trip')::uuid,'2026-11-14','2026-11-15','confirmed','[{"date":"2026-11-14","availability":"reduced"}]','normal');
INSERT INTO activities(id,resolution_state,sport,start_at,local_date) VALUES
    (md5('excluded')::uuid,'resolved','running','2026-11-15T09:00Z','2026-11-15'),
    (md5('not_a_run')::uuid,'resolved','walking','2026-11-15T10:00Z','2026-11-15'),
    (md5('actual')::uuid,'resolved','trail_running','2026-11-22T01:00Z','2026-11-22');
INSERT INTO activity_annotations(id,activity_id,version,excluded) VALUES
    (md5('a')::uuid,md5('excluded')::uuid,1,false),(md5('b')::uuid,md5('excluded')::uuid,2,true);
