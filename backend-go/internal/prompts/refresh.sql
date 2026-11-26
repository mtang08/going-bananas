WITH clock AS (
 SELECT $1::timestamptz AS now,($1 AT TIME ZONE coalesce((SELECT timezone FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York'))::date AS today
),
runs AS (
 SELECT a.*,coalesce((SELECT rpe FROM session_rpe WHERE activity_id=a.id AND source='manual'),
   (SELECT rpe FROM session_rpe WHERE activity_id=a.id AND source='garmin_fit'),a.workout_rpe) AS effective_rpe
 FROM activities a WHERE a.sport IN ('running','trail_running','treadmill_running') AND resolution_state='resolved'
 AND NOT coalesce((SELECT excluded FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1),false)
),
latest AS (SELECT DISTINCT ON(session_uid) r.* FROM calendar_session_revisions r JOIN app_state h ON h.id=1
 WHERE h.calendar_head_version>0 AND calendar_version_number<=h.calendar_head_version ORDER BY session_uid,calendar_version_number DESC,revision DESC),
plans AS (SELECT l.*,m.reason_codes FROM latest l JOIN metric_results m ON m.subject_key=l.session_uid::text AND
 m.metric_id='planned_actual_session' AND m.method_version='v2' AND m.is_current,clock
 WHERE l.kind='run' AND NOT l.deleted AND l.local_date BETWEEN today-7 AND today),
-- Calendar prompts have no expiry timestamp. Activity prompts close 48 hours after the run.
desired AS (
 SELECT 'rpe' AS kind,id AS activity_id,NULL::uuid AS session_uid,end_at AS opens_at,end_at+interval '48 hours' AS closes_at
 FROM runs,clock WHERE end_at<=clock.now
 UNION ALL SELECT 'delayed_symptom',id,NULL,end_at+interval '16 hours',end_at+interval '48 hours' FROM runs r,clock
 WHERE end_at<=clock.now AND (EXISTS(SELECT FROM metric_results WHERE metric_id='long_run_exposure' AND method_version='v1' AND is_current AND subject_key=r.id::text AND value->>'classification'='long')
 OR EXISTS(SELECT FROM checkins_v2 c JOIN symptom_reports s ON s.checkin_id=c.id WHERE c.observed_at>=r.start_at-interval '336 hours' AND c.observed_at<r.start_at AND s.severity>0))
 UNION ALL SELECT 'missing_activity',NULL,session_uid,clock.now,NULL FROM plans,clock WHERE local_date<today AND 'NO_ACTIVITY_FOUND'=ANY(reason_codes)
 UNION ALL SELECT 'unmatched_session',NULL,session_uid,clock.now,NULL FROM plans,clock WHERE reason_codes && array['MOVE_CANDIDATE','AMBIGUOUS_MATCH']::varchar[]
),
combined AS (
 SELECT p.id,p.status AS previous,coalesce(p.kind,d.kind) AS kind,coalesce(p.activity_id,d.activity_id) AS activity_id,
 coalesce(p.session_uid,d.session_uid) AS session_uid,coalesce(p.opens_at,d.opens_at) AS opens_at,
 CASE WHEN p.id IS NULL THEN d.closes_at ELSE p.closes_at END AS closes_at,d.kind IS NOT NULL AS wanted
 FROM prompts p FULL JOIN desired d ON p.kind=d.kind AND coalesce(p.activity_id,p.session_uid)=coalesce(d.activity_id,d.session_uid)
),
-- Keep terminal answers and dismissals, even after their originating facts disappear.
states AS (
 SELECT c.*,CASE
 WHEN previous IN ('dismissed','answered') THEN previous
 WHEN kind='rpe' AND EXISTS(SELECT FROM runs r WHERE r.id=c.activity_id AND r.effective_rpe BETWEEN 0 AND 10) THEN 'answered'
 WHEN kind='delayed_symptom' AND EXISTS(SELECT FROM checkins_v2 x WHERE x.kind='delayed_followup' AND (x.activity_id=c.activity_id OR x.prompt_id=c.id)) THEN 'answered'
 WHEN kind IN ('missing_activity','unmatched_session') AND EXISTS(
   SELECT FROM session_completions s WHERE s.session_uid=c.session_uid AND
   (s.activity_id IN (SELECT id FROM runs) OR s.strong_workout_id IN (SELECT id FROM strong_workouts WHERE resolution_state='resolved')
    OR s.manual_session_id IN (SELECT id FROM manual_sessions)
    OR (num_nonnulls(s.activity_id,s.strong_workout_id,s.manual_session_id)=0 AND s.match_method='user_marked' AND s.status IN ('unknown','skipped')))) THEN 'answered'
 WHEN NOT wanted OR previous='expired' OR closes_at<=clock.now THEN 'expired'
 ELSE 'open' END AS status
 FROM combined c,clock
),
created AS (
 INSERT INTO prompts(id,kind,activity_id,session_uid,opens_at,closes_at,status)
 SELECT gen_random_uuid(),kind,activity_id,session_uid,opens_at,closes_at,status FROM states WHERE id IS NULL
 ON CONFLICT DO NOTHING RETURNING status
),
updated AS (
 UPDATE prompts p SET status=s.status FROM states s WHERE s.id=p.id AND s.status<>s.previous RETURNING p.status
),
changes AS (SELECT status FROM created UNION ALL SELECT status FROM updated)
SELECT (SELECT count(*) FROM created),count(*) FILTER(WHERE status='expired'),count(*) FILTER(WHERE status='answered') FROM changes
