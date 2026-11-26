UPDATE app_state SET calendar_head_version=1 WHERE id=1;
INSERT INTO calendar_versions(id,number) VALUES(gen_random_uuid(),1);
INSERT INTO activities(id,start_at,local_date,sport,distance_m,timer_s,resolution_state)
SELECT md5(label)::uuid, ts::timestamptz, '2000-01-01',sport,metres,seconds,resolution
FROM (VALUES
 ('prior','2030-01-05 12:00Z','trail_running',4000,2000,'resolved'),
 ('first','2030-01-07 12:00Z','running',5000,2500,'resolved'),
 ('second','2030-01-09 12:00Z','treadmill_running',6000,3000,'resolved'),
 ('zero','2030-01-09 12:00Z','running',0,60,'resolved'),
 ('missing','2030-01-09 12:00Z','running',NULL,60,'resolved'),
 ('excluded','2030-01-08 12:00Z','running',9000,3000,'resolved'),
 ('unresolved','2030-01-08 12:00Z','running',9000,3000,'unresolved'),
 ('cycling','2030-01-08 12:00Z','cycling',9000,3000,'resolved')
) f(label,ts,sport,metres,seconds,resolution);
INSERT INTO activity_annotations(id,activity_id,version,excluded)
VALUES (gen_random_uuid(),md5('excluded')::uuid,1,false),(gen_random_uuid(),md5('excluded')::uuid,2,true);
INSERT INTO calendar_session_revisions(id,session_uid,revision,calendar_version_number,deleted,
  local_date,slot,kind,planned_distance_m,planned_duration_s,structure)
SELECT gen_random_uuid(),md5(label)::uuid,revision,ver,deleted,'2030-01-01'::date+(day-1),0,'run',metres,seconds,steps::jsonb
FROM (VALUES
 ('past',1,1,false,7,2000,NULL,NULL),
 ('today',1,1,false,9,6000,NULL,NULL),
 ('skip',1,1,false,10,1000,NULL,NULL),
 ('friday',1,1,false,11,3000,NULL,NULL),
 ('friday',2,2,false,11,33000,NULL,NULL),
 ('moved',1,1,false,12,2000,NULL,NULL),
 ('sunday',1,1,false,13,NULL,600,NULL),
 ('known',1,1,false,13,NULL,300,'[{"type":"work","duration_type":"time","duration_value":200,"target":{"modality":"speed","low":2,"high":4}}]'),
 ('unknown',1,1,false,10,1000,NULL,NULL),('badstructure',1,1,false,10,NULL,300,'[]'),
 ('deleted',1,1,false,31,1000,NULL,NULL),('deleted',2,1,true,31,1000,NULL,NULL),
 ('later',1,1,false,19,1000,NULL,NULL)
) f(label,revision,ver,deleted,day,metres,seconds,steps);
INSERT INTO session_completions(id,session_uid,activity_id,status)
VALUES (gen_random_uuid(),md5('today')::uuid,md5('second')::uuid,'completed_as_planned'),
 (gen_random_uuid(),md5('skip')::uuid,NULL,'skipped'),
 (gen_random_uuid(),md5('moved')::uuid,md5('prior')::uuid,'moved'),
 (gen_random_uuid(),md5('unknown')::uuid,NULL,'unknown');
INSERT INTO manual_sessions(id,date,kind,duration_s,linked_activity_id)
VALUES(gen_random_uuid(),'2030-01-08','run',1800,NULL),(gen_random_uuid(),'2030-01-09','run',3000,md5('second')::uuid);
INSERT INTO coverage_intervals(id,dataset,start_date,end_date,status,fully_enumerated)
VALUES(gen_random_uuid(),'activities','2030-01-07','2030-01-08','complete',true),
 (gen_random_uuid(),'activities','2030-01-09','2030-01-09','complete',true);
