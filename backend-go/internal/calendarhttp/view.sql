WITH selected AS (
 SELECT DISTINCT ON (session_uid) r.* FROM calendar_session_revisions r
 WHERE calendar_version_number <= $1
 ORDER BY session_uid,calendar_version_number DESC,revision DESC
), planned AS (SELECT * FROM selected WHERE NOT deleted),
head AS (
 SELECT DISTINCT ON (session_uid) deleted, local_date FROM calendar_session_revisions
 WHERE calendar_version_number <= $2 ORDER BY session_uid,calendar_version_number DESC,revision DESC
), sessions AS (
 SELECT p.local_date,p.slot,p.session_uid,to_jsonb(p) || jsonb_build_object(
  'certainty',CASE WHEN p.local_date <= $5::date + 6 THEN 'committed' ELSE 'provisional' END,
  'is_original',p.revision=1,'changed_by_version',p.calendar_version_number,
  'exception_patch',CASE WHEN ep.id IS NOT NULL THEN jsonb_build_object(
   'patch_id',ep.id,'proposal_id',ep.proposal_id,'reassess_on',ep.reassess_on,'status',ep.status) END) AS body
 FROM planned p LEFT JOIN exception_patches ep ON ep.calendar_version_number=p.calendar_version_number
 WHERE p.local_date BETWEEN $3::date AND $4::date
), runs AS (
 SELECT a.id AS activity_id,(a.start_at AT TIME ZONE $6)::date AS local_date,a.timer_s,a.distance_m,a.start_at
 FROM activities a LEFT JOIN LATERAL (
  SELECT excluded FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1
 ) ann ON true WHERE a.sport IN ('running','trail_running','treadmill_running')
 AND a.resolution_state='resolved' AND ann.excluded IS NOT TRUE
 AND a.start_at >= ($3::date::timestamp AT TIME ZONE $6) AND a.start_at < (($4::date+1)::timestamp AT TIME ZONE $6)
), actual AS (
 SELECT c.*,CASE WHEN c.activity_id IS NOT NULL THEN (a.start_at AT TIME ZONE $6)::date
  WHEN c.strong_workout_id IS NOT NULL THEN s.local_date WHEN c.manual_session_id IS NOT NULL THEN m.date
  ELSE p.local_date END AS local_date
 FROM session_completions c LEFT JOIN activities a ON a.id=c.activity_id
 LEFT JOIN strong_workouts s ON s.id=c.strong_workout_id LEFT JOIN manual_sessions m ON m.id=c.manual_session_id
 LEFT JOIN planned p ON p.session_uid=c.session_uid
), completions AS (
 SELECT actual.*,CASE WHEN status='extra' AND r.activity_id IS NOT NULL THEN
  jsonb_build_object('distance_m',r.distance_m,'timer_s',r.timer_s) ELSE '{}'::jsonb END AS extra
 FROM actual LEFT JOIN runs r USING(activity_id) WHERE actual.local_date BETWEEN $3::date AND $4::date
), versions AS (
 SELECT number,kind,actor,created_at FROM calendar_versions WHERE number <= $2 ORDER BY number DESC LIMIT 50
)
SELECT (SELECT max(local_date)::text FROM head WHERE NOT deleted),
 coalesce((SELECT jsonb_agg(body ORDER BY local_date,slot,session_uid) FROM sessions),'[]'),
 coalesce((SELECT jsonb_agg((to_jsonb(c)-'extra') || extra ORDER BY updated_at,id) FROM completions c),'[]'),
 coalesce((SELECT jsonb_agg(to_jsonb(r)-'start_at' ORDER BY start_at,activity_id) FROM runs r
  WHERE NOT EXISTS(SELECT FROM completions c WHERE c.activity_id=r.activity_id)),'[]'),
 coalesce((SELECT jsonb_agg(to_jsonb(v) ORDER BY number DESC) FROM versions v),'[]')
