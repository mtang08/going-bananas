// Package blockbenchmark shares the active block and eligible benchmark match across read models.
package blockbenchmark

// Selection defines the relations spec, zone, scheduled and matched.
const Selection = `latest AS (
 SELECT DISTINCT ON (block_uid) * FROM block_versions ORDER BY block_uid,version DESC
), active AS (
 SELECT * FROM latest WHERE status IN ('active','consolidating') ORDER BY created_at DESC,version DESC,id DESC LIMIT 1
), spec AS (
 SELECT b.*, b.benchmark->>'kind' AS kind,(b.benchmark->>'event_id')::uuid AS event_id,
        (b.benchmark->>'planned_date')::date-3 AS first,b.review_date+7 AS last FROM active b
), zone AS (
 SELECT coalesce((SELECT nullif(timezone,'') FROM profile_versions ORDER BY version DESC LIMIT 1),'America/New_York') AS name
), calendar_head AS (
 SELECT DISTINCT ON (session_uid) session_uid,local_date,kind,recipe_id,deleted
 FROM calendar_session_revisions WHERE calendar_version_number <= COALESCE((SELECT calendar_head_version FROM app_state WHERE id=1),0)
 ORDER BY session_uid,calendar_version_number DESC,revision DESC
), scheduled AS (
 SELECT c.session_uid,c.local_date FROM calendar_head c,spec WHERE NOT c.deleted AND c.kind='run' AND c.recipe_id='REC009'
 AND c.local_date BETWEEN spec.first AND spec.last
), manual_match AS (
 SELECT a.id FROM block_benchmarks b JOIN spec ON b.block_uid=spec.block_uid AND b.block_version=spec.version
 JOIN activities a ON a.id=b.activity_id WHERE b.match_method='manual' AND spec.kind IS NOT NULL
), trial_match AS (
 SELECT c.activity_id AS id FROM scheduled s JOIN session_completions c USING (session_uid),spec
 WHERE spec.kind='time_trial' AND c.activity_id IS NOT NULL ORDER BY s.local_date DESC,s.session_uid DESC LIMIT 1
), event_match AS (
 SELECT a.id,e.result_s FROM spec JOIN events e ON e.id=spec.event_id
 CROSS JOIN zone JOIN activities a ON (a.start_at AT TIME ZONE zone.name)::date=e.event_date
 WHERE spec.kind='event' AND e.event_date BETWEEN spec.first AND spec.last
 AND a.sport IN ('running','trail_running','treadmill_running') AND a.resolution_state='resolved'
 AND NOT COALESCE((SELECT excluded FROM activity_annotations WHERE activity_id=a.id ORDER BY version DESC LIMIT 1),false)
 ORDER BY COALESCE(a.distance_m,0) DESC,a.start_at DESC,a.id LIMIT 1
), candidates AS (
 SELECT id,'manual' AS method, NULL::integer AS result_override,1 AS priority FROM manual_match UNION ALL
 SELECT id,'auto',NULL,2 FROM trial_match UNION ALL SELECT id,'auto',result_s,2 FROM event_match
), matched AS (
 SELECT a.*,c.method,c.result_override FROM candidates c JOIN activities a USING (id) ORDER BY c.priority LIMIT 1
)`

// StatusJSON projects a matched benchmark using the timestamp representation of its caller.
func StatusJSON(evidenceTime string) string {
	return `jsonb_build_object('status',CASE WHEN s.kind IS NULL THEN 'not_set' WHEN m.id IS NOT NULL THEN 'completed'
                     WHEN $1::date <= s.review_date+2 THEN 'pending' ELSE 'missed' END,
          'match_method',m.method,'activity_id',m.id,'event_id',s.event_id,'local_date',(m.start_at AT TIME ZONE zone.name)::date,
          'distance_m',round(m.distance_m)::bigint,'result_s',COALESCE(m.result_override,round(m.timer_s)::bigint),
          'rpe',COALESCE((SELECT rpe FROM session_rpe WHERE activity_id=m.id AND source IN ('manual','garmin_fit')
                    ORDER BY (source='manual') DESC,collected_at DESC,id DESC LIMIT 1),m.workout_rpe),
          'scheduled_date',(SELECT max(local_date) FROM scheduled),'evidence_at',` + evidenceTime + `)`
}
