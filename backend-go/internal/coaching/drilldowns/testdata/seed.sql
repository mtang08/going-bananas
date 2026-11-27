SET LOCAL TIME ZONE 'Asia/Kathmandu';
CREATE TEMP TABLE app_state AS SELECT * FROM app_state WITH NO DATA;
CREATE TEMP TABLE profile_versions AS SELECT * FROM profile_versions WITH NO DATA;
CREATE TEMP TABLE activities AS SELECT * FROM activities WITH NO DATA;
CREATE TEMP TABLE session_rpe AS SELECT * FROM session_rpe WITH NO DATA;
CREATE TEMP TABLE metric_configs AS SELECT * FROM metric_configs WITH NO DATA;
CREATE TEMP TABLE metric_results AS SELECT * FROM metric_results WITH NO DATA;
CREATE TEMP TABLE calendar_versions AS SELECT * FROM calendar_versions WITH NO DATA;
CREATE TEMP TABLE calendar_session_revisions AS SELECT * FROM calendar_session_revisions WITH NO DATA;
CREATE TEMP TABLE session_completions AS SELECT * FROM session_completions WITH NO DATA;
CREATE TEMP TABLE activity_laps AS SELECT * FROM activity_laps WITH NO DATA;
CREATE TEMP TABLE activity_workout_steps AS SELECT * FROM activity_workout_steps WITH NO DATA;
CREATE TEMP TABLE recovery_observations AS SELECT * FROM recovery_observations WITH NO DATA;
CREATE TEMP TABLE checkins_v2 AS SELECT * FROM checkins_v2 WITH NO DATA;
CREATE TEMP TABLE symptom_reports AS SELECT * FROM symptom_reports WITH NO DATA;
CREATE TEMP TABLE prompts AS SELECT * FROM prompts WITH NO DATA;
INSERT INTO app_state(id,data_revision,calendar_head_version) VALUES(1,4,2);
INSERT INTO profile_versions(id,version,timezone,facts) VALUES(md5('prof')::uuid,1,'America/Denver','{}');
INSERT INTO activities(id,original_start,start_at,end_at,local_date,sport,workout_rpe,timer_s,fit_status,treadmill_interval_paces) VALUES
('00000000-0000-0000-0000-000000000001','synthetic','2026-11-03T00:00Z','2026-11-03T01:00Z','2026-11-02','treadmill_running',4,3600,'decoded',
'{"0":{"lap_identity":"2026-11-03T00:00:00+00:00||600.0|600.0|None","pace_s_per_mile":523.5}}');
INSERT INTO session_rpe(id,activity_id,source,rpe) SELECT md5('rpe')::uuid,id,'manual',3 FROM activities;
INSERT INTO calendar_versions(id,number) VALUES(md5('v1')::uuid,1),(md5('v2')::uuid,2);
INSERT INTO calendar_session_revisions(id,session_uid,revision,calendar_version_number,deleted,local_date,slot,kind,recipe_id,custom,locked,legacy_unstructured,placeholder,intent,certainty,planned_duration_s)
SELECT md5('rev'||n)::uuid,md5('uid')::uuid,n,n,false,date '2026-11-01'+n,0,'run','REC001',false,false,false,false,'Synthetic easy run','committed',1800 FROM generate_series(1,2)n;
INSERT INTO session_completions(id,session_uid,activity_id,status,match_method,version,input_version,updated_at)
SELECT md5('comp')::uuid,md5('uid')::uuid,id,'completed_as_planned','explicit',1,1,'2026-11-03T04:00Z' FROM activities;
INSERT INTO activity_laps(id,activity_id,lap_index,start_at,timer_s,elapsed_s) SELECT md5('lap')::uuid,id,0,start_at,600,600 FROM activities;
INSERT INTO activity_workout_steps(id,activity_id,message_index,step_name,duration_type) SELECT md5('step')::uuid,id,1,'Example step','time' FROM activities;
INSERT INTO checkins_v2(id,kind,activity_id,observed_at,recorded_at,pain_reported,gait_change) SELECT md5('check')::uuid,'delayed_followup',id,'2026-11-04T04:00Z','2026-11-04T05:00Z',false,'no' FROM activities;
INSERT INTO prompts(id,kind,activity_id,status,opens_at,closes_at) SELECT md5('prompt')::uuid,'delayed_symptom',id,'open','2026-11-03T04:00Z','2026-11-04T04:00Z' FROM activities;
INSERT INTO metric_configs(id,metric_id,method_version,config_hash,config)
SELECT md5(x.metric_id)::uuid,x.metric_id,x.method_version,x.config_hash,'{"synthetic":true}' FROM jsonb_to_recordset('@IDENTITIES@'::jsonb) x(metric_id text, method_version text, config_hash text);
INSERT INTO metric_results (id,metric_id,method_version,config_hash,subject_type,subject_key,status,value,window_start,calculated_at,reason_codes,quality_flags,anchor_keys,source_refs,dependency_hash,timezone,is_current)
SELECT c.id,c.metric_id,c.method_version,c.config_hash,CASE WHEN c.metric_id='planned_actual_session' THEN 'session' ELSE 'activity' END,
CASE WHEN c.metric_id='planned_actual_session' THEN md5('uid')::uuid::text ELSE a.id::text END,'available',
CASE c.metric_id WHEN 'long_run_exposure' THEN '{"classification":"long"}'::jsonb WHEN 'session_rpe_load' THEN '{"load_au":120}'::jsonb WHEN 'symptom_response_timeline' THEN '{"reports":[]}'::jsonb ELSE '{}'::jsonb END,
a.start_at,'2026-11-05T06:45:35.25Z','{}','{}','{}','{"activity":{"synthetic":true}}','test','America/Denver',true
FROM metric_configs c,activities a WHERE metric_id IN ('work_interval_execution','intensity_time_distribution','aerobic_efficiency','session_rpe_load','symptom_response_timeline','planned_actual_session','long_run_exposure');
