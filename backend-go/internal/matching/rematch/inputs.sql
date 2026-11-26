-- Reconcile the edited day and its neighbors, using two further context days.
WITH head AS (SELECT calendar_head_version AS n FROM app_state WHERE id=1),
origin AS (SELECT min(local_date) AS day FROM calendar_session_revisions,head WHERE calendar_version_number<=head.n AND head.n>0),
days AS (SELECT DISTINCT d::date+i AS day FROM unnest($1::text[]) d CROSS JOIN generate_series(-1,1) i,origin WHERE d::date+i>=origin.day),
context AS (SELECT DISTINCT d.day+i AS day FROM days d CROSS JOIN generate_series(-2,2) i,origin WHERE d.day+i>=origin.day),
bounds AS (SELECT min(day) AS first,max(day) AS last FROM context),
latest AS (SELECT DISTINCT ON(session_uid) r.* FROM calendar_session_revisions r,head
 WHERE calendar_version_number<=head.n ORDER BY session_uid,calendar_version_number DESC,revision DESC),
plans AS (SELECT * FROM latest,bounds WHERE NOT deleted AND local_date BETWEEN first AND last),
zone AS (SELECT coalesce((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York') AS name),
activity_dates AS (SELECT a.*, (a.start_at AT TIME ZONE zone.name)::date AS athlete_day FROM activities a,zone),
subjects AS (
 SELECT a.id::text AS key,a.athlete_day AS day,'run' AS kind,a.timer_s,a.distance_m,
 EXISTS(SELECT FROM activity_workout_steps s WHERE s.activity_id=a.id) AS steps
 FROM activity_dates a,bounds
 WHERE a.athlete_day BETWEEN first AND last AND a.sport IN ('running','trail_running','treadmill_running') AND a.resolution_state='resolved'
 AND NOT coalesce((SELECT excluded FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1),false)
 UNION ALL SELECT 'strong:'||id,local_date,'strength',NULL,NULL,false FROM strong_workouts,bounds WHERE resolution_state='resolved' AND local_date BETWEEN first AND last
 UNION ALL SELECT 'manual:'||id,date,'strength',NULL,NULL,false FROM manual_sessions,bounds WHERE kind='strength' AND linked_activity_id IS NULL AND date BETWEEN first AND last
),
-- Ineligible recordings still locate stale automatic associations.
holders AS (SELECT c.*,coalesce(c.activity_id::text,'strong:'||c.strong_workout_id,'manual:'||c.manual_session_id) AS key,
 coalesce(a.athlete_day,s.local_date,m.date) AS actual FROM session_completions c
 LEFT JOIN activity_dates a ON a.id=c.activity_id LEFT JOIN strong_workouts s ON s.id=c.strong_workout_id LEFT JOIN manual_sessions m ON m.id=c.manual_session_id),
-- A moved or deleted plan can have an older revision inside the context.
history AS (SELECT DISTINCT session_uid FROM calendar_session_revisions,head WHERE local_date IN (SELECT day FROM context) AND calendar_version_number<=head.n),
runs AS (SELECT key, day, kind,timer_s,distance_m,steps,true AS eligible FROM subjects
 UNION ALL SELECT key,actual,NULL,NULL,NULL,false,false FROM holders h
 WHERE actual IN (SELECT day FROM context) AND NOT EXISTS(SELECT FROM subjects s WHERE s.key=h.key))
SELECT jsonb_build_object(
 'days',(SELECT jsonb_agg(day ORDER BY day) FROM days),
 'context_days',(SELECT jsonb_agg(day ORDER BY day) FROM context),
 'planned',(SELECT jsonb_agg(jsonb_build_object('session_uid',session_uid,'local_date',local_date,'kind',kind,'planned_duration_s',planned_duration_s,'planned_distance_m',planned_distance_m,'structure',structure) ORDER BY local_date,kind,slot,session_uid) FROM plans),
 'runs',(SELECT jsonb_agg(jsonb_build_object('subject_key',key,'local_date',day,'kind',kind,'timer_s',timer_s,'distance_m',distance_m,'has_workout_steps',steps,'eligible',eligible) ORDER BY day,key) FROM runs),
 'completions',(SELECT jsonb_agg(jsonb_build_object('session_uid',session_uid,'subject_key',key,'status',status,'match_method',match_method) ORDER BY session_uid)
 FROM holders WHERE session_uid IN (SELECT session_uid FROM history) OR actual IN (SELECT day FROM context)))
